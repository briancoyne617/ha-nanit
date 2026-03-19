"""Base entities for Nanit."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BABY_NAME, CONF_CAMERA_UID, DOMAIN
from .coordinator import NanitPushCoordinator
from .speaker import NanitSpeakerCoordinator


class NanitEntity(CoordinatorEntity[NanitPushCoordinator]):
    """Base entity for the Nanit camera — backed by the push coordinator."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.data[CONF_CAMERA_UID])},
            name=self.coordinator.config_entry.data[CONF_BABY_NAME],
            manufacturer="Nanit",
        )

    @property
    def available(self) -> bool:
        """Return True when the coordinator has data and camera is connected."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.connected
        )


class NanitSpeakerEntity(CoordinatorEntity[NanitSpeakerCoordinator]):
    """Base entity for the Nanit Sound + Light — backed by the speaker coordinator.

    The Sound + Light is a separate device from the camera with its own
    WebSocket connection (wss://remote.nanit.com/speakers/...) and its own
    device registry entry.
    """

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Sound + Light device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"speaker_{self.coordinator.speaker_uid}")},
            name=f"{self.coordinator.baby_name} Sound + Light",
            manufacturer="Nanit",
            model="Sound + Light",
        )

    @property
    def available(self) -> bool:
        """Return True when connected and data has been received."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.connected
        )
