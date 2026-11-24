"""Shared fixtures for the hub-health unit tests.

``custom_components.orion_sleep`` cannot be imported outside Home Assistant
(its ``__init__`` imports ``homeassistant``), so ``hub_health.py`` is loaded
by file path. It has no Home Assistant imports and no relative imports.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "orion_sleep"
HUB_HEALTH_PATH = COMPONENT_DIR / "hub_health.py"

MODULE_NAME = "orion_hub_health"

# Made-up identifiers. None of these belong to a real device or network.
FAKE_SERIAL = "TESTSERIAL01"
FAKE_NETWORK_NAME = "example-wifi"
FAKE_IP = "192.0.2.10"
FAKE_MAC = "02:00:00:00:00:01"


def _load_hub_health():
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, HUB_HEALTH_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module: dataclasses resolve the module by name.
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def hh():
    """The hub_health module, loaded by path."""
    return _load_hub_health()


_HEALTHY_FRAME = {
    "serial_number": FAKE_SERIAL,
    "model": "OSCT001-1",
    "zones": [
        {"id": "zone_a", "temp": 20.5, "on": False},
        {"id": "zone_b", "temp": 20.5, "on": False},
    ],
    "led_brightness": 0,
    "water_fill": "unknown",
    "is_in_water_fill_mode": False,
    "status": {
        "online": True,
        "firmware": {"cb": "2.6.0", "ib": "2.5.0"},
        "firmware_update": {
            "workflow_id": "test-workflow",
            "started_at": 1700000000,
            "updated_at": 1700000100,
            "in_progress": False,
            "current_step": "complete",
            "completed_at": 1700000200,
            "result": "success",
        },
        "pending_update": {"is_available": False},
        "network": {
            "last_seen": 1700000500,
            "name": FAKE_NETWORK_NAME,
            "ip": FAKE_IP,
            "rssi": -58,
            "uptime": 3600,
            "mac": FAKE_MAC,
        },
        "safety": {"error": False, "error_codes": [], "error_descriptions": []},
        "zones": [
            {"id": "zone_a", "temp": 21.9, "thermal_state": "standby"},
            {"id": "zone_b", "temp": 22.1, "thermal_state": "standby"},
        ],
        "sensors": {
            "sensor1": {
                "heart_rate": 0,
                "breath_rate": 0,
                "status": 5,
                "status_text": "left_bed",
                "sign_of_asleep": 1,
                "sign_of_wake_up": 1,
                "timestamp": 1700000400,
                "uptime": 7200,
                "is_working": True,
                "firmware_version": "1.0.0-test",
                "hardware_version": "1.0-test",
            },
            "sensor2": {
                "heart_rate": 0,
                "breath_rate": 0,
                "status": 5,
                "status_text": "left_bed",
                "sign_of_asleep": 1,
                "sign_of_wake_up": 1,
                "timestamp": 1700000400,
                "uptime": 7200,
                "is_working": True,
                "firmware_version": "1.0.1-test",
                "hardware_version": "1.0-test",
            },
        },
    },
}


def make_frame() -> dict:
    """Return a fresh, hand-written healthy live payload."""
    return copy.deepcopy(_HEALTHY_FRAME)


@pytest.fixture
def frame() -> dict:
    return make_frame()
