# Orion Sleep - Home Assistant HACS Integration

## Project Overview

HACS-compatible Home Assistant custom integration for the **Orion Sleep** smart mattress topper. Cloud-connected bed temperature control with per-zone support, sleep tracking (heart rate, breath rate, HRV, sleep stages), and sleep scheduling.

## Repository Structure

```
home-assistant-orion-integration/
├── hacs.json                          # HACS repo metadata
├── README.md                          # User-facing install/usage docs
├── openapi.yaml                       # OpenAPI 3.1 spec (reverse-engineered; WS section validated on-wire)
├── orion_info.py                      # Working CLI script (REST + WS capture tooling)
├── custom_components/
│   └── orion_sleep/
│       ├── __init__.py                # async_setup_entry / async_unload_entry
│       ├── manifest.json              # HA integration manifest (v1.0.0)
│       ├── const.py                   # DOMAIN, config keys, defaults, temp lookup table
│       ├── api.py                     # Async aiohttp API client
│       ├── coordinator.py             # DataUpdateCoordinator + data helpers
│       ├── config_flow.py             # Auth flow (email/phone OTP or API key) + options flow
│       ├── entity.py                  # Base entity with DeviceInfo + temp conversion helpers
│       ├── climate.py                 # Bed temperature control
│       ├── sensor.py                  # Sleep insight + schedule + offset + WS state sensors (18 per device)
│       ├── websocket.py                # Live device WebSocket client (per-device aiohttp)
│       ├── binary_sensor.py           # Sleep session active
│       ├── switch.py                  # Power (user-away) + sleep schedule switches
│       ├── diagnostics.py             # Diagnostics with PII redaction
│       ├── strings.json               # UI translations
│       ├── translations/
│       │   └── en.json                # English translations (mirrors strings.json)
│       └── brand/                     # Integration icon (96px + 180px)
```

## Source-of-Truth Policy

Both `openapi.yaml` and `orion_info.py` are kept in sync as new endpoints or behaviors are discovered. The REST section of the spec is reverse-engineered from the Android bytecode with spot-checks against the live API; the WebSocket section (`/device/{serial_number}` path and `x-websocket` block) is validated by an on-wire capture (`orion_info.py --ws-scenario`). Neither file is inherently more authoritative — when they disagree, re-verify against the live server rather than trusting one blindly.

Known gaps and unverified endpoints are called out in the tables below. When adding or changing behavior:

1. Prefer running `orion_info.py --ws-scenario` (or the individual flags) against a live account to confirm on-wire shapes.
2. Update **both** `openapi.yaml` and the relevant comments/flags in `orion_info.py`.
3. Reflect any new limitations or caveats in this file.

### API Base URL

```
https://api1.orionbed.com
```

### Working Endpoints

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| POST | `/v1/auth/code` | No | Send verification code to email/phone |
| POST | `/v1/auth/do` **or** `/v1/auth/verify` | No | Verify code, get tokens. The spec now documents `/v1/auth/do` (from Android bytecode); the previously live-verified endpoint was `/v1/auth/verify`. Code tries `/v1/auth/do` first and falls back to `/v1/auth/verify`. Response handled in all known shapes — see `_extract_tokens`. |
| POST | `/v1/auth/refresh` | No | Refresh tokens. Body sends both `refreshToken` (current spec) and `refresh_token` (legacy) so the request works regardless of which key the live API requires. Response handled by `_extract_tokens`. |
| GET | `/v1/auth/me` | Bearer | User profile. Wrapped in `{"response": {...}, "success": true}`. Also used to validate pasted API keys during HA config flow. |
| GET | `/v1/api-keys` | Bearer | List API key metadata (`response.api_keys[]`). No raw keys. Live-verified 2026-07-19. |
| POST | `/v1/api-keys` | Bearer | Create API key. Body: `{"name": "..."}` (required). Returns raw `api_key` once in `response`. Format: `os_live_...`, long-lived. |
| DELETE | `/v1/api-keys/{id}` | Bearer | Revoke key. Live-verified 2026-07-19. |
| GET | `/v1/devices` | Bearer | Devices at `response.devices[]`. Fields: `id`, `serial_number`, `name`, `model`, `zones[]`, `temperature_range`, `temperature_scale` |
| GET | `/v1/sleep-schedules` | Bearer | Schedules at `response.schedules.{user_id}[]` (7 days). Also `today_sleep_schedule.{user_id}` and `response.recommendations.{user_id}[]` — **Orion Intelligence temperature recommendations** (live-verified 2026-07-19; see "Real API Response Shapes" below). |
| PUT | `/v1/sleep-schedules` | Bearer | Update schedule. Body: `{"schedules": [{"day": N, field: value}]}`. Partial updates work (only specified field changes). |
| POST | `/v1/sleep-configurations/user-away` | Bearer | Presence override. Body: `{"user_id": "...", "is_away": bool}`. Also powers the device down; prefer `/v1/devices/{id}/live` for pure power control. |
| PUT | `/v1/devices/{deviceId}` | Bearer | Update metadata (`name`, `orientation`, `timezone`). Partial updates accepted. |
| GET | `/v1/devices/{serial_number}/live` | Bearer | **Live runtime snapshot** (zones with `on`/`temp`, status, sensors, firmware). Path uses `serial_number`, NOT UUID. |
| PUT | `/v1/devices/{serial_number}/live` | Bearer | **Canonical power/temp primitive.** Path uses `serial_number`, NOT UUID (UUID returns `403 "Device not found"`). Body: `{"zones": [{"id": "zone_a", "on": bool, "temp": float}, ...]}`. Each zone requires `id` and at least one of `on`/`temp` (Celsius). |
| PUT | `/v1/devices/{serial_number}/live/zones/{zoneId}` | Bearer | Single-zone power/temp. Path uses `serial_number`. Body: `{on?, temp?}` with `minProperties: 1`. |
| POST | `/v1/devices/{deviceId}/action` | Bearer | Device action (quiet_mode, reboot, LED brightness, etc.). **No power action** — `DeviceAllowedAction` enum contains no on/off. Body: `{"action": "...", "value"?: ...}`. |
| POST | `/v1/devices/{deviceId}/activate` | Bearer | Pair device to account. Body: `{"model": "OSCT001-1"}`. |
| POST | `/v1/devices/{deviceId}/deactivate` | Bearer | Unpair device. |
| POST | `/v1/devices/{deviceId}/update` | Bearer | Trigger firmware update. |
| GET | `/v2/insights?from=&to=` | Bearer | NOT wrapped in `response`. Top-level: `{user_id, has_subscription, data: {date: {score, quality, color, sessions[]}}, overview: {date: {score, quality, color}}}`. Session shape has grown significantly since first documented — see "Real API Response Shapes" below. |
| GET | `/v3/insights` | Bearer | **New 2026-07-16.** NOT wrapped in `response`. Pre-aggregated day/week/month trend data — backs the "new sleep insights" surface (consistency, sleep debt, breathing disturbances, calendar/trends view) announced 2026-07-15. Response shape live-verified against the **primary account only**. `api.py`'s `get_insights_v3()` is now wired into the coordinator poll for both the primary and partner `OrionApiClient` instances (2026-07-16) — same bearer-token client/error-handling path already proven for partner `/v2/insights` — but the partner-side *response shape* specifically has not yet been independently observed (partner OTP re-login wasn't available during this pass, and probing from outside the running integration isn't possible). No account-type special-casing exists anywhere in the client, so no divergence is expected; treat as reasoned-not-observed until the next partner poll's diagnostics are checked. `from`/`to` params probed, did not change the returned window — treat as unverified/no-op. |

### Non-Working / Unverified Endpoints

| Path | Status | Notes |
|------|--------|-------|
| `/v1/sleep-configurations/devices` | **404** | Does not exist despite OpenAPI spec |
| `/v1/sleep-configurations/temperature` | Unverified | PUT to set temp — not tested against live API |
| `/v1/sleep-schedules?action=enable` | Unverified | Schedule enable/disable — body format `{"enabled": bool}` not confirmed |
| `/v1/session-state` | Returns onboarding state | `{patch_step, is_survey_complete, ...}` — NOT sleep session state |

### Real API Response Shapes

**Devices** — each device has:
- `id` (UUID), `serial_number`, `name`, `model` ("OSCT001-1"), `type` ("control_tower")
- `zones`: `[{id: "zone_a", user: {...}}, {id: "zone_b", user: {...}}]`
- `temperature_range`: `{min: 10, max: 45}` (Celsius)
- `temperature_scale.fahrenheit[]`: `{in: 50..113, out: 10..45}` mapping
- `temperature_scale.relative[]`: `{in: -10..+10, out: 10..45}` non-linear offset-to-Celsius mapping
- `orientation`, `timezone`, `permissions`, `default_zone_id`

**Schedules** — keyed by user_id, 7 entries (day 0-6):
- `bedtime`, `wakeup` (HH:mm strings)
- `bedtime_is_active`, `wakeup_is_active` (booleans)
- `bedtime_temp`, `wakeup_temp`, `phase_1_temp`, `phase_2_temp` (Celsius floats)
- `auto_turn_off`, `is_smart_temperature_active`
- `override_date`, `is_override_available`, `is_override_applied`

**Insights sessions** (`/v2/insights`) — each session has:
- `session_id`, `zone_id`, `is_in_progress`, `start_time`, `end_time`, `confidence`
- `sleep_summary`: `{time_asleep, deep_sleep, rem_sleep, light_sleep, awake_time, hypnogram[]}` (minutes; `hypnogram` is a per-~30s-epoch integer stage timeline, meaning not yet decoded)
- `heart_rate` / `breath_rate` / `hrv`: `{average, min, max, values[], axis: {min, max}}` (BPM / breaths-min / ms; HRV often null)
- `movement`: `{total_seconds, movement_rate, left_bed_seconds, values[]}`
- `temperature` / `temperature_control` / `temperature_setpoint`: each `{values[]}` (Celsius floats, ~3 per minute). The latter two are new (2026-07-16) and undecoded — plausibly control-loop target vs. active setpoint, unconfirmed.
- `apnea`: **new (2026-07-16)**: `{ahi, longest_event_seconds, central_total_seconds, obstructive_total_seconds, values[]}` — plausibly the session-level breathing-disturbance signal (same `session_id` links to `/v3/insights`' `breathing_disturbances` metric)
- Also new (2026-07-16), previously undocumented: `is_combined`, `combined_zone_ids` (dual-zone/occupancy detection, always `false`/`null` observed), `user_rating`, `user_fallasleep_timestamp`, `user_wakeup_timestamp`, `has_been_edited`, `has_been_rated` (manual session editing/rating — no known write endpoint yet), `last_updated_at`, `timezone`, `in_bed_start_time`, `in_bed_end_time`, `device: {id, serial_number, name, model, type, timezone, orientation}` (embedded device, previously only from `/v1/devices`), `manual_confirmation: {needs_confirmation, status, users[]}` (lists both the primary and partner account users — even on the primary account's own token, confirming session data is shared/linked across a paired household)

**Temperature recommendations** (`response.recommendations`, `/v1/sleep-schedules`, discovered 2026-07-19) — a dict keyed by `user_id`, one entry **per user sharing the device** (not just the requesting account — on the probed account this included both zone_a/zone_b users and both anonymous guest users, four keys total, matching `today_sleep_schedule`'s keys). Each value is an **array, observed empty (`[]`) for every user** on the probed account despite `has_subscription: true` and `bundle: true` on `/v3/insights` and ~2.5 months of continuous sleep history (`data_availability.earliest_date` to `latest_date`) — i.e. subscription + data volume alone don't guarantee a populated array; the feature is presumably intermittent (recommendations appear only when Orion's model has something new to suggest) or gated by a rollout/cohort flag not otherwise visible in the API. **No non-empty sample has been captured, so the item schema inside the array is unknown.** `orion_info.py --recommendations` isolates this map for quick re-checking without scrolling the full schedule dump. Note: a *related but distinct* per-day schedule field, `is_override_available` (seen `true` only on the current day-of-week entry for two of the four users), may or may not be connected to this feature — unconfirmed, flagged here so a future pass doesn't have to rediscover the correlation.

**Insights v3 trends** (`/v3/insights`, new 2026-07-16) — top-level: `{user_id, has_subscription, bundle, timezone, data_availability: {earliest_date, latest_date, latest_insight_date}, granularities: {day, week, month}}`. Each granularity: `{range: {start_date, end_date, count}, data: {period_key: {period_key, granularity, start_date, end_date, overview: {score, rating, color, award, state}, days_with_data, previous_data_date, days[], metrics}}}`. `metrics` always has exactly 8 keys: `sleep_duration`, `body_movements`, `breathing_disturbances`, `consistency`, `sleep_debt`, `hrv`, `heart_rate`, `breath_rate` — each a `{value, unit, polarity, insight (human-readable string), comparisons: {vs_prior_day, vs_prior_week, vs_prior_month}, series[], axis, details, show, state, sessions[]}` envelope. `sleep_debt` additionally has `need` (computed baseline minutes) and `status` (`"balanced"`/`"low"` observed). `sessions[].session_id` matches `/v2/insights` session IDs, confirming `/v3/insights` re-aggregates the same underlying sessions rather than a separately modeled data source (spot-checked: v2 `time_asleep` 433min vs v3 `sleep_duration.value` 429min for the same session — minor rounding difference, not a distinct model).

### Key Gotchas

- Token fields were **snake_case** (`access_token`) when verified against the live API, but the current OpenAPI spec (from Android bytecode) shows **camelCase** (`accessToken`). `_extract_tokens` in `api.py` handles all three known shapes: nested-snake, flat-camelCase, flat-snake.
- The auth verification endpoint was `/v1/auth/verify` when live-verified; the spec now says `/v1/auth/do`. Code tries both.
- Refresh request body similarly sends both `refreshToken` (spec) and `refresh_token` (legacy) keys.
- Token expiry uses `expires_at` Unix timestamp, NOT JWT parsing
- Insights endpoints (`/v2/insights`, `/v3/insights`) do NOT wrap in `response` — top-level
- `/v3/insights` and its new metrics are response-shape-verified against the **primary account only** (2026-07-16). The coordinator now also fetches it for the partner account (2026-07-16) via the same client path already proven for partner `/v2/insights`; check partner-side diagnostics/logs after a live poll before treating the shape itself as independently confirmed.
- All other endpoints wrap data in `{"response": {...}, "success": true}`
- Temperature values throughout the API are in **Celsius**
- Device zones are `zone_a`/`zone_b`, not `left`/`right`
- Sleep session detection uses `is_in_progress` from insights, not `/v1/session-state`
- Device power state is read from each zone's `on`/`is_on` field (set via `PUT /v1/devices/{id}/live`); `set_user_away` affects the `user` field but is a separate presence override
- Temperature offsets (app-style -10 to +10) map **non-linearly** to absolute Celsius via `temperature_scale.relative` table

## Architecture

- **Polling**: `DataUpdateCoordinator` polls `/v1/devices`, `/v1/sleep-schedules`, and `/v2/insights` on a configurable interval (default 600s)
- **One-time data**: User profile fetched once in `_async_setup()`
- **Per-poll data**: Device list re-fetched each poll to detect away/present (power) state changes
- **Token persistence**: Refresh callback updates `config_entry.data` so tokens survive HA restarts
- **Error handling**: Each polled endpoint has independent try/except — one failing doesn't break the others. Auth errors (`OrionAuthError`) always raise `ConfigEntryAuthFailed` to trigger re-auth flow.
- **Auth flow**: Email/phone OTP (pick method → enter address → verification code) **or API key** (paste `os_live_...` from https://app.orionsleep.com/api-keys, validated via `GET /v1/auth/me`). Re-auth for API keys prompts for a freshly minted key (no refresh). Partner account supports the same methods in the options flow.
- **Options flow**: Configurable `scan_interval` (60-3600s) and `insights_days` (1-30 days)
- **Temperature conversion**: `OrionBaseEntity` provides `_celsius_to_offset()` and `_offset_to_celsius()` using per-device lookup table (falls back to `DEFAULT_RELATIVE_TEMP_TABLE` in `const.py`)

### Data Flow

```
Config Flow (auth) --> tokens stored in config_entry.data
       |
       v
__init__.py creates OrionApiClient + OrionDataUpdateCoordinator
       |
       v
coordinator._async_setup() -- fetches user profile + devices (once)
       |
       v
coordinator._async_update_data() -- polls every N seconds:
  1. ensure_valid_token() (auto-refresh, persists via callback)
  2. list_devices()        --> coordinator.devices (away/present detection)
  3. OrionWebSocketManager.sync_to_serials() (start/stop per-device WS)
  4. get_live_device(serial) per device (skipped when WS is fresh)
  5. get_sleep_schedules() --> data["schedules"]
  6. get_insights(days=N)  --> data["insights"]
  7. get_insights_v3()     --> data["insights_v3"]
  (partner client, when configured, repeats 5-7 into the partner_* keys)
       |
       v
Per-device live WebSocket (wss://live.api1.orionbed.com/device/<serial>):
  - Pushes live_device.snapshot on connect, live_device.update on every
    state change (+ idle heartbeat every ~2s)
  - Coordinator._handle_ws_message merges payload into live_devices
    and calls async_set_updated_data() so entities refresh immediately
  - Timeline field is stored at data["ws_timelines"][device_id]
       |
       v
Entities read from coordinator:
  - Climate: schedule (target temp, HVAC mode) + session (current temp)
  - Number: per-phase app-style temperature offsets (-10..+10)
  - Sensors: insights sessions + schedule + overview scores
             + per-topper-sensor live HR/BR/status (from WS)
  - Binary sensors: session.is_in_progress
                    + per-topper-sensor occupancy (from WS)
  - Switches: device zones (power) + user-away (away mode)
              + schedule.bedtime_is_active
  - Diagnostic sensors: per-device WS connection state
                        + per-topper-sensor raw status_text
```

## Entities

| Platform | Entity | Key / unique_id suffix | Data Source |
|----------|--------|----------------------|-------------|
| Climate | Bed Climate | `_climate` | Target temp from live setpoint `zones[].temp`; current temp from live measured `status.zones[].temp` (WS, ~2s) |
| Sensor | Sleep Score Left / Right | `_{zone_id}_sleep_score` | per-zone `session.score` (via `get_latest_session_for_zone`) with `quality_rating` extra attr |
| Sensor | Total Sleep Time | `_total_sleep_time` | `session.sleep_summary.time_asleep` (formatted as "Xh Ym") |
| Sensor | Deep Sleep Time | `_deep_sleep_time` | `session.sleep_summary.deep_sleep` |
| Sensor | REM Sleep Time | `_rem_sleep_time` | `session.sleep_summary.rem_sleep` |
| Sensor | Light Sleep Time | `_light_sleep_time` | `session.sleep_summary.light_sleep` |
| Sensor | Awake Time | `_awake_time` | `session.sleep_summary.awake_time` |
| Sensor | Heart Rate Average | `_heart_rate_avg` | `session.heart_rate.average` + min/max/range extra attrs |
| Sensor | Breath Rate | `_breath_rate` | `session.breath_rate.average` + min/max/range extra attrs |
| Sensor | HRV Left / Right | `_{zone_id}_hrv` | per-zone `session.hrv.average` (via `get_latest_session_for_zone`), current value only |
| Sensor | Body Movement Rate | `_body_movement_rate` | `session.movement.movement_rate` |
| Sensor | Restless Time | `_restless_time` | `session.movement.total_seconds` (formatted as "Xm Ys") |
| Sensor | Bedtime | `_bedtime` | `today_sleep_schedule.bedtime` (HH:mm) |
| Sensor | Wake-up Time | `_wakeup_time` | `today_sleep_schedule.wakeup` |
| Sensor | Schedule Duration | `_schedule_duration` | Calculated from bedtime/wakeup (handles overnight) |
| Sensor | Bedtime Temperature | `_bedtime_temp` | `today_sleep_schedule.bedtime_temp` + phase/smart temp extra attrs |
| Sensor | Wake-up Temperature | `_wakeup_temp` | `today_sleep_schedule.wakeup_temp` |
| Sensor | Current Temp Offset | `_current_temp_offset` | Latest session `temperature.values[-1]` converted to app-style offset. |
| Sensor | Temperature Recommendations | `_temperature_recommendations` | `response.recommendations.{user_id}` from `/v1/sleep-schedules` (`coordinator.get_recommendations()`). State = pending-recommendation count (`0` is the normal, observed steady state); raw list exposed as a `recommendations` extra attribute since the item schema is unconfirmed (see "Real API Response Shapes"). `None`/unavailable if the `recommendations` key is absent from the response entirely. Partner variant mirrors via the partner account's own schedules response. |
| Sensor (diag) | Live Connection | `_websocket_state` | WS connection state (`connecting`/`connected`/`reconnecting`/`device_offline`/`auth_failed`/`stopped`) plus `seconds_since_last_message` extra attr |
| Sensor | Sensor 1/2 Heart Rate | `_sensorN_live_heart_rate` | WS `status.sensors.sensorN.heart_rate` (bpm). `0` (empty bed) and `255` (no reading yet) both mapped to `None`. |
| Sensor | Sensor 1/2 Breath Rate | `_sensorN_live_breath_rate` | WS `status.sensors.sensorN.breath_rate` (br/min). Same sentinel handling. |
| Sensor (diag) | Sensor 1/2 Status | `_sensorN_sensor_status` | Raw `status_text`: observed `left_bed` (empty) and `normal` (occupied). |
| Sensor | Left/Right Bed Temperature | `_{zone_id}_measured_temp` | `status.zones[].temp` from WS — actual measured bed temp in °C, updated every ~2s. `thermal_state` exposed as extra attribute. |
| Sensor | Left/Right Thermal State | `_{zone_id}_thermal_state` | `status.zones[].thermal_state` from WS — `standby` observed; `heating`/`cooling` expected but unconfirmed. |
| Binary Sensor | Sleep Session Active | `_session_active` | `session.is_in_progress` (shows "Asleep" / "Not asleep") |
| Binary Sensor | Sensor 1/2 On Bed | `_sensorN_on_bed` | Occupancy device class. `status_text != "left_bed"`. The WS push itself is realtime, but the topper takes ~30s–1min to decide someone has sat down or left, so `status_text` transitions lag the real event. |
| Switch | Power | `_power` | On = all zones on, Off = all zones off. Uses `PUT /v1/devices/{id}/live` (canonical power primitive). State read from each zone's `on`/`is_on` field. |
| Switch | Away Mode | `_away_mode` | On = user marked away, Off = user present. State read from `zones[*].user` (null across all zones = away). `POST /v1/sleep-configurations/user-away`. Returns `400 "User has no previous device to return to"` on no-op toggle — swallowed in the switch. |
| Switch | Sleep Schedule | `_sleep_schedule` | `today_sleep_schedule.bedtime_is_active`. Toggle via `update_sleep_schedule`. |
| Number | Bedtime Temperature Offset | `_bedtime_temp_offset` | App-style -10..+10 slider. Reads `today_sleep_schedule.bedtime_temp`, converts to offset via per-device relative table; writes back via `PUT /v1/sleep-schedules` on today's day-of-week. |
| Number | Asleep Phase 1 Offset | `_phase_1_temp_offset` | As above, `phase_1_temp` field. |
| Number | Asleep Phase 2 Offset | `_phase_2_temp_offset` | As above, `phase_2_temp` field. |
| Number | Wake Up Temperature Offset | `_wakeup_temp_offset` | As above, `wakeup_temp` field. |

**Per device: 1 climate + 4 number + 28 sensors + 3 binary sensors + 3 switches = 39 entities**

- 28 sensors = 11 insights + 5 schedule + 1 current-temp-offset + 1 live-connection + 6 per-sensor live (2× HR + 2× BR + 2× diag status_text) + 4 zone live (2× measured temp + 2× thermal state).
- 4 number sliders: one per schedule-phase temperature offset (bedtime / phase_1 / phase_2 / wakeup).
- 3 binary sensors: Sleep Session Active + 2× On Bed (sensor1/sensor2).
- 3 switches: Power, Away Mode, Sleep Schedule.

### Sensor Implementation Notes

- Duration sensors (total sleep, deep sleep, etc.) deliberately avoid `device_class=DURATION` because HA would override entity names
- Sleep score has special handling: reads from `insights.overview` (not sessions) and adds `quality_rating` extra attribute ("Excellent" >= 90, "Good" >= 80, "Fair" >= 60, "Poor" < 60)
- Temperature offset conversion uses per-device `temperature_scale.relative` lookup table, non-linear mapping
- Heart rate and breath rate sensors include min/max/range as extra state attributes

## API Client (`api.py`)

### Exception Hierarchy
- `OrionApiError` — base for all API errors
- `OrionAuthError(OrionApiError)` — 401 / invalid tokens
- `OrionConnectionError(OrionApiError)` — network failures (`aiohttp.ClientError`)

### Token Management
- `_token_expired(margin_seconds=60)` — checks `time.time() + 60` against `expires_at`
- `ensure_valid_token()` — auto-refreshes if expired
- `_extract_tokens(data)` — static helper; normalises token response from nested-snake, flat-camelCase, or flat-snake shapes
- `_refresh_tokens()` — sends both `refreshToken` and `refresh_token` body keys; parses response via `_extract_tokens`
- `verify_auth_code()` — tries `/v1/auth/do` then `/v1/auth/verify`; parses response via `_extract_tokens`
- `set_token_refresh_callback(callback)` — called after successful refresh to persist tokens

### Action Methods
| Method | Endpoint | Status |
|--------|----------|--------|
| `set_temperature(device_id, temperature, zone_id)` | `PUT /v1/sleep-configurations/temperature` | **Unverified** (prefer `update_live_device_zone[s]`) |
| `set_user_away(user_id, is_away)` | `POST /v1/sleep-configurations/user-away` | Working (used by away-mode switch; presence override) |
| `update_device(device_id, **fields)` | `PUT /v1/devices/{deviceId}` | Metadata updates (name/orientation/timezone) |
| `update_live_device_zones(device_id, zones)` | `PUT /v1/devices/{deviceId}/live` | **Canonical power primitive** (used by power switch) |
| `update_live_device_zone(device_id, zone_id, on=, temp=)` | `PUT /v1/devices/{deviceId}/live/zones/{zoneId}` | Per-zone power/temp |
| `device_action(device_id, action, value=)` | `POST /v1/devices/{deviceId}/action` | quiet_mode/reboot/etc. — NOT for power |
| `activate_device(device_id, model)` | `POST /v1/devices/{deviceId}/activate` | Pair device |
| `deactivate_device(device_id)` | `POST /v1/devices/{deviceId}/deactivate` | Unpair device |
| `trigger_firmware_update(device_id)` | `POST /v1/devices/{deviceId}/update` | Firmware update |
| `update_schedule_temperature(day, field, celsius)` | `PUT /v1/sleep-schedules` | Partial updates verified |
| `update_sleep_schedule(schedule_data, action)` | `PUT /v1/sleep-schedules` | **Unverified** for enable/disable action |

## Testing

Run `orion_info.py` to verify API connectivity and response shapes:
```bash
python orion_info.py --email user@example.com
python orion_info.py --phone 15132015808
```
Tokens cache to `~/.orion_tokens.json`. Use `--relogin` to force fresh auth.

`orion_info.py` also always fetches `/v3/insights` (trends: consistency, sleep debt, breathing disturbances) alongside `/v2/insights` — no flag needed. This standalone script can only exercise the account it logs in as; verifying the partner side through it would require an interactive OTP login as the partner (`--email`/`--phone` + `--relogin` for their account), which wasn't available during this pass. The coordinator (`coordinator.py`) takes a different path that sidesteps this: it already holds an authenticated `OrionApiClient` for the partner (`self._partner_api_client`, used every poll for `/v2/insights`), and now calls `get_insights_v3()` through it too — so partner-side `/v3/insights` parity gets exercised on every live poll without needing OTP.

Additional `orion_info.py` flags:
- `--insights-days N` — number of days of insights to fetch
- `--set-away` / `--set-present` — toggle device power, then re-fetch devices/schedules to show changes
- `--power-on` / `--power-off` — probe `PUT /v1/devices/{ident}/live` against both `id` and `serial_number`
- `--websocket [--ws-duration N]` — open `/device/<serial>?token=<JWT>` and log every frame for N seconds (default 60)
- `--ws-scenario` — open the WebSocket and drive a scripted sequence of REST edits (zone on/off, temp low/high, bulk on/off, user-away) while logging frames; restores the original zone state at the end. Use this to re-verify the event taxonomy against the live server.
- `--recommendations` — isolate and print just `response.recommendations.{user_id}` from the sleep-schedules response (Orion Intelligence temperature recommendations), with a per-user pending count, instead of scrolling the full schedule dump.

## WebSocket — Live Device Data

Validated against the live server with `orion_info.py --ws-scenario`.

### Connection

```
wss://live.api1.orionbed.com/device/<serial_number>?token=<JWT>
```

- Path uses the device's **`serial_number`**, NOT its UUID `id` (UUID returns 404 `{"error":"Not Found","message":"Device not found"}`).
- JWT is passed as a `token` query parameter.
- Cloudflare negotiates HTTP/2 by default which breaks the WS upgrade — the SSL context **must force ALPN to `http/1.1`**.
- Working User-Agent: `okhttp/4.12.0`.
- **No client-side handshake**. The server pushes `live_device.snapshot` immediately after the Upgrade completes, then `live_device.update` on state changes and approximately every 2s as an idle refresh.
- Close code `1001` on clean client shutdown.
- On 401 during upgrade, refresh via `POST /v1/auth/refresh` and reconnect with the new token.

### Event Taxonomy (exhaustive as of last capture)

| `type` | When | Notes |
|---|---|---|
| `live_device.snapshot` | Once, immediately after connect | Full state |
| `live_device.update` | On every REST mutation to `/v1/devices/{serial}/live[/zones/{zone}]` or `/v1/sleep-configurations/user-away`, plus ~every 2s as an idle refresh | Same payload shape as snapshot; may include a `timeline` array of today's schedule actions |

Both use the envelope `{"type": <event>, "payload": {...}}`. `set_user_away` does **not** emit a distinct event type — it produces another `live_device.update` with zones powered accordingly.

### Payload Shape (shared between snapshot and update)

```text
payload.serial_number         string
payload.model                 e.g. "OSCT001-1"
payload.zones[]               setpoints (user intent): {id, temp (°C), on}
payload.led_brightness        int 0-100
payload.water_fill            string (observed "unknown")
payload.is_in_water_fill_mode bool
payload.status.online         bool
payload.status.firmware       {cb, ib}
payload.status.firmware_update {workflow_id, started_at, updated_at, in_progress,
                                current_step, completed_at, result}
payload.status.pending_update {is_available}
payload.status.network        {last_seen, name, ip, rssi, uptime, mac}
payload.status.safety         {error, error_codes[], error_descriptions[]}
payload.status.zones[]        measured: {id, temp (°C), thermal_state}
payload.status.sensors.sensor1, sensor2
                              {heart_rate, breath_rate, status, status_text,
                               sign_of_asleep, sign_of_wake_up, timestamp,
                               uptime, is_working, firmware_version,
                               hardware_version}
payload.timeline[]            only on update; today's scheduled actions:
                              {id, user_id, label (bedtime|phase_1|phase_2|
                               wake_up|turn_off), scheduled_time, action:
                               {zones:[...]}, created_at}
```

Notable:
- `payload.zones[].temp` is the **setpoint**. The **measured** zone temperature lives at `payload.status.zones[].temp`.
- `status.zones[].thermal_state` was only observed as `"standby"`; heating/cooling values are plausible but unobserved.
- `sensors.sensor*.status_text` observed values: `"left_bed"` (empty bed, HR=BR=0) and `"normal"` (occupied, realistic HR/BR). The topper also reports HR=BR=255 as a "no reading yet" sentinel in the first ~2s after someone sits down. Other values hinted at by the app strings (e.g. sitting/asleep/error) are plausible but unobserved.
- `sensors.sensor*.sign_of_asleep` / `sign_of_wake_up` only ever observed as `1`; likely edge triggers that momentarily take another value during stage transitions (unconfirmed — a full sleep session hasn't been captured).

### Events NOT Observed (may exist, were not triggered)

- Distinct session-start / session-end events (likely still only available via `/v2/insights` polling)
- Device-offline event (device was online throughout the capture)
- quiet_mode / reboot action responses
- Firmware-update-in-progress transitions
- Water-fill-mode transitions

## Known Issues

- **Unused translations**: `bed_climate_left` and `bed_climate_right` defined in strings.json but no entities use them

## Known Limitations / Future Work

- `set_temperature` endpoint not verified against live API
- Schedule enable/disable (`PUT /v1/sleep-schedules?action=enable`) not verified
- `async_set_hvac_mode(OFF)` turns the zone off immediately; it does not disable the schedule, so the device may turn itself back on at the next scheduled bedtime
- Firmware versions are not exposed as dedicated entities yet (available in the WS payload at `status.firmware.{cb,ib}` and on each sensor block's `firmware_version` — plumb through if surfacing them becomes useful)
- HRV values frequently null in real data
- No way to start/stop sleep sessions via API
- Zone splitting/merging not supported
- Guest user management not supported
- `OrionPowerSwitch` and `OrionScheduleSwitch` don't catch API errors — they propagate to the HA UI as failed-action notifications. `OrionAwayModeSwitch` specifically swallows the `400 "User has no previous device to return to"` that the server returns on a no-op toggle.
- Topper sensor1 ↔ sensor2 to zone_a ↔ zone_b mapping is unverified — entities are named per sensor rather than per side until a split-occupancy capture confirms the mapping
- `/v3/insights` (consistency, sleep debt, breathing disturbances, day/week/month trends) is documented and fetched by the coordinator for both the primary and partner accounts (`data["insights_v3"]` / `data["partner_insights_v3"]`, added 2026-07-16). Consistency (`OrionConsistencySensor`, added 2026-07-16) and breathing disturbances (`OrionBreathingDisturbancesSensor`, added 2026-07-16) both have sensors now; sleep debt still has **no dedicated entity/sensor yet** (only available via the week/month `OrionTrendScoreSensor` summary attributes). See follow-up beads for the remaining scoped sensor implementation work.
- Orion Intelligence temperature recommendations (`response.recommendations.{user_id}` from `/v1/sleep-schedules`, discovered 2026-07-19) has a sensor (`OrionTemperatureRecommendationSensor`), but the item schema inside the array is **unconfirmed** — it was observed empty for every user on the only account probed so far, despite an active subscription and 2.5 months of data. Re-verify the item shape (and whether `is_override_available` on today's schedule entry is related) once a live account with a populated recommendation is available, then tighten `native_value`/`extra_state_attributes` to surface specific fields (e.g. a recommended temp, phase, human-readable insight) instead of just the count + raw list.
- `/v3/insights` partner-account response shape has not been independently observed (would need either an interactive partner OTP login or checking config-entry diagnostics after a live poll) — but it now runs through the identical client/error-handling path already proven for partner `/v2/insights`, so no divergence is expected.
- Device objects from `/v1/devices` include a `capabilities: {sensors: {sleep_tracking, heart_rate, weight_detection}, alarms: {vibration, sound, temperature}, accessories: {blanket}}` block (observed 2026-07-16, now documented in `openapi.yaml`'s `Device` schema). It is **not yet plumbed into the integration** — `sensor.py`/`binary_sensor.py` entity setup (`async_setup_entry`) unconditionally creates the same fixed entity set (heart-rate, breath-rate, etc.) for every device rather than reading `device["capabilities"]` to skip sensors/alarms/accessories a given device doesn't support. Only one device has been observed so its `capabilities` values are all `true`/present — there's no confirmed example of a device with a `false` flag yet, so gating logic can't be verified against real heterogeneous data. Treat this as a follow-up: gate entity creation per-device once a device with a differing capability set is observed.
