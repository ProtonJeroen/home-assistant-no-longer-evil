"""Climate controls supported by the hosted API."""

import math

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError

from .api import ApiError, AuthenticationError
from .entity import ThermostatEntity, discover_entities

READ_MODES = {
    "heat": HVACMode.HEAT,
    "cool": HVACMode.COOL,
    "range": HVACMode.HEAT_COOL,
    "off": HVACMode.OFF,
}
WRITE_MODES = {
    HVACMode.HEAT: "heat",
    HVACMode.COOL: "cool",
    HVACMode.HEAT_COOL: "heat-cool",
    HVACMode.OFF: "off",
}
HEAT_FIELDS = (
    "hvac_heater_state",
    "hvac_heat_x2_state",
    "hvac_heat_x3_state",
    "hvac_emer_heat_state",
    "hvac_aux_heater_state",
    "hvac_alt_heat_state",
)
COOL_FIELDS = ("hvac_ac_state", "hvac_cool_x2_state", "hvac_cool_x3_state")


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entry.async_on_unload(
        discover_entities(
            coordinator,
            async_add_entities,
            lambda serial, data: [
                ("climate", ThermostatClimate(coordinator, serial, "climate"))
            ],
        )
    )


class ThermostatClimate(ThermostatEntity, ClimateEntity):
    """Report Celsius state and translate hosted API command formats."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 4.5
    _attr_max_temp = 32
    _attr_target_temperature_step = 0.5
    _enable_turn_on_off_backwards_compatibility = False

    @property
    def shared(self):
        return self.data.get("shared", {})

    @property
    def hvac_modes(self):
        if self.heating_only:
            return [HVACMode.OFF, HVACMode.HEAT]
        modes = [HVACMode.OFF]
        if self.shared.get("can_heat") is True:
            modes.append(HVACMode.HEAT)
        if self.shared.get("can_cool") is True:
            modes.append(HVACMode.COOL)
        if HVACMode.HEAT in modes and HVACMode.COOL in modes:
            modes.append(HVACMode.HEAT_COOL)
        return modes

    @property
    def heating_only(self):
        return self.serial in self.coordinator.config_entry.options.get(
            "heating_only", []
        )

    @property
    def hvac_mode(self):
        mode = READ_MODES.get(
            str(self.shared.get("target_temperature_type", "")).lower()
        )
        if self.heating_only and mode not in (HVACMode.OFF, HVACMode.HEAT):
            return None
        return mode

    @property
    def supported_features(self):
        if self.hvac_mode == HVACMode.HEAT_COOL:
            return ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        if self.hvac_mode in (HVACMode.HEAT, HVACMode.COOL):
            return ClimateEntityFeature.TARGET_TEMPERATURE
        return ClimateEntityFeature(0)

    @property
    def current_temperature(self):
        return self.shared.get("current_temperature")

    @property
    def target_temperature(self):
        if self.hvac_mode in (HVACMode.HEAT, HVACMode.COOL):
            return self.shared.get("target_temperature")
        return None

    @property
    def target_temperature_low(self):
        return (
            self.shared.get("target_temperature_low")
            if self.hvac_mode == HVACMode.HEAT_COOL
            else None
        )

    @property
    def target_temperature_high(self):
        return (
            self.shared.get("target_temperature_high")
            if self.hvac_mode == HVACMode.HEAT_COOL
            else None
        )

    @property
    def hvac_action(self):
        if any(self.shared.get(key) is True for key in HEAT_FIELDS):
            return HVACAction.HEATING
        if any(self.shared.get(key) is True for key in COOL_FIELDS):
            return HVACAction.COOLING
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        fields = HEAT_FIELDS + COOL_FIELDS
        if not any(isinstance(self.shared.get(key), bool) for key in fields):
            return None
        return HVACAction.IDLE

    async def _command(self, endpoint, body):
        if not self.available:
            raise HomeAssistantError("Thermostat is unavailable")
        try:
            await self.coordinator.api.command(self.data["info"]["id"], endpoint, body)
        except AuthenticationError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from None
        except ApiError as err:
            raise HomeAssistantError(str(err)) from None
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in self.hvac_modes:
            raise HomeAssistantError("HVAC mode is not supported by this thermostat")
        await self._command("mode", {"mode": WRITE_MODES[hvac_mode]})

    def _temperature(self, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not 4.5 <= value <= 32
        ):
            raise HomeAssistantError("Temperature must be between 4.5 and 32 Celsius")
        return value

    async def async_set_temperature(self, **kwargs):
        mode = kwargs.get("hvac_mode", self.hvac_mode)
        if mode not in self.hvac_modes:
            raise HomeAssistantError("HVAC mode is not supported by this thermostat")
        if mode == HVACMode.HEAT_COOL:
            low = self._temperature(kwargs.get("target_temp_low"))
            high = self._temperature(kwargs.get("target_temp_high"))
            if low >= high:
                raise HomeAssistantError(
                    "Low temperature must be below high temperature"
                )
            endpoint, body = (
                "temperature/range",
                {"low": low, "high": high, "scale": "C"},
            )
        elif mode in (HVACMode.HEAT, HVACMode.COOL):
            endpoint, body = (
                "temperature",
                {
                    "value": self._temperature(kwargs.get(ATTR_TEMPERATURE)),
                    "mode": WRITE_MODES[mode],
                    "scale": "C",
                },
            )
        else:
            raise HomeAssistantError(
                "Select heat, cool or heat/cool before setting temperature"
            )
        if mode != self.hvac_mode:
            await self.async_set_hvac_mode(mode)
        await self._command(endpoint, body)
