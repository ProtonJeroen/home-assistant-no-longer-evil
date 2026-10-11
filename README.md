# No Longer Evil Thermostat for Home Assistant

Version **0.1.0** — a custom integration for the **hosted** No Longer Evil service.
Requires Home Assistant 2025.1 or newer. Self-hosted servers use a different API
and are not supported in this version.

## Installation with HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/ProtonJeroen/home-assistant-no-longer-evil` with category **Integration**.
3. Find **No Longer Evil Thermostat** in HACS and download it.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration → No Longer Evil Thermostat**.

For manual installation, copy `custom_components/no_longer_evil` into your
Home Assistant configuration's `custom_components` folder and restart.

## Configuration and security

Generate an API key at [No Longer Evil settings](https://nolongerevil.com/settings)
with **read and write** scopes and access to your thermostats. Enter it in the
masked configuration field. Devices are discovered automatically at setup and
on subsequent polls, including devices shared with your account.

The key is sent only as an HTTPS Bearer header to the fixed official API origin.
Redirects are disabled and TLS certificates are verified. Home Assistant stores
the key in its configuration entry storage; protect your configuration and backups.
The integration does not log keys or response bodies. Never put real keys in
source files, issues, screenshots or commits. Revoked keys prompt reauthentication.
Use one entry per account to avoid duplicate devices and shared rate limits.
The API provides no account identity or scope-introspection endpoint; setup
validates read access without sending a thermostat command. Missing write scope
is reported when a control is attempted.

## Entities and behavior

- Climate: current and target temperature, HVAC mode and heating/cooling action.
- Heat and cool controls appear only when `can_heat` / `can_cool` report support.
- When equipment flags are absent, the explicitly reported active mode remains
  available for temperature control. No other modes are inferred. If the API
  also omits the active mode, the climate state remains unknown.
- Combined heat/cool mode provides low and high setpoints. Temperatures use Celsius
  internally; Home Assistant converts them for your preferred display unit.
- Optional diagnostic sensors: humidity, backplate temperature, battery level and
  estimated seconds to target. Sensors appear only when the device reports them.
  Battery level is a raw number because its unit is not documented.
- Polling starts at 60 seconds and increases for larger accounts. Requests are
  serialized at least 3.2 seconds apart, with server-directed rate-limit backoff.
  Commands and refreshes may take several seconds. Rate limits are shared with
  other clients using the same key.
- Failed or removed devices become unavailable; their registry entries remain
  available for user cleanup. A service outage marks coordinator entities unavailable.

English and Dutch UI translations are included. Fan, eco/away, emergency heat,
schedules and locks are not exposed in v0.1.0. The documented hosted mode endpoint
does not support emergency heat; occupancy documentation also disagrees on away
values, so no inferred occupancy entity is provided. No energy-use estimate or
network device scanning is implemented.

## Verified API contract

Checked against the official documentation on **2026-10-11**. All paths below
are relative to `https://nolongerevil.com/api/v1`. See [authentication](https://docs.nolongerevil.com/api-reference/authentication).

| Operation | Endpoint | Format used |
| --- | --- | --- |
| Inventory | [GET /devices](https://docs.nolongerevil.com/api-reference/v1/devices) | `devices[]`: `id`, `serial`, `name` |
| State | [GET /thermostat/{deviceId}/status](https://docs.nolongerevil.com/api-reference/v1/get-status) | `state["shared.<serial>"].value`, `state["device.<serial>"].value` |
| Temperature | [POST /thermostat/{deviceId}/temperature](https://docs.nolongerevil.com/api-reference/v1/set-temperature) | `{"value": number, "mode": "heat" or "cool", "scale": "C"}` |
| Mode | [POST /thermostat/{deviceId}/mode](https://docs.nolongerevil.com/api-reference/v1/set-mode) | `{"mode": "heat", "cool", "heat-cool" or "off"}` |
| Range | [POST /thermostat/{deviceId}/temperature/range](https://docs.nolongerevil.com/api-reference/v1/set-temperature-range) | `{"low": number, "high": number, "scale": "C"}` |

Commands require `success: true`. Device IDs address REST endpoints; serials
identify state buckets, Home Assistant entities and devices. Reported `range`
maps to Home Assistant `heat_cool` and outgoing `heat-cool`.

The [device state model](https://docs.nolongerevil.com/nest-protocol/device-state)
documents temperature fields, Celsius units, the 4.5–32°C range, equipment flags,
HVAC operation booleans and optional diagnostic fields. Unknown state remains
unknown rather than being inferred from setpoint differences.

## Development

Use Python 3.12 in a virtual environment:

```sh
pip install -r requirements-test.txt
ruff check .
pytest -q
```

Tests use synthetic responses and mocked commands. CI runs tests and HACS
structure validation. A real hosted account and physical thermostat are required
for end-to-end validation; no real API credentials are included in this repository.
