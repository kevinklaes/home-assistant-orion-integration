"""Fault names and advice (``faults.py``) and how the entities compose them.

Every input is hand-written. None of it comes from a real capture.
"""

from __future__ import annotations

import pytest

WATER_FLOW = (
    "Water isn't flowing",
    "Check the water level and that the hoses aren't kinked.",
)
TEMP_READINGS_NAME = "Temperature readings look unreliable"
TEMP_READINGS_ADVICE = "Restarting the hub may clear it."


def _frame_with_safety(frame, safety):
    if safety is None:
        frame["status"].pop("safety", None)
    else:
        frame["status"]["safety"] = safety
    return frame


def _entities(hh, faults, frame):
    """Compose exactly as sensor.py and binary_sensor.py do."""
    health = hh.parse_hub_health(frame)
    return {
        "error_codes_state": health.error_codes_text,
        "error_codes_attrs": faults.with_fault_names(
            hh.error_codes_attributes(health), health.error_codes
        ),
        "problem_state": faults.problem_state(health.problem_text, health.error_codes),
        "problem_attrs": faults.with_fault_names(
            hh.problem_attributes(health), health.error_codes
        ),
        "device_problem_on": hh.device_problem_is_on(frame),
        "device_problem_attrs": faults.with_error_names(
            hh.device_problem_attributes(frame)
        ),
    }


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------


def test_describe_known_hub_identifier(faults):
    assert faults.describe("PUMP_OFF_TEC_ON") == WATER_FLOW


def test_describe_known_generic_key(faults):
    assert faults.describe("water_flow") == WATER_FLOW


@pytest.mark.parametrize(
    "code",
    ["pump_off_tec_on", "Pump_Off_Tec_On", "Water_Flow", "WATER_FLOW", "  PUMP_OFF_TEC_ON "],
)
def test_describe_ignores_case_and_whitespace(faults, code):
    assert faults.describe(code) == WATER_FLOW


@pytest.mark.parametrize(
    ("code", "side"),
    [
        ("RTEC_FAULT_DETECTED", "right"),
        ("LTEC_FAULT_DETECTED", "left"),
        ("ltec_fault_detected", "left"),
    ],
)
def test_describe_zone_fault_names_its_side(faults, code, side):
    name, advice = faults.describe(code)
    assert "Heating and cooling fault" in name
    assert side in name
    assert advice == faults.FAULTS["zone_fault"][1]


def test_describe_generic_zone_fault_has_no_side(faults):
    assert faults.describe("zone_fault") == faults.FAULTS["zone_fault"]


@pytest.mark.parametrize(
    "code",
    ["E42", "", "   ", None, 17, 3.5, True, [], {}, "right"],
    ids=repr,
)
def test_describe_unknown_or_bad_input(faults, code):
    assert faults.describe(code) is None


def test_every_identifier_and_key_resolves(faults):
    for code, key in faults.FAULT_CODES.items():
        assert faults.describe(code) == faults.FAULTS[key]
    for key, entry in faults.FAULTS.items():
        assert faults.describe(key) == entry
    for code in faults.ZONE_FAULTS:
        assert faults.describe(code) is not None


def test_names_fit_the_state_limit(faults):
    for name, _ in faults.FAULTS.values():
        assert len(name) <= faults.MAX_TEXT_LENGTH
    for code in faults.ZONE_FAULTS:
        assert len(faults.describe(code)[0]) <= faults.MAX_TEXT_LENGTH


# ---------------------------------------------------------------------------
# Names and advice lists
# ---------------------------------------------------------------------------


def test_names_and_advice_mixed(faults):
    codes = ["E42", "ADC_NOT_OK"]
    assert faults.fault_names(codes) == ["E42", TEMP_READINGS_NAME]
    assert faults.fault_advice(codes) == [faults.UNKNOWN_FAULT[1], TEMP_READINGS_ADVICE]


def test_names_numeric_code_stays_raw(faults):
    assert faults.fault_names([17]) == ["17"]
    assert faults.fault_advice([17]) == [faults.UNKNOWN_FAULT[1]]


def test_names_empty_list(faults):
    assert faults.fault_names([]) == []
    assert faults.fault_advice([]) == []


@pytest.mark.parametrize("codes", [None, "X1", 5, {"a": 1}], ids=repr)
def test_names_not_a_list(faults, codes):
    assert faults.fault_names(codes) is None
    assert faults.fault_advice(codes) is None


def test_with_fault_names_key_order(faults):
    attrs = faults.with_fault_names({"codes": ["ADC_NOT_OK"], "descriptions": []}, ["ADC_NOT_OK"])
    assert list(attrs) == ["codes", "descriptions", "names", "advice"]


def test_with_fault_names_does_not_mutate(faults):
    original = {"codes": ["ADC_NOT_OK"]}
    faults.with_fault_names(original, ["ADC_NOT_OK"])
    assert original == {"codes": ["ADC_NOT_OK"]}


def test_with_fault_names_not_a_list_returns_attrs(faults):
    attrs = {"descriptions": ["x"]}
    assert faults.with_fault_names(attrs, "X1") is attrs
    assert faults.with_fault_names(None, None) is None


def test_problem_state_cut_to_limit(faults, monkeypatch):
    monkeypatch.setitem(faults.FAULTS, "water_flow", ("N" * 400, "advice"))
    state = faults.problem_state("whatever", ["PUMP_OFF_TEC_ON"])
    assert state == "N" * faults.MAX_TEXT_LENGTH


@pytest.mark.parametrize("text", ["OK", None, "Problem reported (no details)"], ids=repr)
def test_problem_state_passes_through_without_known_code(faults, text):
    assert faults.problem_state(text, []) == text
    assert faults.problem_state(text, None) == text
    assert faults.problem_state(text, ["E42"]) == text


def test_with_error_names_adds_names(faults):
    attrs = {"error_codes": ["E42", "PUMP_OFF_TEC_ON"], "error_descriptions": ["x"]}
    result = faults.with_error_names(attrs)
    assert result == {
        "error_codes": ["E42", "PUMP_OFF_TEC_ON"],
        "error_descriptions": ["x"],
        "error_names": ["E42", WATER_FLOW[0]],
    }
    assert "error_names" not in attrs


@pytest.mark.parametrize(
    "attrs",
    [None, {"error_codes": "A"}, {"error_descriptions": ["x"]}],
    ids=repr,
)
def test_with_error_names_unchanged(faults, attrs):
    assert faults.with_error_names(attrs) == attrs


# ---------------------------------------------------------------------------
# Example Mapping rows, end to end
# ---------------------------------------------------------------------------


def test_row_known_hub_identifier(hh, faults, frame):
    _frame_with_safety(
        frame, {"error": True, "error_codes": ["PUMP_OFF_TEC_ON"], "error_descriptions": []}
    )
    out = _entities(hh, faults, frame)
    assert out["error_codes_state"] == "PUMP_OFF_TEC_ON"
    assert out["error_codes_attrs"] == {
        "codes": ["PUMP_OFF_TEC_ON"],
        "descriptions": [],
        "names": [WATER_FLOW[0]],
        "advice": [WATER_FLOW[1]],
    }
    assert out["problem_attrs"]["names"] == [WATER_FLOW[0]]
    assert out["problem_attrs"]["advice"] == [WATER_FLOW[1]]
    assert out["problem_state"] == WATER_FLOW[0]
    assert out["device_problem_on"] is True
    assert out["device_problem_attrs"]["error_names"] == [WATER_FLOW[0]]


def test_row_generic_key(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": ["water_flow"]})
    out = _entities(hh, faults, frame)
    assert out["error_codes_attrs"]["names"] == [WATER_FLOW[0]]
    assert out["error_codes_attrs"]["advice"] == [WATER_FLOW[1]]
    assert out["problem_state"] == WATER_FLOW[0]


def test_row_mixed_case(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": ["Pump_Off_Tec_On"]})
    out = _entities(hh, faults, frame)
    assert out["error_codes_state"] == "Pump_Off_Tec_On"
    assert out["error_codes_attrs"]["names"] == [WATER_FLOW[0]]
    assert out["error_codes_attrs"]["advice"] == [WATER_FLOW[1]]


def test_row_zone_fault(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": ["LTEC_FAULT_DETECTED"]})
    out = _entities(hh, faults, frame)
    (name,) = out["error_codes_attrs"]["names"]
    assert "Heating and cooling fault" in name and "left" in name
    assert out["error_codes_attrs"]["advice"] == [faults.FAULTS["zone_fault"][1]]
    assert out["problem_state"] == name


def test_row_unknown_with_description(hh, faults, frame):
    _frame_with_safety(
        frame, {"error": True, "error_codes": ["E42"], "error_descriptions": ["Pump stalled"]}
    )
    out = _entities(hh, faults, frame)
    assert out["error_codes_attrs"]["names"] == ["E42"]
    assert out["error_codes_attrs"]["advice"] == [faults.UNKNOWN_FAULT[1]]
    assert out["problem_state"] == "Pump stalled"


def test_row_unknown_without_description(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": ["E42"], "error_descriptions": []})
    out = _entities(hh, faults, frame)
    assert out["error_codes_attrs"]["names"] == ["E42"]
    assert out["problem_state"] == "E42"
    assert out["device_problem_attrs"]["error_names"] == ["E42"]


def test_row_mixed_known_unknown_no_description(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": ["E42", "ADC_NOT_OK"]})
    out = _entities(hh, faults, frame)
    assert out["error_codes_attrs"]["names"] == ["E42", TEMP_READINGS_NAME]
    assert out["problem_attrs"]["names"] == ["E42", TEMP_READINGS_NAME]
    assert out["problem_state"] == TEMP_READINGS_NAME


def test_known_name_beats_description(hh, faults, frame):
    _frame_with_safety(
        frame,
        {"error": True, "error_codes": ["E42", "ADC_NOT_OK"], "error_descriptions": ["Pump stalled"]},
    )
    out = _entities(hh, faults, frame)
    assert out["problem_state"] == TEMP_READINGS_NAME


def test_error_with_no_details(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": [], "error_descriptions": []})
    out = _entities(hh, faults, frame)
    assert out["problem_state"] == "Problem reported (no details)"
    assert out["error_codes_attrs"]["names"] == []
    assert out["error_codes_attrs"]["advice"] == []
    assert out["device_problem_on"] is True
    assert out["device_problem_attrs"] is None


def test_row_empty_list(hh, faults, frame):
    out = _entities(hh, faults, frame)
    assert out["error_codes_state"] == "none"
    assert out["error_codes_attrs"]["names"] == []
    assert out["error_codes_attrs"]["advice"] == []
    assert out["problem_state"] == "OK"
    assert out["device_problem_on"] is False
    assert out["device_problem_attrs"] is None
    assert faults.with_error_names(None) is None


def test_row_no_safety_block(hh, faults, frame):
    _frame_with_safety(frame, None)
    out = _entities(hh, faults, frame)
    assert out["problem_state"] is None
    assert out["error_codes_state"] is None
    assert out["error_codes_attrs"] is None
    assert out["problem_attrs"] is None
    assert out["device_problem_attrs"] is None


def test_error_codes_not_a_list(hh, faults, frame):
    _frame_with_safety(frame, {"error": True, "error_codes": "X1", "error_descriptions": ["d"]})
    out = _entities(hh, faults, frame)
    assert "names" not in out["error_codes_attrs"]
    assert "advice" not in out["error_codes_attrs"]
    assert "names" not in out["problem_attrs"]
    assert out["device_problem_attrs"] == {"error_codes": "X1", "error_descriptions": ["d"]}
