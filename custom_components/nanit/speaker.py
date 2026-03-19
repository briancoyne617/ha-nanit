"""Nanit Sound + Light speaker client and coordinator.

The Sound + Light machine uses a completely different WebSocket endpoint
and protobuf schema from the camera:

  Endpoint: wss://remote.nanit.com/speakers/{speaker_uid}/user_connect/
  Auth:     Authorization: Bearer {access_token}
  Proto:    sound_light_pb2 (see that file for full schema docs)

NanitSpeakerClient  — raw WebSocket I/O; connects, sends commands, parses frames.
NanitSpeakerCoordinator — DataUpdateCoordinator wrapping the client; handles
                           reconnection and pushes SpeakerState to HA entities.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from dataclasses import dataclass, field, replace
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from . import sound_light_pb2 as sl

_LOGGER = logging.getLogger(__name__)

SPEAKER_WS_BASE = "wss://remote.nanit.com/speakers"
_RECONNECT_DELAY_INITIAL: float = 5.0
_RECONNECT_DELAY_MAX: float = 60.0


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpeakerState:
    """Immutable snapshot of Nanit Sound + Light state.

    Fields mirror the proto Settings message. None means "not yet received".
    volume is stored as 0–100 int (the proto sends 0.0–1.0 float).
    brightness is 0–100 int (proto sends 0.0–1.0 float).
    available_sounds is populated once via GetSettings(savedSounds=True).
    """

    is_on: bool | None = None
    volume: int | None = None               # 0–100
    sound: str | None = None               # current track name
    available_sounds: tuple[str, ...] = ()  # all playable tracks
    brightness: int | None = None          # 0–100 (light brightness)
    temperature: float | None = None       # °C, from speaker hardware
    humidity: float | None = None          # %, from speaker hardware


def _merge(current: SpeakerState, partial: SpeakerState) -> SpeakerState:
    """Return a new SpeakerState with non-None fields from partial overlaid on current."""
    return replace(
        current,
        **{
            k: v
            for k, v in {
                "is_on": partial.is_on,
                "volume": partial.volume,
                "sound": partial.sound,
                "available_sounds": partial.available_sounds or None,
                "brightness": partial.brightness,
                "temperature": partial.temperature,
                "humidity": partial.humidity,
            }.items()
            if v is not None
        },
    )


def _parse_settings(settings: sl.Settings) -> SpeakerState:  # type: ignore[name-defined]
    """Convert a proto Settings message into a partial SpeakerState.

    Only fields actually present in the proto message are set; the rest stay
    None so callers can merge with _merge() to preserve existing values.
    """
    is_on = settings.isOn if settings.HasField("isOn") else None
    volume = round(settings.volume * 100) if settings.HasField("volume") else None
    brightness = round(settings.brightness * 100) if settings.HasField("brightness") else None
    temperature = settings.temperature if settings.HasField("temperature") else None
    humidity = settings.humidity if settings.HasField("humidity") else None

    sound: str | None = None
    if settings.HasField("sound"):
        s = settings.sound
        if s.HasField("noSound") and s.noSound:
            sound = ""
        elif s.HasField("track"):
            sound = s.track

    available_sounds: tuple[str, ...] = ()
    if settings.HasField("soundList") and settings.soundList.tracks:
        available_sounds = tuple(settings.soundList.tracks)

    return SpeakerState(
        is_on=is_on,
        volume=volume,
        sound=sound,
        available_sounds=available_sounds,
        brightness=brightness,
        temperature=temperature,
        humidity=humidity,
    )


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------

class NanitSpeakerClient:
    """Low-level WebSocket client for the Nanit Sound + Light device.

    Connects to wss://remote.nanit.com/speakers/{uid}/user_connect/ using
    the shared access token. Calls on_state_update with a partial SpeakerState
    each time a settings response arrives.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token_manager: Any,
        on_state_update: Any,
    ) -> None:
        self._session = session
        self._token_mgr = token_manager
        self._on_state_update = on_state_update
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def connect_and_run(self, speaker_uid: str) -> None:
        """Connect to the speaker and run the receive loop until disconnected.

        This method blocks until the WebSocket closes. The coordinator calls
        it in a managed loop to handle reconnection automatically.
        """
        token = await self._token_mgr.async_get_access_token()
        url = f"{SPEAKER_WS_BASE}/{speaker_uid}/user_connect/"

        async with self._session.ws_connect(
            url,
            headers={"Authorization": f"Bearer {token}"},
            ssl=ssl.create_default_context(),
            timeout=aiohttp.ClientWSTimeout(ws_close=15.0),
            heartbeat=30.0,
        ) as ws:
            self._ws = ws
            # Request full state immediately on connect.
            await self._request_all(ws)
            # Block until the server closes or errors.
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._handle_frame(msg.data)
                elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
            self._ws = None

    def _handle_frame(self, data: bytes) -> None:
        """Parse one incoming binary frame and call on_state_update if it contains settings."""
        try:
            msg = sl.Message()
            msg.ParseFromString(data)
            if msg.HasField("response") and msg.response.HasField("settings"):
                partial = _parse_settings(msg.response.settings)
                self._on_state_update(partial)
        except Exception as err:
            _LOGGER.debug("Speaker frame parse error: %s  raw=%s", err, data.hex())

    async def send_control(
        self,
        *,
        is_on: bool | None = None,
        volume: int | None = None,   # 0–100
        sound: str | None = None,
    ) -> None:
        """Send a settings control command.

        After sending, requests a full state refresh so entities update promptly.
        """
        if self._ws is None or self._ws.closed:
            raise RuntimeError("Speaker WebSocket not connected")

        req = sl.Request()
        req.id = 1
        settings = sl.Settings()

        if is_on is not None:
            settings.isOn = is_on
        if volume is not None:
            settings.volume = volume / 100.0
        if sound is not None:
            sound_msg = sl.Sound()
            if sound == "":
                sound_msg.noSound = True
                sound_msg.track = ""
            else:
                sound_msg.noSound = False
                sound_msg.track = sound
            settings.sound.CopyFrom(sound_msg)

        req.settings.CopyFrom(settings)
        await self._send_request(self._ws, req)

        # Give the device a moment to process, then pull fresh state.
        await asyncio.sleep(0.5)
        await self._request_all(self._ws)

    @staticmethod
    async def _request_all(ws: aiohttp.ClientWebSocketResponse) -> None:
        """Request full device state: power/volume/sound/sensors/sound list."""
        req = sl.Request()
        req.id = 1
        gs = sl.GetSettings()
        gs.all = True
        gs.temperature = True
        gs.humidity = True
        gs.savedSounds = True
        req.getSettings.CopyFrom(gs)
        msg = sl.Message()
        msg.request.CopyFrom(req)
        await ws.send_bytes(msg.SerializeToString())

    @staticmethod
    async def _send_request(
        ws: aiohttp.ClientWebSocketResponse, req: sl.Request  # type: ignore[name-defined]
    ) -> None:
        msg = sl.Message()
        msg.request.CopyFrom(req)
        await ws.send_bytes(msg.SerializeToString())


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class NanitSpeakerCoordinator(DataUpdateCoordinator[SpeakerState]):
    """Push-based coordinator for the Nanit Sound + Light device.

    Maintains a persistent WebSocket connection and calls
    async_set_updated_data() on every state change from the speaker.
    Reconnects automatically with exponential back-off when the connection
    drops (network blip, token expiry, etc.).

    Entities call async_send_control() to send commands.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        token_manager: Any,
        speaker_uid: str,
        baby_name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_speaker_{speaker_uid}",
            # No update_interval — purely push-based.
        )
        self.speaker_uid = speaker_uid
        self.baby_name = baby_name
        self.connected: bool = False
        self._state = SpeakerState()
        self._client = NanitSpeakerClient(session, token_manager, self._on_state_update)
        self._manage_task: asyncio.Task | None = None
        self._stopped = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Start the managed connection loop and wait for the first connect."""
        first_connect: asyncio.Future[None] = self.hass.loop.create_future()
        self._manage_task = self.hass.loop.create_task(
            self._manage_connection(first_connect)
        )
        try:
            await asyncio.wait_for(asyncio.shield(first_connect), timeout=15.0)
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Speaker %s did not connect within 15 s — will keep retrying in background",
                self.speaker_uid,
            )

    async def async_shutdown(self) -> None:
        self._stopped = True
        if self._manage_task and not self._manage_task.done():
            self._manage_task.cancel()
            try:
                await self._manage_task
            except asyncio.CancelledError:
                pass
        await super().async_shutdown()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_send_control(self, **kwargs: Any) -> None:
        """Forward a control command to the client (is_on, volume, sound)."""
        await self._client.send_control(**kwargs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _manage_connection(
        self, first_connect: asyncio.Future[None]
    ) -> None:
        """Connection management loop with exponential back-off reconnect."""
        delay = _RECONNECT_DELAY_INITIAL
        while not self._stopped:
            try:
                _LOGGER.debug("Speaker %s connecting", self.speaker_uid)
                self.connected = True
                if not first_connect.done():
                    first_connect.set_result(None)
                self.async_set_updated_data(self._state)
                await self._client.connect_and_run(self.speaker_uid)
                # connect_and_run returned — connection closed gracefully.
                delay = _RECONNECT_DELAY_INITIAL
            except asyncio.CancelledError:
                return
            except Exception as err:
                _LOGGER.warning(
                    "Speaker %s connection error: %s", self.speaker_uid, err
                )
                if not first_connect.done():
                    first_connect.set_exception(err)

            self.connected = False
            self.async_set_updated_data(self._state)

            if not self._stopped:
                _LOGGER.debug(
                    "Speaker %s reconnecting in %.0fs", self.speaker_uid, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, _RECONNECT_DELAY_MAX)

    def _on_state_update(self, partial: SpeakerState) -> None:
        """Merge a partial state update and notify HA entities."""
        self._state = _merge(self._state, partial)
        self.async_set_updated_data(self._state)
