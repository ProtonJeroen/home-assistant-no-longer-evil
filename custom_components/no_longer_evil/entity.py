"""Common device identity and availability."""

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class ThermostatEntity(CoordinatorEntity):
    """An entity associated with a thermostat serial."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, serial, key):
        super().__init__(coordinator)
        self.serial = serial
        self._info = coordinator.data[serial]["info"]
        self._attr_unique_id = f"{serial}_{key}"

    @property
    def data(self):
        return self.coordinator.data.get(self.serial, {})

    @property
    def available(self):
        return super().available and self.data.get("available", False)

    @property
    def device_info(self):
        info = self.data.get("info", self._info)
        return DeviceInfo(
            identifiers={(DOMAIN, self.serial)},
            name=info.get("name") or self.serial,
            manufacturer="Nest",
            serial_number=self.serial,
        )


def discover_entities(coordinator, async_add_entities, factory):
    """Add newly discovered thermostats and optional sensors during polling."""
    known = set()

    def discover():
        entities = []
        for serial, data in coordinator.data.items():
            if data.get("available"):
                for key, entity in factory(serial, data):
                    if (serial, key) not in known:
                        known.add((serial, key))
                        entities.append(entity)
        if entities:
            async_add_entities(entities)

    discover()
    return coordinator.async_add_listener(discover)
