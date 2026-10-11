"""No Longer Evil Thermostat integration."""

from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NoLongerEvilApi
from .const import PLATFORMS
from .coordinator import ThermostatCoordinator


async def async_setup_entry(hass, entry):
    """Set up a UI configured account."""
    coordinator = ThermostatCoordinator(
        hass,
        entry,
        NoLongerEvilApi(async_get_clientsession(hass), entry.data[CONF_API_KEY]),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    """Unload platforms and their coordinator listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
