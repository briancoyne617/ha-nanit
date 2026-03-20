"""Media player platform for Nanit — Sound + Light combined entity."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NanitConfigEntry
from .entity import NanitSpeakerEntity
from .speaker import NanitSpeakerCoordinator

_SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NanitConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Nanit Sound + Light media player."""
    speaker_coordinator = entry.runtime_data.speaker_coordinator
    if speaker_coordinator is not None:
        async_add_entities([NanitSpeakerMediaPlayer(speaker_coordinator)])


class NanitSpeakerMediaPlayer(NanitSpeakerEntity, MediaPlayerEntity):
    """Combined media player entity for the Nanit Sound + Light.

    Exposes power, volume, and sound track selection as a single media player,
    matching the experience of Google Home / Alexa speaker entities.
    """

    _attr_translation_key = "speaker_media_player"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = _SUPPORTED_FEATURES

    def __init__(self, coordinator: NanitSpeakerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"speaker_{coordinator.speaker_uid}_media_player"

    @property
    def state(self) -> MediaPlayerState | None:
        """Return playing when on, idle when off, None when unknown."""
        if self.coordinator.data is None or self.coordinator.data.is_on is None:
            return None
        return MediaPlayerState.PLAYING if self.coordinator.data.is_on else MediaPlayerState.IDLE

    @property
    def volume_level(self) -> float | None:
        """Return volume as 0.0–1.0."""
        if self.coordinator.data is None or self.coordinator.data.volume is None:
            return None
        return self.coordinator.data.volume / 100.0

    @property
    def source(self) -> str | None:
        """Return the currently playing sound track."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.sound

    @property
    def source_list(self) -> list[str]:
        """Return all available sound tracks."""
        if self.coordinator.data and self.coordinator.data.available_sounds:
            return list(self.coordinator.data.available_sounds)
        return []

    async def async_media_play(self) -> None:
        """Turn the speaker on."""
        await self.coordinator.async_send_control(is_on=True)

    async def async_media_stop(self) -> None:
        """Turn the speaker off."""
        await self.coordinator.async_send_control(is_on=False)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume (HA passes 0.0–1.0)."""
        await self.coordinator.async_send_control(volume=round(volume * 100))

    async def async_volume_up(self) -> None:
        """Step volume up by 5."""
        if self.coordinator.data and self.coordinator.data.volume is not None:
            new_vol = min(100, self.coordinator.data.volume + 5)
            await self.coordinator.async_send_control(volume=new_vol)

    async def async_volume_down(self) -> None:
        """Step volume down by 5."""
        if self.coordinator.data and self.coordinator.data.volume is not None:
            new_vol = max(0, self.coordinator.data.volume - 5)
            await self.coordinator.async_send_control(volume=new_vol)

    async def async_select_source(self, source: str) -> None:
        """Select a sound track and turn the speaker on."""
        await self.coordinator.async_send_control(sound=source, is_on=True)
