"""Contract and behavior tests using synthetic data, never real credentials."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.exceptions import HomeAssistantError

from custom_components.no_longer_evil.api import (
    ApiError,
    AuthenticationError,
    NoLongerEvilApi,
    PermissionError,
)
from custom_components.no_longer_evil.climate import ThermostatClimate
from custom_components.no_longer_evil.entity import discover_entities


def response(status=200, payload=None):
    result = MagicMock()
    result.status = status
    result.json = AsyncMock(return_value=payload)
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    return result


@pytest.mark.parametrize(
    "status,error",
    [
        (401, AuthenticationError),
        (403, PermissionError),
        (500, ApiError),
        (302, ApiError),
    ],
)
async def test_safe_http_errors(status, error):
    session = MagicMock()
    session.request.return_value = response(status)
    api = NoLongerEvilApi(session, "test-only-placeholder")
    with pytest.raises(error) as caught:
        await api.devices()
    assert "placeholder" not in str(caught.value)


async def test_contract_and_headers():
    session = MagicMock()
    session.request.return_value = response(
        payload={"devices": [{"id": "id", "serial": "serial"}]}
    )
    api = NoLongerEvilApi(session, "test-only-placeholder")
    assert (await api.devices())[0]["id"] == "id"
    args, kwargs = session.request.call_args
    assert args == ("GET", "https://nolongerevil.com/api/v1/devices")
    assert kwargs["headers"] == {"Authorization": "Bearer test-only-placeholder"}
    assert kwargs["allow_redirects"] is False
    api._next_request = 0
    session.request.return_value = response(payload={"success": True})
    await api.command(
        "id/escaped", "temperature", {"value": 21, "mode": "heat", "scale": "C"}
    )
    assert session.request.call_args.args[1].endswith("/id%2Fescaped/temperature")
    assert session.request.call_args.kwargs["json"] == {
        "value": 21,
        "mode": "heat",
        "scale": "C",
    }


async def test_status_bucket_parsing():
    api = NoLongerEvilApi(MagicMock(), "test")
    api.request = AsyncMock(
        return_value={
            "state": {
                "shared.s": {"value": {"current_temperature": 20}},
                "device.s": {"value": {"current_humidity": 40}},
            }
        }
    )
    assert await api.status("id", "s") == {
        "shared": {"current_temperature": 20},
        "device": {"current_humidity": 40},
    }
    api.request.return_value = {"state": {}}
    with pytest.raises(ApiError):
        await api.status("id", "s")


async def test_rate_limit_backoff():
    session = MagicMock()
    session.request.return_value = response(429, {"retryAfter": "2099-01-01T00:00:00Z"})
    api = NoLongerEvilApi(session, "test")
    with pytest.raises(ApiError, match="rate limit"):
        await api.devices()
    import time

    assert api._next_request > time.monotonic() + 60


def climate(shared):
    coordinator = MagicMock()
    coordinator.data = {
        "s": {"info": {"id": "id", "serial": "s"}, "available": True, "shared": shared}
    }
    coordinator.last_update_success = True
    coordinator.api.command = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return ThermostatClimate(coordinator, "s", "climate")


async def test_heat_capabilities_and_command():
    entity = climate(
        {
            "can_heat": True,
            "can_cool": False,
            "target_temperature_type": "heat",
            "hvac_heater_state": True,
        }
    )
    assert entity.hvac_modes == [HVACMode.OFF, HVACMode.HEAT]
    assert entity.hvac_action == HVACAction.HEATING
    await entity.async_set_temperature(temperature=21.5)
    entity.coordinator.api.command.assert_awaited_once_with(
        "id", "temperature", {"value": 21.5, "mode": "heat", "scale": "C"}
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_set_hvac_mode(HVACMode.COOL)


async def test_range_mapping_and_validation():
    entity = climate(
        {"can_heat": True, "can_cool": True, "target_temperature_type": "range"}
    )
    assert entity.hvac_mode == HVACMode.HEAT_COOL
    assert entity.hvac_action is None
    await entity.async_set_hvac_mode(HVACMode.HEAT_COOL)
    entity.coordinator.api.command.assert_awaited_with(
        "id", "mode", {"mode": "heat-cool"}
    )
    await entity.async_set_temperature(target_temp_low=19, target_temp_high=23)
    entity.coordinator.api.command.assert_awaited_with(
        "id", "temperature/range", {"low": 19, "high": 23, "scale": "C"}
    )
    for kwargs in (
        {"target_temp_low": 24, "target_temp_high": 20},
        {"target_temp_low": float("nan"), "target_temp_high": 20},
    ):
        with pytest.raises(HomeAssistantError):
            await entity.async_set_temperature(**kwargs)


def test_discovery_and_removal():
    coordinator = MagicMock()
    coordinator.data = {"s": {"available": True}}
    add = MagicMock()
    discover_entities(coordinator, add, lambda serial, data: [("climate", serial)])
    listener = coordinator.async_add_listener.call_args.args[0]
    listener()
    assert add.call_count == 1
    coordinator.data["new"] = {"available": True}
    listener()
    assert add.call_count == 2
    entity = climate({"target_temperature_type": "off"})
    entity.coordinator.data = {}
    assert entity.available is False


async def test_config_flow_invalid_and_success():
    from custom_components.no_longer_evil.config_flow import ConfigFlow

    flow = ConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": "user"}
    with (
        patch("custom_components.no_longer_evil.config_flow.async_get_clientsession"),
        patch("custom_components.no_longer_evil.config_flow.NoLongerEvilApi") as api,
    ):
        api.return_value.devices = AsyncMock(
            side_effect=AuthenticationError("rejected")
        )
        result = await flow.async_step_user({"api_key": "nle_test_placeholder"})
        assert result["errors"] == {"base": "invalid_auth"}
        api.return_value.devices = AsyncMock(return_value=[])
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        result = await flow.async_step_user({"api_key": "nle_test_placeholder"})
        assert result["type"] == "create_entry"
        assert "nle_" not in flow.async_set_unique_id.call_args.args[0]
