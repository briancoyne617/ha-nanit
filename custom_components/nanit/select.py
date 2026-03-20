"""Select platform for Nanit — Sound + Light track selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NanitConfigEntry
from .entity import NanitSpeakerEntity
from .speaker import NanitSpeakerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NanitConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nanit select entities."""
    speaker_coordinator = entry.runtime_data.speaker_coordinator
    if speaker_coordinator is not None:
        async_add_entities([NanitSpeakerSoundSelect(speaker_coordinator)])


class NanitSpeakerSoundSelect(NanitSpeakerEntity, SelectEntity):
    """Select entity for Sound + Light track selection.

    Choosing a track also turns the speaker on (isOn=True) so the selection
    takes effect immediately, matching the behaviour of the Nanit app.
    """

    _attr_translation_key = "speaker_sound"
    _attr_icon = "mdi:music-note"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NanitSpeakerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"speaker_{coordinator.speaker_uid}_sound"

    @property
    def options(self) -> list[str]:
        """Return the list of available sound tracks."""
        if self.coordinator.data and self.coordinator.data.available_sounds:
            return list(self.coordinator.data.available_sounds)
        return []

    @property
    def current_option(self) -> str | None:
        """Return the currently selected track."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.sound or None

    async def async_select_option(self, option: str) -> None:
        """Select a track and ensure the speaker is on."""
        await self.coordinator.async_send_control(sound=option, is_on=True)
        self.async_write_ha_state()
