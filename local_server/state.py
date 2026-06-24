"""In-memory state store for the local Orion server."""

from __future__ import annotations

import asyncio
import copy
import random
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional


class OrionState:
    """Thread-safe-ish in-memory store for users, devices, tokens, schedules."""

    def __init__(self) -> None:
        self._users: Dict[str, dict] = {}
        self._contacts: Dict[str, str] = {}       # contact string → user_id
        self._pending_codes: Dict[str, str] = {}  # contact → OTP
        self._access_tokens: Dict[str, dict] = {} # token → {user_id, expires}
        self._refresh_tokens: Dict[str, dict] = {}
        self._devices: Dict[str, dict] = {}        # serial → full device dict (contains "_live")
        self._schedules: Dict[str, List[dict]] = {}  # user_id → schedule list
        # WebSocket listeners: serial → list of async callbacks
        self._ws_listeners: Dict[str, List[Callable[[dict], Awaitable[None]]]] = {}

    # ── Auth ─────────────────────────────────────────────────────────────────

    def generate_code(self, contact: str) -> str:
        """Create and store a 6-digit OTP for *contact* (email or phone)."""
        code = f"{random.randint(100000, 999999):06d}"
        self._pending_codes[contact] = code
        return code

    def verify_code(self, contact: str, code: str) -> Optional[dict]:
        """Verify OTP; return token dict on success or None on failure."""
        if self._pending_codes.get(contact) != code:
            return None
        del self._pending_codes[contact]
        is_email = "@" in contact
        user = self._get_or_create_user(contact, is_email)
        return self._issue_tokens(user["id"])

    def refresh_tokens_by_refresh(self, refresh_token: str) -> Optional[dict]:
        entry = self._refresh_tokens.get(refresh_token)
        if not entry or entry["expires"] < time.time():
            return None
        return self._issue_tokens(entry["user_id"])

    def get_user_by_token(self, token: str) -> Optional[dict]:
        entry = self._access_tokens.get(token)
        if not entry or entry["expires"] < time.time():
            return None
        return self._users.get(entry["user_id"])

    def _get_or_create_user(self, contact: str, is_email: bool) -> dict:
        user_id = self._contacts.get(contact)
        if user_id:
            return self._users[user_id]
        user_id = str(uuid.uuid4())
        user: dict = {
            "id": user_id,
            "email": contact if is_email else None,
            "phone": None if is_email else contact,
            "first_name": "Local",
            "last_name": "User",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._users[user_id] = user
        self._contacts[contact] = user_id
        return user

    def _issue_tokens(self, user_id: str) -> dict:
        access = str(uuid.uuid4())
        refresh = str(uuid.uuid4())
        now = time.time()
        self._access_tokens[access] = {"user_id": user_id, "expires": now + 3600}
        self._refresh_tokens[refresh] = {"user_id": user_id, "expires": now + 86400 * 30}
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": int(now + 3600),
            "token_type": "Bearer",
        }

    # ── Devices ───────────────────────────────────────────────────────────────

    def register_device(self, serial: str, name: str | None = None) -> dict:
        """Add a device to local state. Call once during setup."""
        device_id = str(uuid.uuid4())
        device: dict = {
            "id": device_id,
            "serial_number": serial,
            "name": name or f"Orion Bed ({serial[-6:]})",
            "model": "OSCT001-1",
            "type": "control_tower",
            "orientation": "left",
            "timezone": "UTC",
            "temperature_range": {"min": 10, "max": 45},
            "temperature_scale": {
                "fahrenheit": [
                    {"in": 55, "out": 10}, {"in": 60, "out": 15},
                    {"in": 65, "out": 21}, {"in": 70, "out": 26},
                    {"in": 75, "out": 32}, {"in": 80, "out": 38},
                    {"in": 86, "out": 45},
                ],
                "relative": [
                    {"in": -10, "out": 10}, {"in": -9, "out": 12},
                    {"in": -8, "out": 14}, {"in": -7, "out": 16},
                    {"in": -6, "out": 17.5}, {"in": -5, "out": 19},
                    {"in": -4, "out": 20.5}, {"in": -3, "out": 23},
                    {"in": -2, "out": 24.5}, {"in": -1, "out": 26},
                    {"in": 0, "out": 27.5}, {"in": 1, "out": 29},
                    {"in": 2, "out": 30.5}, {"in": 3, "out": 32},
                    {"in": 4, "out": 33.5}, {"in": 5, "out": 35},
                    {"in": 6, "out": 37}, {"in": 7, "out": 39},
                    {"in": 8, "out": 41}, {"in": 9, "out": 43},
                    {"in": 10, "out": 45},
                ],
            },
            "zones": [
                {"id": "zone_a", "user": None},
                {"id": "zone_b", "user": None},
            ],
            "default_zone_id": "zone_a",
            "permissions": ["read", "write", "admin"],
            "_live": self._default_live(serial),
        }
        self._devices[serial] = device
        return device

    def _default_live(self, serial: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "serial_number": serial,
            "model": "OSCT001-1",
            "zones": [
                {"id": "zone_a", "temp": 27.5, "on": False},
                {"id": "zone_b", "temp": 27.5, "on": False},
            ],
            "led_brightness": 50,
            "water_fill": "unknown",
            "is_in_water_fill_mode": False,
            "status": {
                "online": True,
                "firmware": {"cb": "1.0.0", "ib": "1.0.0"},
                "firmware_update": {
                    "workflow_id": None,
                    "started_at": None,
                    "updated_at": None,
                    "in_progress": False,
                    "current_step": None,
                    "completed_at": None,
                    "result": None,
                },
                "pending_update": {"is_available": False},
                "network": {
                    "last_seen": now,
                    "name": "Local Network",
                    "ip": "127.0.0.1",
                    "rssi": -50,
                    "uptime": 0,
                    "mac": "AA:BB:CC:DD:EE:FF",
                },
                "safety": {
                    "error": False,
                    "error_codes": [],
                    "error_descriptions": [],
                },
                "zones": [
                    {"id": "zone_a", "temp": 27.5, "thermal_state": "standby"},
                    {"id": "zone_b", "temp": 27.5, "thermal_state": "standby"},
                ],
                "sensors": {
                    "sensor1": self._default_sensor(now),
                    "sensor2": self._default_sensor(now),
                },
            },
            "timeline": [],
        }

    @staticmethod
    def _default_sensor(now: str) -> dict:
        return {
            "heart_rate": 0,
            "breath_rate": 0,
            "status": "left_bed",
            "status_text": "left_bed",
            "sign_of_asleep": False,
            "sign_of_wake_up": False,
            "timestamp": now,
            "uptime": 0,
            "is_working": True,
            "firmware_version": "1.0.0",
            "hardware_version": "1.0.0",
        }

    def get_device_by_serial(self, serial: str) -> Optional[dict]:
        return self._devices.get(serial)

    def get_device_by_id(self, device_id: str) -> Optional[dict]:
        for d in self._devices.values():
            if d["id"] == device_id:
                return d
        return None

    def list_devices(self) -> List[dict]:
        return list(self._devices.values())

    def get_live(self, serial: str) -> Optional[dict]:
        device = self._devices.get(serial)
        return device["_live"] if device else None

    def update_live_zones(self, serial: str, zones: List[dict]) -> Optional[dict]:
        device = self._devices.get(serial)
        if not device:
            return None
        live = device["_live"]
        for update in zones:
            zone_id = update.get("id")
            for zone in live["zones"]:
                if zone["id"] == zone_id:
                    if "on" in update:
                        zone["on"] = update["on"]
                    if "temp" in update:
                        zone["temp"] = update["temp"]
        live["status"]["network"]["last_seen"] = datetime.now(timezone.utc).isoformat()
        self._broadcast(serial, "live_device.update", live)
        return live

    def update_live_zone(
        self,
        serial: str,
        zone_id: str,
        on: bool | None = None,
        temp: float | None = None,
    ) -> Optional[dict]:
        device = self._devices.get(serial)
        if not device:
            return None
        live = device["_live"]
        for zone in live["zones"]:
            if zone["id"] == zone_id:
                if on is not None:
                    zone["on"] = on
                if temp is not None:
                    zone["temp"] = temp
        live["status"]["network"]["last_seen"] = datetime.now(timezone.utc).isoformat()
        self._broadcast(serial, "live_device.update", live)
        return live

    def set_away(self, serial: str, is_away: bool) -> Optional[dict]:
        live = self.get_live(serial)
        if not live:
            return None
        if is_away:
            for zone in live["zones"]:
                zone["on"] = False
        self._broadcast(serial, "live_device.update", live)
        return live

    def update_device_meta(self, device_id: str, fields: dict) -> Optional[dict]:
        device = self.get_device_by_id(device_id)
        if not device:
            return None
        for key in ("name", "orientation", "timezone"):
            if key in fields:
                device[key] = fields[key]
        return device

    def set_led_brightness(self, serial: str, value: int) -> None:
        live = self.get_live(serial)
        if live:
            live["led_brightness"] = max(0, min(100, int(value)))
            self._broadcast(serial, "live_device.update", live)

    # ── Schedules ─────────────────────────────────────────────────────────────

    def get_schedules(self, user_id: str) -> List[dict]:
        if user_id not in self._schedules:
            self._schedules[user_id] = self._default_schedules()
        return self._schedules[user_id]

    def update_schedules(self, user_id: str, updates: List[dict]) -> List[dict]:
        schedules = self.get_schedules(user_id)
        for update in updates:
            day = update.get("day")
            for sched in schedules:
                if sched["day"] == day:
                    for k, v in update.items():
                        if k != "day":
                            sched[k] = v
        return schedules

    @staticmethod
    def _default_schedules() -> List[dict]:
        return [
            {
                "day": d,
                "bedtime": "22:00",
                "wakeup": "07:00",
                "bedtime_is_active": False,
                "wakeup_is_active": False,
                "bedtime_temp": 27.5,
                "wakeup_temp": 32.0,
                "phase_1_temp": 24.5,
                "phase_2_temp": 27.5,
                "auto_turn_off": True,
                "is_smart_temperature_active": False,
                "override_date": None,
                "is_override_available": False,
                "is_override_applied": False,
            }
            for d in range(7)
        ]

    # ── WebSocket broadcast ───────────────────────────────────────────────────

    def register_ws_listener(
        self, serial: str, callback: Callable[[dict], Awaitable[None]]
    ) -> None:
        self._ws_listeners.setdefault(serial, []).append(callback)

    def unregister_ws_listener(
        self, serial: str, callback: Callable[[dict], Awaitable[None]]
    ) -> None:
        listeners = self._ws_listeners.get(serial, [])
        self._ws_listeners[serial] = [c for c in listeners if c is not callback]

    def _broadcast(self, serial: str, event_type: str, live: dict) -> None:
        payload = copy.deepcopy(live)
        msg = {"type": event_type, "payload": payload}
        for cb in list(self._ws_listeners.get(serial, [])):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(cb(msg))
            except RuntimeError:
                pass


# Module-level singleton
state = OrionState()
