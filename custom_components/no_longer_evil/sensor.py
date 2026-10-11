"""Optional documented diagnostics, added only when reported."""

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)

from .entity import ThermostatEntity, discover_entities

# battery_level has no documented unit; do not claim a percentage or voltage.
SENSORS = {
    "current_humidity": (SensorDeviceClass.HUMIDITY, PERCENTAGE),
    "backplate_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "battery_level": (None, None),
    "time_to_target": (SensorDeviceClass.DURATION, UnitOfTime.SECONDS),
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data

    def factory(serial, data):
        return [
            (key, ThermostatSensor(coordinator, serial, key))
            for key in SENSORS
            if key in data.get("device", {})
        ]

    entry.async_on_unload(discover_entities(coordinator, async_add_entities, factory))


class ThermostatSensor(ThermostatEntity, SensorEntity):
    """An optional diagnostic measurement."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, serial, key):
        super().__init__(coordinator, serial, key)
        self.key = key
        self._attr_translation_key = key
        self._attr_device_class, self._attr_native_unit_of_measurement = SENSORS[key]

    @property
    def native_value(self):
        return self.data.get("device", {}).get(self.key)
