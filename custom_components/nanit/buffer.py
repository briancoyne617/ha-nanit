"""Rolling video buffer manager for Nanit.

Runs ffmpeg as an asyncio subprocess, recording from the camera's RTMPS stream
into 4 × 30-second rotating segment files (2-minute rolling buffer).

When ``async_save_clip`` is called — either manually via the ``nanit.save_clip``
service or automatically on a sound-alert rising edge — the current segment
files are copied to a temp dir, concatenated with ffmpeg, and written as a
timestamped .mp4 in the configured clips directory.

Token rotation is handled automatically: when the Nanit access token refreshes
(the new token is embedded in the RTMPS URL), ffmpeg is restarted so the
stream stays alive.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from homeassistant.core import HomeAssistant, callback

from aionanit import NanitCamera
from aionanit.models import CameraState

from .coordinator import NanitPushCoordinator

_LOGGER = logging.getLogger(__name__)

# Rolling buffer geometry: 4 × 30 s = 2-minute window
_SEGMENT_DURATION = 30
_SEGMENT_COUNT = 4
_SEGMENT_PATTERN = "seg_%03d.ts"

# ffmpeg restart back-off
_RESTART_DELAY_BASE = 5.0
_RESTART_DELAY_MAX = 60.0

# Minimum seconds between consecutive auto-saves (avoid flooding on sustained noise)
_SAVE_COOLDOWN = 60.0


class NanitBufferManager:
    """Manages a rolling 2-minute RTMPS capture and saves clips on demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        camera: NanitCamera,
        token_manager,               # aionanit.auth.TokenManager
        push_coordinator: NanitPushCoordinator,
        baby_name: str,
        clips_dir: Path,
        max_clips: int = 20,
        max_clip_age_days: int = 7,
    ) -> None:
        self._hass = hass
        self._camera = camera
        self._token_manager = token_manager
        self._push_coordinator = push_coordinator
        self._baby_name = baby_name
        self._clips_dir = clips_dir
        self._max_clips = max_clips
        self._max_clip_age_days = max_clip_age_days

        # Hidden sub-directory for the rolling segment files
        self._seg_dir = clips_dir / ".segments"

        self._proc: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._unsubscribe_tokens = None
        self._unsubscribe_coordinator = None
        self._running = False
        self._restart_delay = _RESTART_DELAY_BASE
        self._last_save_ts: float = 0.0
        self._prev_sound_alert: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Create directories, subscribe to events, start the buffer loop."""
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        self._seg_dir.mkdir(parents=True, exist_ok=True)
        self._running = True

        # Restart ffmpeg when the access token rotates
        self._unsubscribe_tokens = self._token_manager.on_tokens_refreshed(
            self._on_tokens_refreshed
        )

        # Auto-save on sound alert
        self._unsubscribe_coordinator = self._push_coordinator.async_add_listener(
            self._handle_coordinator_update
        )

        self._task = self._hass.async_create_background_task(
            self._run_buffer_loop(), "nanit_buffer"
        )

    async def async_shutdown(self) -> None:
        """Stop the buffer loop and clean up subscriptions."""
        self._running = False
        if self._unsubscribe_tokens is not None:
            self._unsubscribe_tokens()
            self._unsubscribe_tokens = None
        if self._unsubscribe_coordinator is not None:
            self._unsubscribe_coordinator()
            self._unsubscribe_coordinator = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        await self._stop_ffmpeg()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    @callback
    def _on_tokens_refreshed(self, _access: str, _refresh: str) -> None:
        """Stop the current ffmpeg process so the loop restarts with a fresh URL."""
        _LOGGER.debug("Nanit token refreshed — restarting buffer ffmpeg")
        if self._proc is not None and self._proc.returncode is None:
            self._hass.async_create_task(self._stop_ffmpeg())

    @callback
    def _handle_coordinator_update(self) -> None:
        """Trigger an auto-save on the rising edge of sound_alert."""
        data: CameraState | None = self._push_coordinator.data
        if data is None:
            return
        alert = data.sensors.sound_alert
        if alert and not self._prev_sound_alert:
            now = time.monotonic()
            if now - self._last_save_ts >= _SAVE_COOLDOWN:
                self._last_save_ts = now
                self._hass.async_create_task(self.async_save_clip(label="sound"))
        self._prev_sound_alert = alert

    # ------------------------------------------------------------------
    # Buffer loop
    # ------------------------------------------------------------------

    async def _run_buffer_loop(self) -> None:
        """Main background loop: keeps ffmpeg running with exponential back-off."""
        while self._running:
            try:
                url = await self._camera.async_get_stream_rtmps_url()
                await self._camera.async_start_streaming()
                await self._start_ffmpeg(url)
                # Block until ffmpeg exits (normally only happens on token rotation
                # or a stream error)
                if self._proc is not None:
                    await self._proc.wait()
                if not self._running:
                    break
                rc = self._proc.returncode if self._proc else "?"
                _LOGGER.warning(
                    "Buffer ffmpeg exited (rc=%s), restarting in %.0f s", rc, self._restart_delay
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning(
                    "Buffer loop error: %s — restarting in %.0f s", err, self._restart_delay
                )

            await asyncio.sleep(self._restart_delay)
            self._restart_delay = min(self._restart_delay * 2, _RESTART_DELAY_MAX)

    async def _start_ffmpeg(self, rtmps_url: str) -> None:
        """Launch ffmpeg with the rotating segment muxer."""
        seg_path = str(self._seg_dir / _SEGMENT_PATTERN)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "warning",
            "-i", rtmps_url,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(_SEGMENT_DURATION),
            "-segment_wrap", str(_SEGMENT_COUNT),
            "-segment_format", "mpegts",
            "-reset_timestamps", "1",
            seg_path,
        ]
        _LOGGER.debug("Starting buffer ffmpeg (segment_wrap=%d × %ds)", _SEGMENT_COUNT, _SEGMENT_DURATION)
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._restart_delay = _RESTART_DELAY_BASE  # reset on successful start

    async def _stop_ffmpeg(self) -> None:
        """Gracefully stop the current ffmpeg process."""
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None

    # ------------------------------------------------------------------
    # Clip saving
    # ------------------------------------------------------------------

    async def async_save_clip(self, label: str = "manual") -> Path | None:
        """Copy the rolling buffer segments and concatenate them into a saved clip.

        Returns the path of the new .mp4, or None if no segments exist yet.
        """
        seg_files = await self._hass.async_add_executor_job(self._gather_segments)
        if not seg_files:
            _LOGGER.warning("nanit buffer: no segments available to save")
            return None

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_name = self._baby_name.replace(" ", "_")
        clip_path = self._clips_dir / f"{safe_name}_{label}_{ts}.mp4"

        # Copy segments to a temp directory so ffmpeg doesn't race the live writer
        tmp_dir = Path(
            await self._hass.async_add_executor_job(
                tempfile.mkdtemp, None, "nanit_", str(self._clips_dir)
            )
        )
        try:
            copied = await self._hass.async_add_executor_job(
                self._copy_segments, seg_files, tmp_dir
            )
            concat_list = tmp_dir / "concat.txt"
            await self._hass.async_add_executor_job(
                concat_list.write_text,
                "\n".join(f"file '{p}'" for p in copied),
            )
            success = await self._run_concat(concat_list, clip_path)
        finally:
            await self._hass.async_add_executor_job(shutil.rmtree, str(tmp_dir), True)

        if success:
            _LOGGER.info("nanit: saved clip %s", clip_path.name)
            await self._hass.async_add_executor_job(self._enforce_limits)
            return clip_path
        return None

    # ------------------------------------------------------------------
    # Helpers (run in executor where noted)
    # ------------------------------------------------------------------

    def _gather_segments(self) -> list[Path]:
        """Return existing segment files sorted chronologically (oldest first)."""
        files = list(self._seg_dir.glob("seg_*.ts"))
        return sorted(files, key=lambda p: p.stat().st_mtime)

    def _copy_segments(self, segs: list[Path], dst_dir: Path) -> list[Path]:
        """Copy segment files into dst_dir and return the new paths."""
        copied = []
        for seg in segs:
            dst = dst_dir / seg.name
            shutil.copy2(seg, dst)
            copied.append(dst)
        return copied

    async def _run_concat(self, concat_list: Path, out_path: Path) -> bool:
        """Run ffmpeg concat demuxer to merge segments into a single .mp4."""
        cmd = [
            "ffmpeg", "-y", "-loglevel", "warning",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(out_path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode != 0:
                _LOGGER.error(
                    "ffmpeg concat failed (rc=%d): %s", proc.returncode, stderr.decode()
                )
                return False
            return True
        except asyncio.TimeoutError:
            _LOGGER.error("ffmpeg concat timed out")
            return False

    def _enforce_limits(self) -> None:
        """Delete clips that exceed the age or count limits (runs in executor)."""
        now = time.time()
        max_age = self._max_clip_age_days * 86400
        clips = sorted(
            self._clips_dir.glob("*.mp4"),
            key=lambda p: p.stat().st_mtime,
        )
        keep: list[Path] = []
        for clip in clips:
            if now - clip.stat().st_mtime > max_age:
                clip.unlink(missing_ok=True)
                _LOGGER.debug("Deleted aged clip: %s", clip.name)
            else:
                keep.append(clip)
        while len(keep) > self._max_clips:
            oldest = keep.pop(0)
            oldest.unlink(missing_ok=True)
            _LOGGER.debug("Deleted excess clip: %s", oldest.name)
