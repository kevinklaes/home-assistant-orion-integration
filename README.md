# Orion Sleep - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Custom [Home Assistant](https://www.home-assistant.io/) integration for the **Orion Sleep** smart mattress topper. Control bed temperature, react to occupancy in real time, monitor sleep metrics, and manage sleep schedules — all from your Home Assistant dashboard.

> This is a fork of [tdickman/home-assistant-orion-integration](https://github.com/tdickman/home-assistant-orion-integration), maintained here with additional changes.

## Features

- **Live WebSocket stream** — Temperature, power, and sensor readings update in realtime when the bed or the Orion app changes anything; no need to wait for the next poll.
- **Bed occupancy** — Per-topper-sensor binary sensors track who is on the bed. Latency varies; expect ~30 s to 1 minute after sitting down or leaving before the sensor flips (the topper itself is slow to decide).
- **Live heart rate and breath rate** — Per-sensor realtime readings from the topper (distinct from the post-session averages).
- **Climate control** — Target bed temperature per-zone, with the current measured temperature pulled from the latest session.
- **Power and presence switches** — One-click power via the canonical `/v1/devices/{serial}/live` endpoint, plus an Away Mode switch that reads the authoritative presence signal from `zones[*].user`.
- **Sleep insight sensors** — Per-side sleep score and HRV (left / right), plus heart rate, breath rate, sleep-stage durations (awake / light / deep / REM), total time asleep, restless time, and body-movement rate for your most recent session.
- **Schedule sensors and sliders** — Today's bedtime, wake-up time, duration, and target temperatures, plus Number sliders for adjusting the four schedule-phase temperature offsets (-10 … +10, app-style).
- **Session tracking** — Binary sensor showing whether a sleep session is currently in progress.
- **Diagnostic entity** — Live-connection state sensor (`connecting` / `connected` / `reconnecting` / `device_offline` / `auth_failed`), with the seconds-since-last-frame exposed as an attribute.
- **Passwordless auth with automatic refresh** — Sign in with email or phone + verification code (same flow as the Orion app), **or paste a long-lived API key** from [app.orionsleep.com/api-keys](https://app.orionsleep.com/api-keys) for headless setups. OTP tokens refresh automatically; API keys have no refresh — generate a new key if one is revoked.
- **Redacted diagnostics** — `Download diagnostics` produces a debug bundle with tokens, identifiers, and network PII stripped.

## Installation

### HACS (Recommended)

1. Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.

2. Click the button below to add this repository:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kevinklaes&repository=home-assistant-orion-integration&category=integration)

   Or manually add the custom repository: go to **HACS > Integrations > three-dot menu > Custom repositories**, paste `https://github.com/kevinklaes/home-assistant-orion-integration` and select **Integration** as the category.

3. Search for "Orion Sleep" in HACS and download it.

4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/orion_sleep` directory into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration

After installation, add the integration:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=orion_sleep)

Or go to **Settings > Devices & Services > Add Integration** and search for "Orion Sleep".

### Setup steps

1. Choose whether to sign in with **email**, **phone**, or **API key**.
2. **Email / phone:** enter your Orion Sleep account address. A verification code is sent the same way as in the Orion app, then enter the code to finish.
3. **API key:** paste a key generated at [app.orionsleep.com/api-keys](https://app.orionsleep.com/api-keys). No verification code is needed. If re-authenticating, create a fresh key first — revoked keys fail validation.

### Options

After setup, you can configure:

| Option | Default | Description |
|---|---|---|
| Polling interval | 600 s (10 min) | How often to fetch data from the Orion REST API (60 – 3600 s). The WebSocket stream runs continuously and is independent of this interval. |
| Insights days | 7 | Number of days of sleep history to retrieve (1 – 30) |

Go to **Settings > Devices & Services > Orion Sleep > Configure** to change these.

## Real-time updates

In addition to the REST poll, the integration opens one WebSocket per device to `wss://live.api1.orionbed.com/device/<serial_number>` and merges every `live_device.snapshot` / `live_device.update` frame into the coordinator state. This means:

- The Power switch and Bed Climate reflect app-side changes in realtime.
- Per-sensor vitals (heart rate, breath rate) update continuously while occupied.
- Occupancy binary sensors follow the topper's own classification, which can take ~30 s to 1 minute to decide someone has sat down or left. The underlying vitals still update in realtime.
- The integration will gracefully reconnect with exponential backoff if the stream drops, and automatically refresh the JWT before reconnecting on 401.

The live connection is fully automatic — there is no option to disable it today. Its health is exposed by the **Live Connection** diagnostic sensor per device.

## Entities

One device is created per paired topper. Each device exposes the entities listed below. Entity names below use the integration's default translation strings.

### Climate

| Entity | Description |
|---|---|
| Bed Climate | Target temperature read from today's schedule, current temperature from the latest session's most-recent sample. HVAC mode reflects whether a session is in progress. |

### Switches

| Entity | Description |
|---|---|
| Power | All zones on/off via `PUT /v1/devices/{serial}/live`. State derived from each zone's `on` field. |
| Away Mode | Marks you present/away via `POST /v1/sleep-configurations/user-away`. State derived from whether any zone carries a populated `user` object (the authoritative presence signal). |
| Sleep Schedule | Enable/disable today's bedtime action via `PUT /v1/sleep-schedules`. |
| Partner Away Mode | Same as Away Mode but for the linked partner account. State read from the partner account's own device view. Only present when a partner is configured. |
| Partner Sleep Schedule | Enable/disable the partner's own schedule via the partner API client. Only present when a partner is configured. |

### Numbers (temperature-offset sliders)

App-style offsets (-10 to +10) that map non-linearly to Celsius using the device's `temperature_scale.relative` lookup table. Each slider writes back to today's schedule.

- Bedtime Temperature Offset
- Asleep Phase 1 Offset
- Asleep Phase 2 Offset
- Wake Up Temperature Offset

When a partner (second-side) account is linked, the same four sliders are exposed a second time with a `Partner` prefix. Each writes to the partner's own schedule through the partner API client, so both sides control their phase temperatures independently.

### Sensors — sleep insights (latest completed session)

| Entity | Unit | Source |
|---|---|---|
| Sleep Score Left / Right | points | per-side `score` from that zone's latest session, with a `quality_rating` attribute (Excellent / Good / Fair / Poor) |
| Total Sleep Time | formatted `Xh Ym` | `sleep_summary.time_asleep` |
| Deep Sleep | formatted `Xh Ym` | `sleep_summary.deep_sleep` |
| REM Sleep | formatted `Xh Ym` | `sleep_summary.rem_sleep` |
| Light Sleep | formatted `Xh Ym` | `sleep_summary.light_sleep` |
| Awake Time | formatted `Xh Ym` | `sleep_summary.awake_time` |
| Heart Rate | bpm | `heart_rate.average` plus `min` / `max` / `range` attributes |
| Breath Rate | breaths/min | `breath_rate.average` plus `min` / `max` / `range` attributes |
| HRV Left / Right | ms | per-side `hrv.average` from that zone's latest session (often null in real data) |
| Body Movement Rate | /hr | `movement.movement_rate` |
| Restless Time | formatted `Xm Ys` | `movement.total_seconds` |
| Breathing Disturbances | sec | `/v3/insights` `metrics.breathing_disturbances.value`, with `insight`, `low_seconds` / `high_seconds`, `state`, and (cross-checked from the matching `/v2/insights` session) `ahi` attributes |

When a partner (second-side) account is linked, the account-level insight sensors (Total/Deep/REM/Light Sleep, Awake, Heart Rate, Breath Rate, Body Movement, Restless, Breathing Disturbances), the Current Temperature Offset sensor, and the Sleep Session binary sensor are all exposed a second time with a `Partner` prefix, sourced from the partner's own latest session. (Sleep Score and HRV are already per-side.)

### Sensors — sleep trends (`/v3/insights`, day granularity)

| Entity | Unit | Source |
|---|---|---|
| Consistency | % | `metrics.consistency.value` from the day granularity's latest period, with an `insight` attribute plus `vs_prior_day` / `vs_prior_week` / `vs_prior_month` trend-comparison attributes |
| Sleep Debt | min | `metrics.sleep_debt.value` (accumulated sleep shortfall) from the day granularity's latest period, with `need` (computed sleep-need baseline, minutes), `status` (`balanced`/`low`), `insight`, and the same trend-comparison attributes |

These sensors read unknown when the account has no active subscription or the metric's `state` is `empty` (no data for the period). When a partner (second-side) account is linked, Partner Consistency and Partner Sleep Debt sensors are exposed too, sourced from the partner's own `/v3/insights` data.

### Sensors — trends (calendar/trends view, week/month granularity)

`/v3/insights` also returns pre-aggregated week- and month-granularity trend data — the source for the app's calendar/trends view. Rather than add 8 metric entities per granularity, each period's overview score is one sensor with the full metric breakdown as attributes.

| Entity | Unit | Source |
|---|---|---|
| Weekly Sleep Score | points | latest week period's `overview.score`, with `rating` / `color` / `award` / `state` / `start_date` / `end_date` / `days_with_data` plus one attribute per metric (`sleep_duration`, `body_movements`, `breathing_disturbances`, `consistency`, `sleep_debt`, `hrv`, `heart_rate`, `breath_rate`) — each `{value, unit, insight, comparison}`, comparison being that metric's `vs_prior_week` |
| Monthly Sleep Score | points | same as above from the latest month period, comparison being `vs_prior_month` |

When a partner (second-side) account is linked, both trend sensors are exposed again with a `Partner` prefix, sourced from the partner's own `/v3/insights` data.

### Sensors — today's schedule

- Bedtime (HH:mm)
- Wake Up Time (HH:mm)
- Schedule Duration (formatted, handles overnight)
- Bedtime Temperature (°C) with phase-1 / phase-2 temp and smart-temperature attributes
- Wake Up Temperature (°C)

When a partner (second-side) account is linked, these five schedule read-outs are exposed again with a `Partner` prefix, reading from the partner's own schedule. They pair with the partner temperature-phase sliders above.
- Current Temperature Offset (app-style -10 … +10, computed from the latest session sample via the per-device non-linear lookup table)

### Sensors — live (WebSocket-driven)

Two in-topper sensors (`sensor1`, `sensor2`) report continuously while the device is online. The mapping between these and the physical left / right side of the bed has not been verified, so entities are named per sensor.

| Entity | Unit | Source |
|---|---|---|
| Sensor 1 Heart Rate | bpm | `status.sensors.sensor1.heart_rate` |
| Sensor 2 Heart Rate | bpm | `status.sensors.sensor2.heart_rate` |
| Sensor 1 Breath Rate | br/min | `status.sensors.sensor1.breath_rate` |
| Sensor 2 Breath Rate | br/min | `status.sensors.sensor2.breath_rate` |

The raw `status_text`, `is_working`, `firmware_version`, and `hardware_version` from each sensor are exposed as extra state attributes on the heart-rate and breath-rate entities. A reading of `0` (empty bed) or `255` (no reading yet) is reported as `unknown` — both are server-side sentinels, not real vitals.

### Sensors — diagnostic

| Entity | Source |
|---|---|
| Live Connection | WebSocket state: `stopped` / `connecting` / `connected` / `reconnecting` / `device_offline` / `auth_failed`, with `seconds_since_last_message` as an attribute. |
| Sensor 1 Status | Raw `status_text` from topper sensor 1 (observed values: `left_bed`, `normal`). |
| Sensor 2 Status | Raw `status_text` from topper sensor 2. |
| Wi-Fi Signal | Hub Wi-Fi signal strength in dBm (`status.network.rssi`). |
| Last Restart | Timestamp of the hub's last restart, worked out from `status.network.uptime` (treated as seconds since boot). Kept steady while uptime ticks normally; moves when uptime goes backwards or the derived time shifts by more than 120 s. Starts as unknown after a Home Assistant restart until the hub reports in while online. |
| Last Seen | Timestamp of the hub's last contact with the cloud (`status.network.last_seen`). **Disabled by default** because it changes every couple of seconds. |
| Hub Firmware | Control-board firmware version (`status.firmware.cb`), as reported. |
| Panel Firmware | Panel (interface) board firmware version (`status.firmware.ib`), as reported. |
| Firmware Update Step | Raw `status.firmware_update.current_step` (only `complete` observed so far), with `result`, `in_progress`, `started_at`, `updated_at` and `completed_at` attributes. The timestamps are passed through unconverted because their unit is not confirmed. |
| Problem | Plain-text summary of `status.safety`: `OK` when no error is reported. When a problem is reported: the name of the first code that has a known [fault name](#fault-names); otherwise Orion's own error descriptions, or the raw codes, or `Problem reported (no details)`. `codes`, `descriptions`, `names` and `advice` attributes. Unknown when the payload has no safety block. |
| Error Codes | Raw `status.safety.error_codes`, comma-separated, exactly as reported (`none` when the list is empty), with `codes` and `descriptions` attributes. The state stays the raw codes; `names` and `advice` attributes give one entry per code, in order (see [Fault names](#fault-names)). |
| Water Fill | Raw `water_fill` value (only `unknown` observed so far). |
| LED Brightness | Front-panel LED brightness in % (`led_brightness`). Read-only. |
| Sensor 1 Firmware | `status.sensors.sensor1.firmware_version`, with `hardware_version` as an attribute. |
| Sensor 2 Firmware | Same for topper sensor 2. |

All of these are diagnostic entities read from the live device payload (WebSocket, or the `GET /live` fallback each poll when the WebSocket is down). A missing or malformed field shows as `unknown`, never as a made-up default. The hub's Wi-Fi network name, IP address and MAC address are never exposed in any entity or attribute.

### Binary sensors

| Entity | Device class | Description |
|---|---|---|
| Sleep Session | — | `insights.session.is_in_progress`. Rendered as "Asleep" / "Not asleep". |
| Sensor 1 On Bed | Occupancy | `sensor1.status_text != "left_bed"`. Driven by the topper's own classification, which can take ~30 s to 1 minute to react to someone sitting down or leaving. |
| Sensor 2 On Bed | Occupancy | `sensor2.status_text != "left_bed"`. Same latency caveat as sensor 1. |
| Problem | Problem | Diagnostic. On when `status.safety.error` is set or `error_codes` is non-empty. `error_codes` attribute when present, `error_descriptions` attribute when non-empty, and `error_names` (one [fault name](#fault-names) per code, unknown codes as sent) when `error_codes` is a list. |
| Hub Online | Connectivity | Diagnostic. `status.online`: whether the cloud can currently reach the hub. |
| Firmware Update Available | Update | Diagnostic, read-only. `status.pending_update.is_available`. The API gives only this flag, with no version to compare against, so it is a binary sensor rather than an `update` entity, and the integration does not start updates. |
| Firmware Update In Progress | Running | Diagnostic. `status.firmware_update.in_progress`, with `current_step` and `result` attributes. |
| Water Fill Mode | — | Diagnostic. `is_in_water_fill_mode`. |
| Sensor 1 Problem | Problem | Diagnostic. On when topper sensor 1 reports `is_working: false`, off when `true`. `firmware_version` and `hardware_version` attributes. |
| Sensor 2 Problem | Problem | Same for topper sensor 2. |

### Fault names

The Error Codes and Problem sensors and the Problem binary sensor turn known hub fault identifiers into a plain name and a piece of advice:

| Code | Name | Advice |
|---|---|---|
| `PUMP_OFF_TEC_ON` | Water isn't flowing | Check the water level and that the hoses aren't kinked. |
| `FAN_OFF_TEC_ON` | Fan isn't running | Check the hub's vents aren't blocked. |
| `PUMP_CURRENT` | Water pump is straining | Check the water level and that the hoses aren't kinked. |
| `FAN_RPM_OUT_OF_RANGE` | Fan speed out of range | Check the hub's vents aren't blocked. |
| `NTC_MIN_TEMP_CUTOFF` | Pad reached its low limit | It protects itself and should carry on by itself. If it keeps happening, restart the hub. |
| `NTC_MAX_TEMP_CUTOFF` | Pad reached its high limit | It cooled itself down. If it doesn't carry on, restart the hub. |
| `CB_MAX_TEMP_CUTOFF` | Hub is running hot | Check the vents are clear and there's some space around the hub. |
| `ANGLE_Z_OUT_OF_RANGE` | Hub isn't level | Check the hub is upright and on a flat surface. |
| `NO_IB_VERSION` | Light panel isn't answering | Restarting the hub may clear it. |
| `IB_COMM_NOT_OK` | Light panel isn't answering | Restarting the hub may clear it. |
| `FLASH_NOT_OK` | Hub memory check failed | Restart the hub. If it comes back, contact the maker. |
| `ACCEL_NOT_OK` | Tilt sensor isn't answering | Restarting the hub may clear it. |
| `ADC_NOT_OK` | Temperature readings look unreliable | Restarting the hub may clear it. |
| `AMBIENT_SENSOR_NOT_OK` | Room sensor isn't answering | Room humidity may be missing. Restarting the hub may clear it. |
| `MANUAL_ERROR_COMMAND` | Hub was put in an error state | Restart the hub to clear it. |
| `PTC_FAULT_DETECTED` | Power protection reported a fault | Switch the bed off and on at the wall. If it comes back, contact the maker. |
| `RTEC_FAULT_DETECTED` | Heating and cooling fault (right side) | Restart the hub. If it comes back, contact the maker. |
| `LTEC_FAULT_DETECTED` | Heating and cooling fault (left side) | Restart the hub. If it comes back, contact the maker. |

- The generic keys behind these names (for example `water_flow`, `zone_fault`) also match, and matching ignores letter case and surrounding spaces.
- A code that is not in the table is shown raw, as sent, with the generic advice "Restart the hub. If it comes back, contact the maker."
- The left/right side is the hub's own wording; it is not mapped to `zone_a`/`zone_b`.
- **Not live-verified.** These identifiers come from the hub's local protocol. The cloud's `status.safety.error_codes` has never been seen non-empty, so it is not confirmed that the cloud sends the same identifiers.
- The names and advice are adapted from [Ember & Tide](https://github.com/Ncbudd/ember-tide) under the PolyForm Noncommercial License 1.0.0; see [`NOTICE`](NOTICE).

## Troubleshooting

- **Re-authentication** — If both the access and refresh tokens expire or are revoked, Home Assistant will raise a re-auth flow; follow the prompts to receive and enter a new verification code.
- **Away Mode switch** — If you toggle Away Mode and the Orion app shows you in Home mode (or vice-versa), the device was probably in an already-matching state. The integration swallows the specific `400 "User has no previous device to return to"` error that the server returns on a redundant toggle and simply logs it at `debug`.
- **Live Connection stuck on `reconnecting`** — Typically indicates a network problem reaching `live.api1.orionbed.com`. The client falls back to REST polling so the rest of the integration keeps working; restart HA or check your outbound HTTPS / WSS connectivity.
- **Logs** — Go to **Settings > System > Logs** and filter for `orion_sleep`. For more detail, add this to `configuration.yaml`:

  ```yaml
  logger:
    default: warning
    logs:
      custom_components.orion_sleep: debug
  ```

- **Diagnostics** — Use **Settings > Devices & Services > Orion Sleep > three-dot menu > Download diagnostics** to generate a debug bundle. Access tokens, refresh tokens, user identifiers, names, serial numbers, IP and MAC addresses are automatically redacted.

## Notes and limitations

- Writing to `PUT /v1/sleep-configurations/temperature` has not been verified against the live API; climate `set_temperature` and the Number sliders use `PUT /v1/sleep-schedules` instead, which is confirmed.
- Home Assistant's climate `async_turn_off` / `async_set_hvac_mode(OFF)` are no-ops for Bed Climate — the underlying system is schedule-driven. Use the **Power** switch to actually turn the device off.
- HRV values are frequently `null` in real data; the HRV Left / Right sensors will then report as `unknown`.
- Per-side sleep score and HRV depend on the API returning a session for each occupied zone; a side with no recent session (e.g. an empty side of the bed) reports as `unknown`.
- Starting and stopping sleep sessions is not supported by the API.
- Zone splitting / merging and guest-user management are not exposed.

## License

`custom_components/orion_sleep/faults.py` contains fault names and advice adapted from [Ember & Tide](https://github.com/Ncbudd/ember-tide) and is under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0); see [`NOTICE`](NOTICE) for the Required Notice.

This project is not affiliated with or endorsed by Orion Longevity Inc.
