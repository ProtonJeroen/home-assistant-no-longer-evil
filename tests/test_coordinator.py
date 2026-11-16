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

async def test_transient_device_error_preserves_last_good_state():
    api = MagicMock()
    api.devices = AsyncMock(return_value=[{"id": "a", "serial": "a"}])
    api.status = AsyncMock(side_effect=ApiError("temporary"))
    coordinator = ThermostatCoordinator(MagicMock(), MagicMock(), api)
    coordinator.async_set_updated_data({
        "a": {"info": {"id": "a", "serial": "a"}, "available": True,
              "shared": {"target_temperature": 20}, "device": {}}
    })
    data = await coordinator._async_update_data()
    assert data["a"]["available"] is True
    assert data["a"]["shared"]["target_temperature"] == 20


async def test_transient_inventory_failure_retains_previous_state():
    api = MagicMock()
    api.devices = AsyncMock(side_effect=ApiError("temporary"))
    coordinator = ThermostatCoordinator(MagicMock(), MagicMock(), api)
    previous = {
        "a": {"info": {"id": "a", "serial": "a"}, "available": True,
              "shared": {"target_temperature": 21}, "device": {}}
    }
    coordinator.async_set_updated_data(previous)
    assert await coordinator._async_update_data() == previous


async def test_partial_status_preserves_recent_setpoint_then_expires(caplog):
    from custom_components.no_longer_evil.coordinator import TARGET_GRACE_SECONDS

    api = MagicMock()
    api.devices = AsyncMock(return_value=[{"id": "a", "serial": "a"}])
    api.status = AsyncMock(side_effect=[
        {"shared": {"target_temperature": 20.5, "current_temperature": 20}, "device": {}},
        {"shared": {"current_temperature": 20.7}, "device": {}},
        {"shared": {"current_temperature": 21}, "device": {}},
        {"shared": {"target_temperature": 21.5, "current_temperature": 21}, "device": {}},
    ])
    coordinator = ThermostatCoordinator(MagicMock(), MagicMock(), api)
    with patch("custom_components.no_longer_evil.coordinator.time.monotonic", return_value=100.0) as clock:
        first = await coordinator._async_update_data()
        assert first["a"]["shared"]["target_temperature"] == 20.5
        coordinator.async_set_updated_data(first)
        clock.return_value = 110.0
        second = await coordinator._async_update_data()
        assert second["a"]["shared"]["target_temperature"] == 20.5
        assert second["a"]["shared"]["current_temperature"] == 20.7
        coordinator.async_set_updated_data(second)
        clock.return_value = 100.0 + TARGET_GRACE_SECONDS + 1
        third = await coordinator._async_update_data()
        assert "target_temperature" not in third["a"]["shared"]
        coordinator.async_set_updated_data(third)
        clock.return_value = 500.0
        fourth = await coordinator._async_update_data()
        assert fourth["a"]["shared"]["target_temperature"] == 21.5
    assert "API status omitted target_temperature" in caplog.text


async def test_partial_status_does_not_cache_invalid_target():
    api = MagicMock()
    api.devices = AsyncMock(return_value=[{"id": "a", "serial": "a"}])
    api.status = AsyncMock(side_effect=[
        {"shared": {"target_temperature": None, "current_temperature": 20}, "device": {}},
        {"shared": {"target_temperature": float("nan"), "current_temperature": 21}, "device": {}},
    ])
    coordinator = ThermostatCoordinator(MagicMock(), MagicMock(), api)
    first = await coordinator._async_update_data()
    assert "target_temperature" not in first["a"]["shared"]
    coordinator.async_set_updated_data(first)
    second = await coordinator._async_update_data()
    assert "target_temperature" not in second["a"]["shared"]
