"""API key configuration and reauthentication."""

import hashlib

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ApiError, AuthenticationError, NoLongerEvilApi, PermissionError
from .const import DOMAIN

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the hosted service using a masked API key field."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            key = user_input[CONF_API_KEY].strip()
            try:
                if not key.startswith("nle_") or any(c.isspace() for c in key):
                    raise AuthenticationError("Invalid key format")
                await NoLongerEvilApi(async_get_clientsession(self.hass), key).devices()
            except (AuthenticationError, PermissionError):
                errors["base"] = "invalid_auth"
            except ApiError:
                errors["base"] = "cannot_connect"
            else:
                digest = hashlib.sha256(key.encode()).hexdigest()
                if self.source == config_entries.SOURCE_REAUTH:
                    entry = self._get_reauth_entry()
                    if any(
                        other.unique_id == digest and other.entry_id != entry.entry_id
                        for other in self._async_current_entries()
                    ):
                        return self.async_abort(reason="already_configured")
                    self.hass.config_entries.async_update_entry(entry, unique_id=digest)
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_API_KEY: key}
                    )
                # API exposes no account ID; a digest avoids placing the key in IDs.
                await self.async_set_unique_id(digest)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="No Longer Evil", data={CONF_API_KEY: key}
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data):
        """Replace a revoked or expired key."""
        return await self.async_step_user()
