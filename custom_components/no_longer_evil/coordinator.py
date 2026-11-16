"""Polling and automatic discovery."""

from datetime import timedelta
import logging
import math
import time

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError, AuthenticationError
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)

# A partial cloud response may omit the setpoint temporarily. Do not present
# the cached target as current indefinitely.
TARGET_GRACE_SECONDS = 300
TARGET_FIELDS = ("target_temperature", "target_temperature_low", "target_temperature_high")


def _valid_target(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)



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
        self._last_valid_targets = {}
        self._partial_target_warnings = set()

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
                    previous = (self.data or {}).get(device["serial"], {})
                    result[device["serial"]] = {
                        **previous,
                        "info": device,
                        # Keep the last valid snapshot through a transient
                        # cloud read error; do not turn the card unknown.
                        "available": previous.get("available", False),
                    }
                else:
                    serial = device["serial"]
                    shared = dict(values.get("shared", {}))
                    previous_shared = (self.data or {}).get(serial, {}).get("shared", {})
                    now = time.monotonic()
                    # Cache only fields that were actually returned with valid
                    # numeric values. Never substitute a previous setpoint after
                    # the bounded grace window.
                    for field in TARGET_FIELDS:
                        key = (serial, field)
                        current = shared.get(field)
                        if _valid_target(current):
                            self._last_valid_targets[key] = (current, now)
                            self._partial_target_warnings.discard(key)
                            continue
                        cached = self._last_valid_targets.get(key)
                        if cached is None and _valid_target(previous_shared.get(field)):
                            # Legacy snapshot from before this coordinator started:
                            # do not infer its age or treat it as fresh.
                            LOGGER.debug("Thermostat %s has an undated cached %s", serial[-4:], field)
                        if cached is not None and now - cached[1] <= TARGET_GRACE_SECONDS:
                            shared[field] = cached[0]
                            if key not in self._partial_target_warnings:
                                LOGGER.warning(
                                    "Thermostat %s API status omitted %s; using recent cached value for up to %s seconds",
                                    serial[-4:], field, TARGET_GRACE_SECONDS,
                                )
                                self._partial_target_warnings.add(key)
                        else:
                            shared.pop(field, None)
                            if key in self._last_valid_targets and key not in self._partial_target_warnings:
                                LOGGER.warning("Thermostat %s API status omitted %s; cached value expired", serial[-4:], field)
                                self._partial_target_warnings.add(key)
                    result[serial] = {
                        "info": device,
                        "available": True,
                        **values,
                        "shared": shared,
                    }
            return result
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from None
        except ApiError as err:
            if self.data:
                LOGGER.debug("Transient inventory poll failed; keeping cached state: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from None
