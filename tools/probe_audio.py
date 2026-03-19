#!/usr/bin/env python3
"""Probe Nanit Sound + Light machine via its dedicated WebSocket.

The Nanit sound machine uses a COMPLETELY DIFFERENT WebSocket endpoint
and protobuf schema from the camera:

  Cloud: wss://remote.nanit.com/speakers/{speaker_uid}/user_connect/
  Auth:  Authorization: Bearer {access_token}  (standard SSL)
  Proto: sound_light.proto  (NOT the camera's nanit.proto)

Prerequisites:
  Run `just login` first to create .nanit-session with speaker_uid.

Usage:
  just probe-audio state            # current state (power, volume, sound)
  just probe-audio sounds           # list available sound tracks
  just probe-audio stop             # turn off
  just probe-audio play             # turn on
  just probe-audio set-sound "White Noise.wav"
  just probe-audio set-volume 50    # 0-100
  just probe-audio all              # run full probe sequence

For local (LAN-only) operation, provide the speaker IP:
  just probe-audio --speaker-ip 192.168.0.164 state

Note: Local speaker connection may require different auth than cloud.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
from pathlib import Path

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_FILE = REPO_ROOT / ".nanit-session"
TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "aionanit"))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from aionanit.auth import TokenManager  # noqa: E402
from aionanit.rest import NanitRestClient  # noqa: E402

# Speaker proto — different schema from camera proto.
# Reverse-engineered from Nanit APK v4.0.6 by com6056/nanit-sound-light (MIT).
import sound_light_pb2 as sl  # noqa: E402

SPEAKER_WS_BASE = "wss://remote.nanit.com/speakers"
SPEAKER_LOCAL_PORT = 442


# ---------------------------------------------------------------------------
# Speaker WebSocket session
# ---------------------------------------------------------------------------

class SpeakerSession:
    """Minimal async WebSocket session for the Nanit Sound + Light device.

    Uses aiohttp for the WebSocket connection (same library as the rest of
    the project). The speaker uses standard TLS, Bearer auth, and a
    completely different protobuf schema from the camera.
    """

    def __init__(
        self,
        http_session: aiohttp.ClientSession,
        token_manager: TokenManager,
    ) -> None:
        self._http = http_session
        self._token_mgr = token_manager
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._recv_task: asyncio.Task | None = None
        self._state: dict = {}
        self._state_event: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect_cloud(self, speaker_uid: str) -> None:
        """Connect via Nanit cloud relay at remote.nanit.com."""
        token = await self._token_mgr.async_get_access_token()
        url = f"{SPEAKER_WS_BASE}/{speaker_uid}/user_connect/"
        print(f"  Connecting: {url}")
        self._ws = await self._http.ws_connect(
            url,
            headers={"Authorization": f"Bearer {token}"},
            ssl=ssl.create_default_context(),
            heartbeat=30.0,
            timeout=15.0,
        )
        self._recv_task = asyncio.get_running_loop().create_task(self._recv_loop())

    async def connect_local(self, ip: str, port: int = SPEAKER_LOCAL_PORT) -> None:
        """Connect directly to speaker on LAN."""
        token = await self._token_mgr.async_get_access_token()
        url = f"wss://{ip}:{port}"
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        for auth in (f"Bearer {token}", f"token {token}"):
            print(f"  Trying {url}  Authorization: {auth[:30]}...")
            try:
                self._ws = await self._http.ws_connect(
                    url,
                    headers={"Authorization": auth},
                    ssl=ssl_ctx,
                    heartbeat=30.0,
                    timeout=15.0,
                )
                print(f"  Connected locally with {auth.split()[0]} auth")
                self._recv_task = asyncio.get_running_loop().create_task(
                    self._recv_loop()
                )
                return
            except Exception as err:
                print(f"  Failed: {err}")

        raise RuntimeError(f"Could not connect to {url}")

    async def close(self) -> None:
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._handle_binary(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"  WS error: {self._ws.exception()}")
                    break
        except asyncio.CancelledError:
            return
        except Exception as err:
            print(f"  Recv loop error: {err}")

    def _handle_binary(self, data: bytes) -> None:
        """Parse incoming speaker proto frame and update state."""
        try:
            msg = sl.Message()
            msg.ParseFromString(data)
            if msg.HasField("response"):
                resp = msg.response
                print(f"\n  [PUSH] requestId={resp.requestId} status={resp.statusCode}")
                if resp.HasField("settings"):
                    self._apply_settings(resp.settings)
                    self._print_state()
        except Exception as err:
            print(f"  [PUSH] Parse error: {err}  raw={data.hex()}")

    def _apply_settings(self, settings: sl.Settings) -> None:
        if settings.HasField("isOn"):
            self._state["is_on"] = settings.isOn
        if settings.HasField("volume"):
            self._state["volume"] = round(settings.volume * 100)
        if settings.HasField("brightness"):
            self._state["brightness"] = round(settings.brightness * 100)
        if settings.HasField("temperature"):
            self._state["temperature"] = settings.temperature
        if settings.HasField("humidity"):
            self._state["humidity"] = settings.humidity
        if settings.HasField("sound"):
            sound = settings.sound
            if sound.HasField("noSound") and sound.noSound:
                self._state["sound"] = "No sound"
            elif sound.HasField("track"):
                self._state["sound"] = sound.track
        if settings.HasField("soundList"):
            self._state["available_sounds"] = list(settings.soundList.tracks)
        if settings.HasField("color"):
            color = settings.color
            self._state["color"] = {
                "noColor": color.noColor if color.HasField("noColor") else True,
                "hue": color.hue,
                "saturation": color.saturation,
            }
        self._state_event.set()

    def _print_state(self) -> None:
        print(f"  State: {json.dumps(self._state, indent=4)}")

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    async def _send(self, request: sl.Request) -> None:
        assert self._ws is not None
        msg = sl.Message()
        msg.request.CopyFrom(request)
        await self._ws.send_bytes(msg.SerializeToString())

    async def send_get_state(self) -> None:
        """Request full device state."""
        req = sl.Request()
        req.id = 1
        gs = sl.GetSettings()
        gs.all = True
        gs.temperature = True
        gs.humidity = True
        req.getSettings.CopyFrom(gs)
        await self._send(req)

    async def send_get_sounds(self) -> None:
        """Request list of available saved sounds."""
        req = sl.Request()
        req.id = 3
        gs = sl.GetSettings()
        gs.savedSounds = True
        req.getSettings.CopyFrom(gs)
        await self._send(req)

    async def send_control(
        self,
        *,
        is_on: bool | None = None,
        volume: float | None = None,   # 0.0–1.0
        sound: str | None = None,      # track name or "" for no sound
        no_sound: bool = False,
    ) -> None:
        """Send a settings control command."""
        req = sl.Request()
        req.id = 1
        settings = sl.Settings()

        if is_on is not None:
            settings.isOn = is_on
        if volume is not None:
            settings.volume = float(volume)
        if sound is not None or no_sound:
            sound_msg = sl.Sound()
            if no_sound or sound == "":
                sound_msg.noSound = True
                sound_msg.track = ""
            else:
                sound_msg.noSound = False
                sound_msg.track = str(sound)
            settings.sound.CopyFrom(sound_msg)

        req.settings.CopyFrom(settings)
        await self._send(req)

    async def wait_for_state(self, timeout: float = 5.0) -> bool:
        """Wait until at least one state update is received."""
        self._state_event.clear()
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_state(session: SpeakerSession) -> None:
    print("\nRequesting full device state...")
    await session.send_get_state()
    if await session.wait_for_state(timeout=5.0):
        print("\nFinal state:")
        session._print_state()
    else:
        print("  TIMED OUT — no response")


async def cmd_sounds(session: SpeakerSession) -> None:
    print("\nRequesting available sound tracks...")
    await session.send_get_sounds()
    if await session.wait_for_state(timeout=5.0):
        sounds = session._state.get("available_sounds", [])
        print(f"\nAvailable sounds ({len(sounds)}):")
        for s in sounds:
            print(f"  {s!r}")
    else:
        print("  TIMED OUT — no response")


async def cmd_stop(session: SpeakerSession) -> None:
    print("\nTurning off sound machine (isOn=False)...")
    await session.send_control(is_on=False)
    await asyncio.sleep(2)
    await session.send_get_state()
    await session.wait_for_state(timeout=5.0)
    print(f"\nState after stop: is_on={session._state.get('is_on')}")


async def cmd_play(session: SpeakerSession) -> None:
    print("\nTurning on sound machine (isOn=True)...")
    await session.send_control(is_on=True)
    await asyncio.sleep(2)
    await session.send_get_state()
    await session.wait_for_state(timeout=5.0)
    print(f"\nState after play: is_on={session._state.get('is_on')}")


async def cmd_set_sound(session: SpeakerSession, track_name: str) -> None:
    print(f"\nSetting sound to {track_name!r}...")
    await session.send_control(sound=track_name, is_on=True)
    await asyncio.sleep(2)
    await session.send_get_state()
    await session.wait_for_state(timeout=5.0)
    print(f"\nState after set-sound: {session._state.get('sound')!r}")


async def cmd_set_volume(session: SpeakerSession, volume_pct: int) -> None:
    vol_float = volume_pct / 100.0
    print(f"\nSetting volume to {volume_pct}% ({vol_float:.2f})...")
    await session.send_control(volume=vol_float)
    await asyncio.sleep(2)
    await session.send_get_state()
    await session.wait_for_state(timeout=5.0)
    print(f"\nState after set-volume: {session._state.get('volume')}%")


async def cmd_all(session: SpeakerSession) -> None:
    await cmd_state(session)
    await asyncio.sleep(1)
    await cmd_sounds(session)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Nanit Sound + Light machine."
    )
    parser.add_argument(
        "command",
        choices=["state", "sounds", "stop", "play", "set-sound", "set-volume", "all"],
        help="Command to run",
    )
    parser.add_argument(
        "--speaker-ip",
        help="Speaker local IP for LAN-only operation (skips cloud)",
    )
    parser.add_argument(
        "--track-name", default=None,
        help="Track name for set-sound (e.g. 'White Noise')",
    )
    parser.add_argument(
        "--volume", type=int, default=None,
        help="Volume 0-100 for set-volume",
    )
    # Also accept positional args after the command for convenience:
    #   just probe-audio set-sound "Brown Noise"
    #   just probe-audio set-volume 40
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # Resolve positional shortcuts
    if args.command == "set-sound" and args.track_name is None and args.extra:
        args.track_name = " ".join(args.extra)
    if args.command == "set-volume" and args.volume is None and args.extra:
        try:
            args.volume = int(args.extra[0])
        except (ValueError, IndexError):
            pass
    if args.volume is None:
        args.volume = 50

    if not SESSION_FILE.exists():
        print(f"No session found at {SESSION_FILE}.")
        print("Run: just login")
        return 1

    session_data = json.loads(SESSION_FILE.read_text())
    access_token = session_data["access_token"]
    refresh_token = session_data["refresh_token"]
    speaker_uid = session_data.get("speaker_uid")

    print(f"Speaker UID : {speaker_uid or '(none)'}")
    print(f"Command     : {args.command}")

    if not speaker_uid:
        print("No speaker_uid in session. Run: just login", file=sys.stderr)
        return 1

    async with aiohttp.ClientSession() as http_session:
        rest_client = NanitRestClient(http_session)
        token_mgr = TokenManager(
            rest=rest_client,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        def _save_tokens(new_access: str, new_refresh: str) -> None:
            session_data["access_token"] = new_access
            session_data["refresh_token"] = new_refresh
            SESSION_FILE.write_text(json.dumps(session_data, indent=2) + "\n")

        token_mgr.on_tokens_refreshed(_save_tokens)

        speaker = SpeakerSession(http_session, token_mgr)

        print("\nConnecting to speaker...")
        try:
            if args.speaker_ip:
                await speaker.connect_local(args.speaker_ip)
            else:
                await speaker.connect_cloud(speaker_uid)
        except Exception as err:
            print(f"Failed to connect: {err}")
            return 1

        print("Connected.")
        await asyncio.sleep(0.5)

        try:
            cmd = args.command
            if cmd == "state":
                await cmd_state(speaker)
            elif cmd == "sounds":
                await cmd_sounds(speaker)
            elif cmd == "stop":
                await cmd_stop(speaker)
            elif cmd == "play":
                await cmd_play(speaker)
            elif cmd == "set-sound":
                if not args.track_name:
                    print("--track-name required for set-sound", file=sys.stderr)
                    return 1
                await cmd_set_sound(speaker, args.track_name)
            elif cmd == "set-volume":
                await cmd_set_volume(speaker, args.volume)
            elif cmd == "all":
                await cmd_all(speaker)
        finally:
            await speaker.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
