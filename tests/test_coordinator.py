"""Polling isolation and lifecycle tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.no_longer_evil.api import ApiError, AuthenticationError
from custom_components.no_longer_evil.coordinator import ThermostatCoordinator


async def test_polling_isolates_device_failure_and_refreshes_inventory():
    api = MagicMock()
    api.devices = AsyncMock(
        return_value=[{"id": "a", "serial": "a"}, {"id": "b", "serial": "b"}]
    )
    api.status = AsyncMock(
        side_effect=[ApiError("offline"), {"shared": {"can_heat": True}, "device": {}}]
    )
    coordinator = ThermostatCoordinator(MagicMock(), MagicMock(), api)
    data = await coordinator._async_update_data()
    assert data["a"]["available"] is False
    assert data["b"]["available"] is True
    api.devices.return_value = []
    assert await coordinator._async_update_data() == {}


@pytest.mark.parametrize(
    "error,expected",
    [
        (AuthenticationError("rejected"), ConfigEntryAuthFailed),
        (ApiError("offline"), UpdateFailed),
    ],
)
async def test_inventory_errors(error, expected):
    api = MagicMock()
    api.devices = AsyncMock(side_effect=error)
    coordinator = ThermostatCoordinator(MagicMock(), MagicMock(), api)
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_setup_and_unload():
    from custom_components.no_longer_evil import async_setup_entry, async_unload_entry

    hass = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = MagicMock()
    entry.data = {"api_key": "test-only-placeholder"}
    with (
        patch("custom_components.no_longer_evil.async_get_clientsession"),
        patch("custom_components.no_longer_evil.ThermostatCoordinator") as cls,
    ):
        cls.return_value.async_config_entry_first_refresh = AsyncMock()
        assert await async_setup_entry(hass, entry)
        assert entry.runtime_data is cls.return_value
        cls.return_value.async_config_entry_first_refresh.assert_awaited_once()
        assert await async_unload_entry(hass, entry)
        hass.config_entries.async_unload_platforms.assert_awaited_once()
