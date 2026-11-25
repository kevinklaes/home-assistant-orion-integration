"""parse_hub_health, safety rules, attribute builders and device_problem."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from conftest import FAKE_IP, FAKE_MAC, FAKE_NETWORK_NAME


def _all_builders(hh, health):
    return [
        hh.problem_attributes(health),
        hh.error_codes_attributes(health),
        hh.update_in_progress_attributes(health),
        hh.update_step_attributes(health),
        hh.pad_sensor_problem_attributes(health.sensor1),
        hh.pad_sensor_problem_attributes(health.sensor2),
        hh.pad_sensor_firmware_attributes(health.sensor1),
        hh.pad_sensor_firmware_attributes(health.sensor2),
    ]


# --- Example Mapping rows -------------------------------------------------


def test_healthy_frame(hh, frame):
    health = hh.parse_hub_health(frame)
    assert health.online is True
    assert health.wifi_rssi == -58
    assert health.uptime_seconds == 3600
    assert health.last_seen == datetime.fromtimestamp(1700000500, tz=timezone.utc)
    assert health.hub_firmware == "2.6.0"
    assert health.panel_firmware == "2.5.0"
    assert health.update_available is False
    assert health.update_in_progress is False
    assert health.update_step == "complete"
    assert health.update_result == "success"
    assert health.update_started_at == 1700000000
    assert health.update_updated_at == 1700000100
    assert health.update_completed_at == 1700000200
    assert health.problem_text == "OK"
    assert health.error_codes_text == "none"
    assert health.error_codes == []
    assert health.error_descriptions == []
    assert health.led_brightness == 0
    assert health.water_fill == "unknown"
    assert health.water_fill_mode is False
    assert health.pad_sensor("sensor1").problem is False
    assert health.pad_sensor("sensor2").problem is False
    assert health.pad_sensor("sensor1").firmware_version == "1.0.0-test"
    assert health.pad_sensor("sensor2").firmware_version == "1.0.1-test"
    assert hh.device_problem_is_on(frame) is False


def test_healthy_frame_attributes(hh, frame):
    health = hh.parse_hub_health(frame)
    assert hh.problem_attributes(health) == {"codes": [], "descriptions": []}
    assert hh.error_codes_attributes(health) == {"codes": [], "descriptions": []}
    assert hh.update_in_progress_attributes(health) == {
        "current_step": "complete",
        "result": "success",
    }
    assert hh.update_step_attributes(health) == {
        "result": "success",
        "in_progress": False,
        "started_at": 1700000000,
        "updated_at": 1700000100,
        "completed_at": 1700000200,
    }
    assert hh.pad_sensor_problem_attributes(health.sensor1) == {
        "firmware_version": "1.0.0-test",
        "hardware_version": "1.0-test",
    }
    assert hh.pad_sensor_firmware_attributes(health.sensor2) == {
        "hardware_version": "1.0-test"
    }
    assert hh.device_problem_attributes(frame) is None


def test_hub_offline(hh, frame):
    frame["status"]["online"] = False
    health = hh.parse_hub_health(frame)
    assert health.online is False
    # Other fields are still read as reported.
    assert health.hub_firmware == "2.6.0"


@pytest.mark.parametrize("live", [None, {}, [], "text", 0])
def test_no_payload_all_none(hh, live):
    health = hh.parse_hub_health(live)
    for f in dataclasses.fields(health):
        value = getattr(health, f.name)
        if f.name in ("sensor1", "sensor2"):
            assert value == hh.PadSensorHealth()
            assert value.problem is None
            assert value.firmware_version is None
            assert value.hardware_version is None
        else:
            assert value is None, f.name
    assert health.pad_sensor("sensor1") == hh.PadSensorHealth()
    for attrs in _all_builders(hh, health):
        assert attrs is None
    assert hh.device_problem_is_on(live) is None
    assert hh.device_problem_attributes(live) is None


def test_missing_network_block(hh, frame):
    del frame["status"]["network"]
    health = hh.parse_hub_health(frame)
    assert health.wifi_rssi is None
    assert health.uptime_seconds is None
    assert health.last_seen is None
    tracker = hh.RestartTracker()
    assert tracker.observe(health.uptime_seconds, health.online, 1_700_000_000) is None
    # Other entities unaffected.
    assert health.online is True
    assert health.hub_firmware == "2.6.0"
    assert health.problem_text == "OK"
    assert health.sensor1.problem is False


def test_fault_with_details(hh, frame):
    frame["status"]["safety"] = {
        "error": True,
        "error_codes": ["X1", "X2"],
        "error_descriptions": ["First thing", "Second thing"],
    }
    health = hh.parse_hub_health(frame)
    assert health.problem_text == "First thing; Second thing"
    assert health.error_codes_text == "X1, X2"
    expected = {"codes": ["X1", "X2"], "descriptions": ["First thing", "Second thing"]}
    assert hh.error_codes_attributes(health) == expected
    assert hh.problem_attributes(health) == expected
    assert hh.device_problem_is_on(frame) is True
    assert hh.device_problem_attributes(frame) == {
        "error_codes": ["X1", "X2"],
        "error_descriptions": ["First thing", "Second thing"],
    }


def test_fault_codes_only(hh, frame):
    frame["status"]["safety"] = {
        "error": True,
        "error_codes": ["X1"],
        "error_descriptions": [],
    }
    health = hh.parse_hub_health(frame)
    assert health.problem_text == "X1"
    assert health.error_codes_text == "X1"
    assert hh.device_problem_attributes(frame) == {"error_codes": ["X1"]}


def test_fault_codes_only_blank_descriptions_ignored(hh, frame):
    frame["status"]["safety"] = {
        "error": True,
        "error_codes": ["X1", "X2"],
        "error_descriptions": ["", "   ", None],
    }
    assert hh.parse_hub_health(frame).problem_text == "X1, X2"


def test_fault_no_details(hh, frame):
    frame["status"]["safety"] = {
        "error": True,
        "error_codes": [],
        "error_descriptions": [],
    }
    health = hh.parse_hub_health(frame)
    assert health.problem_text == "Problem reported (no details)"
    assert health.error_codes_text == "none"
    assert hh.device_problem_is_on(frame) is True


def test_codes_without_error_flag_is_problem(hh, frame):
    frame["status"]["safety"] = {"error": False, "error_codes": ["X9"]}
    health = hh.parse_hub_health(frame)
    assert health.problem_text == "X9"
    assert hh.device_problem_is_on(frame) is True


def test_numeric_code(hh, frame):
    frame["status"]["safety"] = {"error": True, "error_codes": [17]}
    health = hh.parse_hub_health(frame)
    assert health.error_codes_text == "17"
    assert hh.error_codes_attributes(health) == {"codes": [17]}
    assert health.problem_text == "17"


def test_unknown_code_shown_raw(hh, frame):
    codes = ["SOMETHING_NEW", "SOMETHING_NEW", "weird code 42", 3.5]
    frame["status"]["safety"] = {"error": True, "error_codes": codes}
    health = hh.parse_hub_health(frame)
    assert health.error_codes_text == "SOMETHING_NEW, SOMETHING_NEW, weird code 42, 3.5"
    assert hh.error_codes_attributes(health)["codes"] == codes


def test_no_safety_block(hh, frame):
    del frame["status"]["safety"]
    health = hh.parse_hub_health(frame)
    assert health.problem_text is None
    assert health.error_codes_text is None
    assert health.error_codes is None
    assert health.error_descriptions is None
    assert hh.problem_attributes(health) is None
    assert hh.error_codes_attributes(health) is None
    # device_problem: unchanged from today (False when no safety dict).
    assert hh.device_problem_is_on(frame) is False
    assert hh.device_problem_attributes(frame) is None


def test_safety_error_not_boolean_without_codes(hh, frame):
    frame["status"]["safety"] = {"error_codes": []}
    assert hh.parse_hub_health(frame).problem_text is None
    frame["status"]["safety"] = {"error": 0, "error_codes": []}
    assert hh.parse_hub_health(frame).problem_text is None


def test_error_codes_not_a_list(hh, frame):
    frame["status"]["safety"] = {"error": False, "error_codes": "X1"}
    health = hh.parse_hub_health(frame)
    assert health.error_codes_text is None
    assert health.error_codes is None
    assert health.problem_text == "OK"


def test_no_problem_with_descriptions_is_ok(hh, frame):
    # Plan-review note 1: descriptions are ignored when no problem is present.
    frame["status"]["safety"] = {
        "error": False,
        "error_codes": [],
        "error_descriptions": ["Stale description"],
    }
    health = hh.parse_hub_health(frame)
    assert health.problem_text == "OK"
    assert health.error_codes_text == "none"
    assert hh.device_problem_is_on(frame) is False


def test_long_text_cut_to_255(hh, frame):
    descriptions = [f"Description number {i} " + "x" * 40 for i in range(10)]
    codes = [f"CODE_{i:03d}_" + "Y" * 30 for i in range(10)]
    frame["status"]["safety"] = {
        "error": True,
        "error_codes": codes,
        "error_descriptions": descriptions,
    }
    health = hh.parse_hub_health(frame)
    assert len("; ".join(descriptions)) > 255
    assert health.problem_text == "; ".join(descriptions)[:255]
    assert len(health.problem_text) == 255
    assert health.error_codes_text == ", ".join(codes)[:255]
    assert len(health.error_codes_text) == 255
    attrs = hh.error_codes_attributes(health)
    assert attrs["codes"] == codes
    assert attrs["descriptions"] == descriptions


def test_long_single_text_fields_cut(hh, frame):
    frame["status"]["firmware"]["cb"] = "v" * 400
    frame["water_fill"] = "w" * 300
    health = hh.parse_hub_health(frame)
    assert health.hub_firmware == "v" * 255
    assert health.water_fill == "w" * 255


def test_pad_sensor_failed(hh, frame):
    frame["status"]["sensors"]["sensor2"]["is_working"] = False
    health = hh.parse_hub_health(frame)
    assert health.pad_sensor("sensor2").problem is True
    assert health.pad_sensor("sensor1").problem is False
    assert hh.pad_sensor_problem_attributes(health.pad_sensor("sensor2")) == {
        "firmware_version": "1.0.1-test",
        "hardware_version": "1.0-test",
    }


def test_pad_sensor_missing_block(hh, frame):
    del frame["status"]["sensors"]["sensor2"]
    health = hh.parse_hub_health(frame)
    assert health.sensor2 == hh.PadSensorHealth()
    assert hh.pad_sensor_problem_attributes(health.sensor2) is None
    assert health.pad_sensor("sensor9") == hh.PadSensorHealth()


@pytest.mark.parametrize("bad", ["", "   ", 11, 1.5, None, True, ["1.0"]])
def test_bad_version_string(hh, frame, bad):
    frame["status"]["sensors"]["sensor1"]["firmware_version"] = bad
    frame["status"]["sensors"]["sensor1"]["hardware_version"] = bad
    health = hh.parse_hub_health(frame)
    assert health.pad_sensor("sensor1").firmware_version is None
    assert health.pad_sensor("sensor1").hardware_version is None
    assert hh.pad_sensor_firmware_attributes(health.sensor1) is None


def test_water_fill_raw(hh, frame):
    health = hh.parse_hub_health(frame)
    assert health.water_fill == "unknown"
    assert health.water_fill_mode is False
    frame["water_fill"] = "Some New State"
    frame["is_in_water_fill_mode"] = True
    health = hh.parse_hub_health(frame)
    assert health.water_fill == "Some New State"
    assert health.water_fill_mode is True


def test_privacy_no_network_identity(hh, frame):
    secrets = (FAKE_NETWORK_NAME, FAKE_IP, FAKE_MAC)
    health = hh.parse_hub_health(frame)
    outputs = [repr(dataclasses.asdict(health))]
    outputs += [repr(a) for a in _all_builders(hh, health)]
    outputs.append(repr(hh.device_problem_attributes(frame)))
    for text in outputs:
        for secret in secrets:
            assert secret not in text
    field_names = {f.name for f in dataclasses.fields(health)}
    assert not field_names & {"name", "ip", "mac", "ssid", "network_name"}


def test_wrong_types_give_none(hh, frame):
    frame["status"]["network"]["rssi"] = True
    frame["status"]["online"] = "yes"
    frame["led_brightness"] = "50"
    health = hh.parse_hub_health(frame)
    assert health.wifi_rssi is None
    assert health.online is None
    assert health.led_brightness is None


def test_wrong_types_more(hh, frame):
    frame["status"]["pending_update"] = {"is_available": 1}
    frame["status"]["firmware_update"] = "nope"
    frame["status"]["firmware"] = ["2.6.0"]
    frame["status"]["network"]["rssi"] = float("nan")
    frame["status"]["network"]["uptime"] = -5
    frame["is_in_water_fill_mode"] = "false"
    frame["status"]["sensors"]["sensor1"]["is_working"] = "true"
    frame["status"]["sensors"]["sensor2"] = "broken"
    health = hh.parse_hub_health(frame)
    assert health.update_available is None
    assert health.update_in_progress is None
    assert health.update_step is None
    assert health.update_result is None
    assert health.hub_firmware is None
    assert health.panel_firmware is None
    assert health.wifi_rssi is None
    assert health.uptime_seconds is None
    assert health.water_fill_mode is None
    assert health.sensor1.problem is None
    assert health.sensor2 == hh.PadSensorHealth()


def test_status_not_a_dict(hh, frame):
    frame["status"] = "broken"
    health = hh.parse_hub_health(frame)
    assert health.online is None
    assert health.problem_text is None
    # Top-level fields still parse.
    assert health.led_brightness == 0
    assert hh.device_problem_is_on(frame) is False


def test_numbers_pass_through_unclamped(hh, frame):
    frame["led_brightness"] = 250
    frame["status"]["network"]["rssi"] = 12.5
    health = hh.parse_hub_health(frame)
    assert health.led_brightness == 250
    assert health.wifi_rssi == 12.5


def test_update_fields_as_reported(hh, frame):
    frame["status"]["firmware_update"].update(
        {
            "in_progress": True,
            "current_step": "downloading",
            "result": None,
            "started_at": "2026-11-24T10:00:00Z",
            "updated_at": None,
            "completed_at": None,
        }
    )
    frame["status"]["pending_update"]["is_available"] = True
    health = hh.parse_hub_health(frame)
    assert health.update_available is True
    assert health.update_in_progress is True
    assert hh.update_in_progress_attributes(health) == {"current_step": "downloading"}
    assert hh.update_step_attributes(health) == {
        "in_progress": True,
        "started_at": "2026-11-24T10:00:00Z",
    }


@pytest.mark.parametrize("bad", [0, -10, "1700000000", True, 1e20, float("inf")])
def test_last_seen_bad_values(hh, frame, bad):
    frame["status"]["network"]["last_seen"] = bad
    assert hh.parse_hub_health(frame).last_seen is None


def test_last_seen_float(hh, frame):
    frame["status"]["network"]["last_seen"] = 1700000500.5
    last_seen = hh.parse_hub_health(frame).last_seen
    assert last_seen.tzinfo is timezone.utc
    assert last_seen.timestamp() == 1700000500.5


def test_health_is_frozen(hh, frame):
    health = hh.parse_hub_health(frame)
    with pytest.raises(dataclasses.FrozenInstanceError):
        health.online = False
    with pytest.raises(dataclasses.FrozenInstanceError):
        health.sensor1.problem = True


# --- device_problem rule (unchanged from the original entity) -------------


def test_device_problem_rule_unchanged(hh, frame):
    # 1. No payload.
    assert hh.device_problem_is_on(None) is None
    assert hh.device_problem_is_on({}) is None
    # 2. No safety dict.
    del frame["status"]["safety"]
    assert hh.device_problem_is_on(frame) is False
    frame["status"]["safety"] = "broken"
    assert hh.device_problem_is_on(frame) is False
    del frame["status"]
    assert hh.device_problem_is_on(frame) is False
    # 3. Truthy error.
    frame["status"] = {"safety": {"error": True}}
    assert hh.device_problem_is_on(frame) is True
    frame["status"] = {"safety": {"error": "yes", "error_codes": []}}
    assert hh.device_problem_is_on(frame) is True
    # 4. Otherwise bool(error_codes) when it is a list.
    frame["status"] = {"safety": {"error": False, "error_codes": ["A"]}}
    assert hh.device_problem_is_on(frame) is True
    assert hh.device_problem_attributes(frame) == {"error_codes": ["A"]}
    frame["status"] = {"safety": {"error": False, "error_codes": []}}
    assert hh.device_problem_is_on(frame) is False
    frame["status"] = {"safety": {"error": False, "error_codes": "A"}}
    assert hh.device_problem_is_on(frame) is False
    # error_codes attribute kept whenever truthy, as before.
    assert hh.device_problem_attributes(frame) == {"error_codes": "A"}


def test_device_problem_descriptions_attribute(hh, frame):
    frame["status"]["safety"] = {
        "error": False,
        "error_codes": [],
        "error_descriptions": ["Only a description"],
    }
    assert hh.device_problem_attributes(frame) == {
        "error_descriptions": ["Only a description"]
    }
    frame["status"]["safety"]["error_descriptions"] = "not a list"
    assert hh.device_problem_attributes(frame) is None
