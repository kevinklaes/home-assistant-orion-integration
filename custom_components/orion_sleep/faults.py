# Fault identifiers, names and advice adapted from Ember & Tide (https://github.com/Ncbudd/ember-tide).
# Licensed under the PolyForm Noncommercial License 1.0.0: https://polyformproject.org/licenses/noncommercial/1.0.0
# Required Notice: Copyright (c) 2026 Ncbudd (https://github.com/Ncbudd/ember-tide)
"""Plain-language names and advice for the hub's safety codes.

The identifiers come from the hub firmware's *local* protocol. It is not
live-verified that the cloud's ``status.safety.error_codes`` uses them; any
code not listed here is shown raw, so nothing is hidden if it does not.

Standard library only, with no relative imports: the tests load this file by
path, without Home Assistant. Every function here is pure and never raises.
"""

from __future__ import annotations

from typing import Any

# Hub identifier -> generic key.
FAULT_CODES: dict[str, str] = {
    "PUMP_OFF_TEC_ON": "water_flow",
    "FAN_OFF_TEC_ON": "fan_stopped",
    "PUMP_CURRENT": "pump",
    "FAN_RPM_OUT_OF_RANGE": "fan_speed",
    "NTC_MIN_TEMP_CUTOFF": "pad_cold_limit",
    "NTC_MAX_TEMP_CUTOFF": "pad_hot_limit",
    "CB_MAX_TEMP_CUTOFF": "hub_hot",
    "ANGLE_Z_OUT_OF_RANGE": "not_level",
    "NO_IB_VERSION": "panel_link",
    "IB_COMM_NOT_OK": "panel_link",
    "FLASH_NOT_OK": "memory",
    "ACCEL_NOT_OK": "tilt_sensor",
    "ADC_NOT_OK": "temp_readings",
    "AMBIENT_SENSOR_NOT_OK": "room_sensor",
    "MANUAL_ERROR_COMMAND": "manual_error",
    "PTC_FAULT_DETECTED": "power",
}

# Zone fault identifier -> the hub's own side word (not mapped to zone_a/zone_b).
ZONE_FAULTS: dict[str, str] = {
    "RTEC_FAULT_DETECTED": "right",
    "LTEC_FAULT_DETECTED": "left",
}
ZONE_FAULT_KEY = "zone_fault"

# Generic key -> (name, advice).
FAULTS: dict[str, tuple[str, str]] = {
    "water_flow": ("Water isn't flowing", "Check the water level and that the hoses aren't kinked."),
    "pump": ("Water pump is straining", "Check the water level and that the hoses aren't kinked."),
    "fan_stopped": ("Fan isn't running", "Check the hub's vents aren't blocked."),
    "fan_speed": ("Fan speed out of range", "Check the hub's vents aren't blocked."),
    "pad_cold_limit": (
        "Pad reached its low limit",
        "It protects itself and should carry on by itself. If it keeps happening, restart the hub.",
    ),
    "pad_hot_limit": (
        "Pad reached its high limit",
        "It cooled itself down. If it doesn't carry on, restart the hub.",
    ),
    "hub_hot": ("Hub is running hot", "Check the vents are clear and there's some space around the hub."),
    "not_level": ("Hub isn't level", "Check the hub is upright and on a flat surface."),
    "panel_link": ("Light panel isn't answering", "Restarting the hub may clear it."),
    "memory": ("Hub memory check failed", "Restart the hub. If it comes back, contact the maker."),
    "tilt_sensor": ("Tilt sensor isn't answering", "Restarting the hub may clear it."),
    "temp_readings": ("Temperature readings look unreliable", "Restarting the hub may clear it."),
    "room_sensor": (
        "Room sensor isn't answering",
        "Room humidity may be missing. Restarting the hub may clear it.",
    ),
    "manual_error": ("Hub was put in an error state", "Restart the hub to clear it."),
    "power": (
        "Power protection reported a fault",
        "Switch the bed off and on at the wall. If it comes back, contact the maker.",
    ),
    "zone_fault": ("Heating and cooling fault", "Restart the hub. If it comes back, contact the maker."),
}
UNKNOWN_FAULT: tuple[str, str] = (
    "The hub reported a problem",
    "Restart the hub. If it comes back, contact the maker.",
)

MAX_TEXT_LENGTH = 255


def describe(code: Any) -> tuple[str, str] | None:
    """``(name, advice)`` for a hub identifier or generic key; ``None`` otherwise.

    Matching ignores letter case and surrounding whitespace.
    """
    if not isinstance(code, str):
        return None
    text = code.strip()
    if not text:
        return None
    upper, lower = text.upper(), text.lower()
    if upper in ZONE_FAULTS:
        name, advice = FAULTS[ZONE_FAULT_KEY]
        return f"{name} ({ZONE_FAULTS[upper]} side)", advice
    key = FAULT_CODES.get(upper, lower)
    return FAULTS.get(key)


def fault_names(codes: Any) -> list[str] | None:
    """One name per code, in order; an unknown code stays as ``str(code)``."""
    if not isinstance(codes, list):
        return None
    names = []
    for code in codes:
        found = describe(code)
        names.append(found[0] if found else str(code))
    return names


def fault_advice(codes: Any) -> list[str] | None:
    """One piece of advice per code, in order; unknown codes get the generic advice."""
    if not isinstance(codes, list):
        return None
    advice = []
    for code in codes:
        found = describe(code)
        advice.append(found[1] if found else UNKNOWN_FAULT[1])
    return advice


def with_fault_names(attrs: dict | None, codes: Any) -> dict | None:
    """``attrs`` plus ``names`` and ``advice`` when ``codes`` is a list; else ``attrs`` as given."""
    if not isinstance(codes, list):
        return attrs
    return {
        **(attrs if isinstance(attrs, dict) else {}),
        "names": fault_names(codes),
        "advice": fault_advice(codes),
    }


def problem_state(problem_text: str | None, codes: Any) -> str | None:
    """The first known fault name among ``codes`` (cut to 255); else ``problem_text``.

    A non-empty code list always means a problem is present, so
    ``problem_text`` is then Orion's descriptions, the raw codes or the
    no-details text; ``OK`` and ``None`` only pass through with no known code.
    """
    if isinstance(codes, list):
        for code in codes:
            found = describe(code)
            if found:
                return found[0][:MAX_TEXT_LENGTH]
    return problem_text


def with_error_names(attrs: dict | None) -> dict | None:
    """``device_problem`` attributes plus ``error_names`` when ``error_codes`` is a list."""
    if not isinstance(attrs, dict):
        return attrs
    codes = attrs.get("error_codes")
    if not isinstance(codes, list):
        return attrs
    return {**attrs, "error_names": fault_names(codes)}
