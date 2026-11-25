"""Hub health parsing for the Orion live-device payload.

This module reads the hub-health fields out of a live payload (the
WebSocket ``live_device.snapshot``/``live_device.update`` payload, or the
unwrapped ``GET /v1/devices/{serial}/live`` body) and returns plain,
immutable snapshots that entity classes can display without further logic.

It deliberately uses the standard library only and has no relative
imports: the unit tests load this file by path, outside Home Assistant.

Type rules: every helper returns ``None`` for a missing key or a value of
the wrong type. Nothing is defaulted and nothing is clamped.

Privacy: the parser never reads ``status.network.name``, ``.ip`` or
``.mac``, and no field below could carry them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAX_TEXT_LENGTH = 255
RESTART_TOLERANCE_SECONDS = 120.0

PAD_SENSOR_NAMES = ("sensor1", "sensor2")

NO_DETAILS_TEXT = "Problem reported (no details)"
OK_TEXT = "OK"
NO_CODES_TEXT = "none"


# ---------------------------------------------------------------------------
# Type helpers
# ---------------------------------------------------------------------------


def _block(value: Any) -> dict | None:
    """Return ``value`` when it is a dict, otherwise ``None``."""
    return value if isinstance(value, dict) else None


def _sub(parent: dict | None, key: str) -> dict | None:
    """Return ``parent[key]`` when both are dicts, otherwise ``None``."""
    if parent is None:
        return None
    return _block(parent.get(key))


def _get(parent: dict | None, key: str) -> Any:
    return None if parent is None else parent.get(key)


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value[:MAX_TEXT_LENGTH]


def _scalar(value: Any) -> str | int | float | bool | None:
    """Return a scalar value as reported; containers give ``None``."""
    if isinstance(value, (str, int, float, bool)):
        return value
    return None


def _epoch(value: Any) -> datetime | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _list(value: Any) -> list | None:
    return value if isinstance(value, list) else None


def _cut(text: str) -> str:
    return text[:MAX_TEXT_LENGTH]


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PadSensorHealth:
    """Health of one under-mattress pad sensor (``status.sensors.sensorN``)."""

    problem: bool | None = None
    firmware_version: str | None = None
    hardware_version: str | None = None


def _parse_pad_sensor(block: dict | None) -> PadSensorHealth:
    if block is None:
        return PadSensorHealth()
    working = _bool(block.get("is_working"))
    return PadSensorHealth(
        problem=None if working is None else not working,
        firmware_version=_text(block.get("firmware_version")),
        hardware_version=_text(block.get("hardware_version")),
    )


@dataclass(frozen=True)
class HubHealth:
    """Hub-health snapshot parsed from one live payload."""

    online: bool | None = None
    wifi_rssi: int | float | None = None
    uptime_seconds: int | float | None = None
    last_seen: datetime | None = None
    hub_firmware: str | None = None
    panel_firmware: str | None = None
    update_available: bool | None = None
    update_in_progress: bool | None = None
    update_step: str | None = None
    update_result: Any = None
    update_started_at: Any = None
    update_updated_at: Any = None
    update_completed_at: Any = None
    error_codes: list | None = None
    error_descriptions: list | None = None
    problem_text: str | None = None
    error_codes_text: str | None = None
    water_fill: str | None = None
    water_fill_mode: bool | None = None
    led_brightness: int | float | None = None
    sensor1: PadSensorHealth = field(default_factory=PadSensorHealth)
    sensor2: PadSensorHealth = field(default_factory=PadSensorHealth)

    def pad_sensor(self, name: str) -> PadSensorHealth:
        """Return the pad-sensor entry for ``"sensor1"`` or ``"sensor2"``."""
        if name == "sensor1":
            return self.sensor1
        if name == "sensor2":
            return self.sensor2
        return PadSensorHealth()


# ---------------------------------------------------------------------------
# Safety rules
# ---------------------------------------------------------------------------


def _safety_codes(safety: dict) -> list:
    codes = safety.get("error_codes")
    return codes if isinstance(codes, list) else []


def _safety_descriptions(safety: dict) -> list[str]:
    raw = safety.get("error_descriptions")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item is not None and str(item).strip()]


def _problem_present(safety: dict) -> bool:
    """Same test the ``device_problem`` binary sensor has always used."""
    return bool(safety.get("error")) or bool(_safety_codes(safety))


def _problem_text(safety: dict | None) -> str | None:
    if safety is None:
        return None
    codes = _safety_codes(safety)
    descriptions = _safety_descriptions(safety)
    if _problem_present(safety):
        if descriptions:
            return _cut("; ".join(descriptions))
        if codes:
            return _cut(", ".join(str(code) for code in codes))
        return NO_DETAILS_TEXT
    if safety.get("error") is False:
        return OK_TEXT
    return None


def _error_codes_text(safety: dict | None) -> str | None:
    if safety is None:
        return None
    codes = safety.get("error_codes")
    if not isinstance(codes, list):
        return None
    if not codes:
        return NO_CODES_TEXT
    return _cut(", ".join(str(code) for code in codes))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_hub_health(live: Any) -> HubHealth:
    """Parse a live payload into a :class:`HubHealth` snapshot.

    Any input is accepted; a non-dict gives a snapshot with every field
    ``None``.
    """
    root = _block(live)
    if root is None:
        return HubHealth()

    status = _sub(root, "status")
    network = _sub(status, "network")
    firmware = _sub(status, "firmware")
    firmware_update = _sub(status, "firmware_update")
    pending_update = _sub(status, "pending_update")
    safety = _sub(status, "safety")
    sensors = _sub(status, "sensors")

    uptime = _number(_get(network, "uptime"))
    if uptime is not None and uptime < 0:
        uptime = None

    return HubHealth(
        online=_bool(_get(status, "online")),
        wifi_rssi=_number(_get(network, "rssi")),
        uptime_seconds=uptime,
        last_seen=_epoch(_get(network, "last_seen")),
        hub_firmware=_text(_get(firmware, "cb")),
        panel_firmware=_text(_get(firmware, "ib")),
        update_available=_bool(_get(pending_update, "is_available")),
        update_in_progress=_bool(_get(firmware_update, "in_progress")),
        update_step=_text(_get(firmware_update, "current_step")),
        update_result=_scalar(_get(firmware_update, "result")),
        update_started_at=_scalar(_get(firmware_update, "started_at")),
        update_updated_at=_scalar(_get(firmware_update, "updated_at")),
        update_completed_at=_scalar(_get(firmware_update, "completed_at")),
        error_codes=_list(_get(safety, "error_codes")),
        error_descriptions=_list(_get(safety, "error_descriptions")),
        problem_text=_problem_text(safety),
        error_codes_text=_error_codes_text(safety),
        water_fill=_text(root.get("water_fill")),
        water_fill_mode=_bool(root.get("is_in_water_fill_mode")),
        led_brightness=_number(root.get("led_brightness")),
        sensor1=_parse_pad_sensor(_sub(sensors, "sensor1")),
        sensor2=_parse_pad_sensor(_sub(sensors, "sensor2")),
    )


# ---------------------------------------------------------------------------
# Attribute builders
# ---------------------------------------------------------------------------


def _attrs(**values: Any) -> dict | None:
    result = {key: value for key, value in values.items() if value is not None}
    return result or None


def problem_attributes(health: HubHealth) -> dict | None:
    return _attrs(codes=health.error_codes, descriptions=health.error_descriptions)


def error_codes_attributes(health: HubHealth) -> dict | None:
    return _attrs(codes=health.error_codes, descriptions=health.error_descriptions)


def update_in_progress_attributes(health: HubHealth) -> dict | None:
    return _attrs(current_step=health.update_step, result=health.update_result)


def update_step_attributes(health: HubHealth) -> dict | None:
    return _attrs(
        result=health.update_result,
        in_progress=health.update_in_progress,
        started_at=health.update_started_at,
        updated_at=health.update_updated_at,
        completed_at=health.update_completed_at,
    )


def pad_sensor_problem_attributes(pad: PadSensorHealth) -> dict | None:
    return _attrs(
        firmware_version=pad.firmware_version,
        hardware_version=pad.hardware_version,
    )


def pad_sensor_firmware_attributes(pad: PadSensorHealth) -> dict | None:
    return _attrs(hardware_version=pad.hardware_version)


# ---------------------------------------------------------------------------
# device_problem helpers (existing binary sensor, rule unchanged)
# ---------------------------------------------------------------------------


def _raw_safety(live: Any) -> tuple[bool, dict | None]:
    """Return ``(has_payload, safety)`` for the ``device_problem`` rules."""
    if not live or not isinstance(live, dict):
        return False, None
    status = live.get("status")
    status = status if isinstance(status, dict) else {}
    return True, _block(status.get("safety"))


def device_problem_is_on(live: Any) -> bool | None:
    """``device_problem`` state: unchanged from the original entity rule."""
    has_payload, safety = _raw_safety(live)
    if not has_payload:
        return None
    if safety is None:
        return False
    if safety.get("error"):
        return True
    codes = safety.get("error_codes")
    return bool(codes) if isinstance(codes, list) else False


def device_problem_attributes(live: Any) -> dict | None:
    """``device_problem`` attributes: ``error_codes`` plus ``error_descriptions``."""
    _, safety = _raw_safety(live)
    if safety is None:
        return None
    result: dict[str, Any] = {}
    codes = safety.get("error_codes")
    if codes:
        result["error_codes"] = codes
    descriptions = safety.get("error_descriptions")
    if isinstance(descriptions, list) and descriptions:
        result["error_descriptions"] = descriptions
    return result or None


# ---------------------------------------------------------------------------
# Last restart
# ---------------------------------------------------------------------------


class RestartTracker:
    """Derive "last restart" from hub uptime, stable across frames.

    One instance per device. The clock is passed to :meth:`observe`, so the
    tracker never reads the time itself.
    """

    def __init__(self) -> None:
        self.restart_at: float | None = None
        self._last_uptime: float | None = None

    def observe(self, uptime: Any, online: Any, now: float) -> float | None:
        """Feed one new payload's uptime and online flag; return ``restart_at``."""
        if online is False:
            return self.restart_at
        value = _number(uptime)
        if value is None or value < 0:
            return self.restart_at

        candidate = float(math.floor(now - value))
        if (
            self.restart_at is None
            or (self._last_uptime is not None and value < self._last_uptime)
            or abs(candidate - self.restart_at) > RESTART_TOLERANCE_SECONDS
        ):
            self.restart_at = candidate
        self._last_uptime = value
        return self.restart_at
