"""Asynchronous client for the documented hosted REST API."""

import asyncio
from datetime import datetime, timezone
import time
from urllib.parse import quote

import aiohttp

from .const import BASE_URL


class ApiError(Exception):
    """Safe API error containing no response bodies or credentials."""


class AuthenticationError(ApiError):
    """The API key was rejected."""


class PermissionError(ApiError):
    """The key lacks access or write scope."""


class NoLongerEvilApi:
    """Use HA's shared session, TLS verification and a fixed trusted origin."""

    def __init__(self, session, api_key):
        self._session = session
        self._api_key = api_key
        self._lock = asyncio.Lock()
        self._next_request = 0.0

    async def request(self, method, path, body=None):
        """Retry a rejected read once before requiring reauthentication."""
        try:
            return await self._request_once(method, path, body)
        except AuthenticationError:
            if method != "GET":
                raise
        # Release the request lock while waiting; never replay control commands.
        await asyncio.sleep(10)
        return await self._request_once(method, path, body)

    async def _request_once(self, method, path, body=None):
        """Serialize and pace calls below the documented 20/minute limit."""
        async with self._lock:
            await asyncio.sleep(max(0, self._next_request - time.monotonic()))
            self._next_request = time.monotonic() + 3.2
            try:
                async with self._session.request(
                    method,
                    BASE_URL + path,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=False,
                ) as response:
                    if response.status == 401:
                        raise AuthenticationError("API key rejected")
                    if response.status == 403:
                        raise PermissionError("API permission denied")
                    if response.status == 429:
                        delay = 60.0
                        try:
                            payload = await response.json()
                            retry = datetime.fromisoformat(
                                payload["retryAfter"].replace("Z", "+00:00")
                            )
                            delay = max(
                                delay,
                                (retry - datetime.now(timezone.utc)).total_seconds(),
                            )
                        except (ValueError, KeyError, TypeError, aiohttp.ClientError):
                            pass
                        self._next_request = time.monotonic() + delay
                        raise ApiError("API rate limit exceeded")
                    if response.status != 200:
                        raise ApiError(f"API returned HTTP {response.status}")
                    data = await response.json()
                    if (
                        not isinstance(data, dict)
                        or data.get("success") is False
                        or "error" in data
                    ):
                        raise ApiError("API returned an unsuccessful response")
                    return data
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                raise ApiError("Unable to communicate with the API") from None

    async def devices(self):
        data = await self.request("GET", "/devices")
        devices = data.get("devices")
        if not isinstance(devices, list) or any(
            not isinstance(d, dict)
            or not isinstance(d.get("id"), str)
            or not d["id"]
            or not isinstance(d.get("serial"), str)
            or not d["serial"]
            for d in devices
        ):
            raise ApiError("Invalid device list")
        return devices

    async def status(self, device_id, serial):
        data = await self.request(
            "GET", f"/thermostat/{quote(device_id, safe='')}/status"
        )
        state = data.get("state")
        if not isinstance(state, dict):
            raise ApiError("Invalid device state")
        values = {}
        for bucket in ("shared", "device"):
            raw = state.get(f"{bucket}.{serial}", {})
            if not isinstance(raw, dict):
                raise ApiError("Invalid state bucket")
            value = raw.get("value", {})
            if not isinstance(value, dict):
                raise ApiError("Invalid state bucket")
            values[bucket] = value
        if not values["shared"]:
            raise ApiError("Missing shared device state")
        return values

    async def command(self, device_id, endpoint, body):
        data = await self.request(
            "POST", f"/thermostat/{quote(device_id, safe='')}/{endpoint}", body
        )
        if data.get("success") is not True:
            raise ApiError("Command was not acknowledged")
