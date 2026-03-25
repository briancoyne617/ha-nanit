"""The Nanit integration."""

from __future__ import annotations

import sys
from pathlib import Path  # used for _DEPS vendor injection and clips_dir

# Vendored aionanit — bundled in _deps/ to avoid PyPI dependency conflicts.
# Must run before any aionanit imports, and before config_flow.py is loaded.
_DEPS = str(Path(__file__).parent / "_deps")
if _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aionanit import NanitAuthError, NanitCamera, NanitConnectionError

from .const import (
    CONF_BABY_NAME,
    CONF_BABY_UID,
    CONF_CAMERA_IP,
    CONF_CAMERA_UID,
    CONF_REFRESH_TOKEN,
    CONF_SPEAKER_UID,
    DOMAIN,
    LOGGER,
    PLATFORMS,
)
from .buffer import NanitBufferManager
from .coordinator import NanitCloudCoordinator, NanitPushCoordinator
from .hub import NanitHub
from .speaker import NanitSpeakerCoordinator


@dataclass
class NanitData:
    """Runtime data for a Nanit config entry."""

    hub: NanitHub
    camera: NanitCamera
    push_coordinator: NanitPushCoordinator
    cloud_coordinator: NanitCloudCoordinator | None
    speaker_coordinator: NanitSpeakerCoordinator | None
    buffer_manager: NanitBufferManager | None


type NanitConfigEntry = ConfigEntry[NanitData]


async def async_setup_entry(hass: HomeAssistant, entry: NanitConfigEntry) -> bool:
    """Set up Nanit from a config entry."""
    session = async_get_clientsession(hass)
    access_token = entry.data[CONF_ACCESS_TOKEN]
    refresh_token = entry.data[CONF_REFRESH_TOKEN]

    # Create the hub (owns NanitClient, token lifecycle)
    hub = NanitHub(session, access_token, refresh_token)

    # Register a callback to persist refreshed tokens back to the config entry
    @callback
    def _on_tokens_refreshed(new_access: str, new_refresh: str) -> None:
        """Persist refreshed tokens to the config entry."""
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ACCESS_TOKEN: new_access, CONF_REFRESH_TOKEN: new_refresh},
        )

    hub.setup_token_callback(_on_tokens_refreshed)

    # Get camera from hub
    camera_uid = entry.data[CONF_CAMERA_UID]
    baby_uid = entry.data[CONF_BABY_UID]
    camera_ip = entry.data.get(CONF_CAMERA_IP)

    try:
        camera = hub.get_camera(
            camera_uid,
            baby_uid,
            prefer_local=camera_ip is not None,
            local_ip=camera_ip,
        )
    except NanitAuthError as err:
        raise ConfigEntryAuthFailed(err) from err

    # Create the push coordinator and start the camera WebSocket
    push_coordinator = NanitPushCoordinator(hass, camera)
    try:
        await push_coordinator.async_setup()
    except NanitAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except NanitConnectionError as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to Nanit camera {camera_uid}: {err}"
        ) from err

    # Cloud coordinator (optional — polls for motion/sound events)
    cloud_coordinator: NanitCloudCoordinator | None = None
    try:
        cloud_coordinator = NanitCloudCoordinator(hass, hub, baby_uid)
        await cloud_coordinator.async_config_entry_first_refresh()
    except NanitAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except NanitConnectionError:
        # Cloud events are optional — log and continue
        LOGGER.warning("Cloud event coordinator failed to start; cloud sensors disabled")
        cloud_coordinator = None

    # Speaker coordinator (optional — only if a Sound + Light is paired)
    # For existing entries without speaker_uid, try fetching it once from the API.
    speaker_coordinator: NanitSpeakerCoordinator | None = None
    speaker_uid = entry.data.get(CONF_SPEAKER_UID)
    if not speaker_uid:
        try:
            babies = await hub.async_get_babies()
            if babies and babies[0].speaker_uid:
                speaker_uid = babies[0].speaker_uid
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_SPEAKER_UID: speaker_uid},
                )
        except Exception:
            LOGGER.debug("Could not fetch speaker UID from API")
    if speaker_uid:
        baby_name = entry.data.get(CONF_BABY_NAME, "Nanit")
        speaker_coordinator = NanitSpeakerCoordinator(
            hass,
            session,
            hub.token_manager,
            speaker_uid,
            baby_name,
        )
        await speaker_coordinator.async_setup()

    # Rolling video buffer (saves clips on sound alert)
    baby_name = entry.data.get(CONF_BABY_NAME, "Nanit")
    clips_dir = Path(hass.config.path("nanit_clips"))
    buffer_manager = NanitBufferManager(
        hass=hass,
        camera=camera,
        token_manager=hub.token_manager,
        push_coordinator=push_coordinator,
        baby_name=baby_name,
        clips_dir=clips_dir,
    )
    try:
        await buffer_manager.async_setup()
    except Exception:
        LOGGER.warning("Rolling video buffer failed to start; clip saving disabled")
        buffer_manager = None

    entry.runtime_data = NanitData(
        hub=hub,
        camera=camera,
        push_coordinator=push_coordinator,
        cloud_coordinator=cloud_coordinator,
        speaker_coordinator=speaker_coordinator,
        buffer_manager=buffer_manager,
    )

    # Register nanit.save_clip service (idempotent — only once per domain)
    if not hass.services.has_service(DOMAIN, "save_clip"):
        async def _handle_save_clip(call: ServiceCall) -> None:
            for cfg_entry in hass.config_entries.async_entries(DOMAIN):
                if (
                    hasattr(cfg_entry, "runtime_data")
                    and cfg_entry.runtime_data
                    and cfg_entry.runtime_data.buffer_manager
                ):
                    await cfg_entry.runtime_data.buffer_manager.async_save_clip(
                        label=call.data.get("label", "manual")
                    )

        hass.services.async_register(DOMAIN, "save_clip", _handle_save_clip)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NanitConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.runtime_data.buffer_manager is not None:
            await entry.runtime_data.buffer_manager.async_shutdown()
        if entry.runtime_data.speaker_coordinator is not None:
            await entry.runtime_data.speaker_coordinator.async_shutdown()
        await entry.runtime_data.hub.async_close()
    return unload_ok
