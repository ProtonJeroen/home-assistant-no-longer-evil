"""Polling and automatic discovery."""

from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthenticationError
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


class ThermostatCoordinator(DataUpdateCoordinator):
    """Refresh inventory and keep individual device failures isolated."""

    def __init__(self, hass, entry, api):
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=60),
        )
        self.api = api

    async def _async_update_data(self):
        try:
            devices = await self.api.devices()
            # Leave request capacity for user commands even with large accounts.
            self.update_interval = timedelta(seconds=max(60, (len(devices) + 1) * 6))
            result = {}
            for device in devices:
                try:
                    values = await self.api.status(device["id"], device["serial"])
                except AuthenticationError:
                    raise
                except ApiError:
                    result[device["serial"]] = {"info": device, "available": False}
                else:
                    result[device["serial"]] = {
                        "info": device,
                        "available": True,
                        **values,
                    }
            return result
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from None
        except ApiError as err:
            raise UpdateFailed(str(err)) from None
