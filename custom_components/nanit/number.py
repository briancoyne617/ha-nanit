"""Number platform for Nanit."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NanitConfigEntry
from .const import CONF_CAMERA_UID
from .coordinator import NanitPushCoordinator
from .entity import NanitEntity, NanitSpeakerEntity
from .speaker import NanitSpeakerCoordinator

from aionanit import NanitCamera


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NanitConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nanit number entities."""
    coordinator = entry.runtime_data.push_coordinator
    camera = entry.runtime_data.camera
    entities: list = [NanitVolume(coordinator, camera)]
    speaker_coordinator = entry.runtime_data.speaker_coordinator
    if speaker_coordinator is not None:
        entities.append(NanitSpeakerVolume(speaker_coordinator))
    async_add_entities(entities)


class NanitVolume(NanitEntity, NumberEntity):
    """Volume number entity."""

    _attr_translation_key = "volume"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: NanitPushCoordinator,
        camera: NanitCamera,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._camera = camera
        self._attr_unique_id = (
            f"{coordinator.config_entry.data.get(CONF_CAMERA_UID, coordinator.config_entry.entry_id)}"
            "_volume"
        )

    @property
    def native_value(self) -> float | None:
        """Return the current volume."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.settings.volume

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        await self._camera.async_set_settings(volume=int(value))
        self.async_write_ha_state()


class NanitSpeakerVolume(NanitSpeakerEntity, NumberEntity):
    """Volume slider for the Nanit Sound + Light."""

    _attr_translation_key = "speaker_volume"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:volume-high"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NanitSpeakerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"speaker_{coordinator.speaker_uid}_volume"

    @property
    def native_value(self) -> float | None:
        """Return current volume (0–100)."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.volume

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        await self.coordinator.async_send_control(volume=int(value))
        self.async_write_ha_state()
