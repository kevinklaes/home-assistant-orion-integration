"""File checks that import nothing from the integration."""

from __future__ import annotations

import ast
import json

import pytest

from conftest import COMPONENT_DIR, FAULTS_PATH, HUB_HEALTH_PATH

STRINGS = COMPONENT_DIR / "strings.json"
EN = COMPONENT_DIR / "translations" / "en.json"
DIAGNOSTICS = COMPONENT_DIR / "diagnostics.py"

NEW_KEYS = {
    "binary_sensor": (
        "hub_online",
        "firmware_update_available",
        "firmware_update_in_progress",
        "water_fill_mode",
        "sensor1_problem",
        "sensor2_problem",
    ),
    "sensor": (
        "wifi_signal",
        "last_restart",
        "last_seen",
        "hub_firmware",
        "panel_firmware",
        "firmware_update_step",
        "problem_description",
        "error_codes",
        "water_fill",
        "led_brightness",
        "sensor1_firmware",
        "sensor2_firmware",
    ),
}

def test_new_key_count():
    assert sum(len(keys) for keys in NEW_KEYS.values()) == 18


def test_strings_and_en_identical():
    assert STRINGS.read_bytes() == EN.read_bytes()


@pytest.mark.parametrize("path", [STRINGS, EN], ids=["strings", "en"])
def test_new_translation_keys_present(path):
    entity = json.loads(path.read_text(encoding="utf-8"))["entity"]
    missing = []
    for platform, keys in NEW_KEYS.items():
        for key in keys:
            entry = entity.get(platform, {}).get(key)
            if not isinstance(entry, dict) or not entry.get("name"):
                missing.append(f"{platform}.{key}")
    assert not missing, missing


def _to_redact_literal() -> set[str]:
    tree = ast.parse(DIAGNOSTICS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "TO_REDACT":
                assert isinstance(node.value, ast.Set), "TO_REDACT must be a set literal"
                return {
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
    raise AssertionError("TO_REDACT not found in diagnostics.py")


def test_diagnostics_redaction():
    assert {"name", "ip", "mac"} <= _to_redact_literal()


def _assert_standard_library_only(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name} must not use relative imports"
            module = node.module or ""
            assert not module.startswith(("homeassistant", "aiohttp")), module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("homeassistant", "aiohttp")), alias.name


def test_hub_health_imports_standard_library_only():
    _assert_standard_library_only(HUB_HEALTH_PATH)


def test_faults_imports_standard_library_only():
    _assert_standard_library_only(FAULTS_PATH)


FAULTS_HEADER = [
    "# Fault identifiers, names and advice adapted from Ember & Tide (https://github.com/Ncbudd/ember-tide).",
    "# Licensed under the PolyForm Noncommercial License 1.0.0: https://polyformproject.org/licenses/noncommercial/1.0.0",
    "# Required Notice: Copyright (c) 2026 Ncbudd (https://github.com/Ncbudd/ember-tide)",
]


def test_faults_licence_header():
    lines = FAULTS_PATH.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == FAULTS_HEADER


def test_fault_codes_map_to_faults(faults):
    assert len(faults.FAULT_CODES) == 16
    assert len(faults.ZONE_FAULTS) == 2
    assert len(faults.FAULTS) == 16
    assert set(faults.FAULT_CODES.values()) <= set(faults.FAULTS)
    assert faults.ZONE_FAULT_KEY in faults.FAULTS
