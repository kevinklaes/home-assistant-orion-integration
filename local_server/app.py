"""FastAPI application — implements the Orion REST API and WebSocket locally."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Annotated, Optional

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse

from .config import config
from .state import state

logger = logging.getLogger(__name__)


# ── Startup / shutdown ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    for serial in config.device_serials:
        state.register_device(serial)
        logger.info("Pre-registered device serial: %s", serial)
    if not config.device_serials:
        logger.warning(
            "No devices pre-registered. Set ORION_DEVICE_SERIALS=<serial> "
            "or POST /admin/devices to add one."
        )
    yield


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(title="Local Orion Server", version="1.0.0", lifespan=lifespan)


# ── Helpers ───────────────────────────────────────────────────────────────────

def wrap(data: Any) -> dict:
    """Wrap response in the standard Orion envelope."""
    return {"response": data, "success": True}


def public_device(device: dict) -> dict:
    """Strip internal underscore-prefixed keys before returning to clients."""
    return {k: v for k, v in device.items() if not k.startswith("_")}


# ── Auth dependency ───────────────────────────────────────────────────────────

async def require_user(
    authorization: Annotated[Optional[str], Header()] = None,
) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:].strip()
    user = state.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


CurrentUser = Annotated[dict, Depends(require_user)]


# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/v1/auth/code")
async def auth_request_code(request: Request) -> dict:
    body = await request.json()
    contact = body.get("email") or body.get("phone")
    if not contact:
        raise HTTPException(status_code=400, detail="email or phone required")
    code = state.generate_code(contact)
    # Print to stdout — the user reads it and enters it in the HA config flow
    print(f"\n{'='*50}")
    print(f"  VERIFICATION CODE for {contact}:  {code}")
    print(f"{'='*50}\n", flush=True)
    logger.info("Verification code for %s: %s", contact, code)
    return {"success": True}


@app.post("/v1/auth/do")
@app.post("/v1/auth/verify")
async def auth_verify_code(request: Request) -> dict:
    body = await request.json()
    contact = body.get("email") or body.get("phone")
    code = body.get("code", "")
    if not contact:
        raise HTTPException(status_code=400, detail="email or phone required")
    tokens = state.verify_code(contact, code)
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid verification code")
    # Return flat snake_case — matches _extract_tokens shape 3 in api.py
    return tokens


@app.post("/v1/auth/refresh")
async def auth_refresh(request: Request) -> dict:
    body = await request.json()
    refresh_token = body.get("refresh_token") or body.get("refreshToken")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token required")
    tokens = state.refresh_tokens_by_refresh(refresh_token)
    if not tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return tokens


@app.get("/v1/auth/me")
async def auth_me(user: CurrentUser) -> dict:
    return wrap(user)


# ── Device endpoints ──────────────────────────────────────────────────────────

@app.get("/v1/devices")
async def list_devices(user: CurrentUser) -> dict:
    devices = [public_device(d) for d in state.list_devices()]
    return wrap({"devices": devices, "shared_with": []})


@app.post("/v1/devices/{device_id}/activate")
async def activate_device(device_id: str, request: Request, user: CurrentUser) -> dict:
    return wrap({"activated": True})


@app.post("/v1/devices/{device_id}/deactivate")
async def deactivate_device(device_id: str, user: CurrentUser) -> dict:
    return wrap({"deactivated": True})


@app.post("/v1/devices/{device_id}/update")
async def trigger_firmware_update(device_id: str, user: CurrentUser) -> dict:
    return wrap({"update_triggered": True})


@app.put("/v1/devices/{device_id}")
async def update_device_meta(device_id: str, request: Request, user: CurrentUser) -> dict:
    body = await request.json()
    device = state.update_device_meta(device_id, body)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return wrap(public_device(device))


@app.post("/v1/devices/{device_id}/action")
async def device_action(device_id: str, request: Request, user: CurrentUser) -> dict:
    body = await request.json()
    action = body.get("action", "")
    value = body.get("value")
    logger.info("Device action %s on %s (value=%s)", action, device_id, value)
    device = state.get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if action == "device_led_brightness" and value is not None:
        state.set_led_brightness(device["serial_number"], int(value))
    return wrap({"action": action, "status": "accepted"})


# ── Live device endpoints ─────────────────────────────────────────────────────

@app.get("/v1/devices/{serial}/live")
async def get_live_device(serial: str, user: CurrentUser) -> dict:
    live = state.get_live(serial)
    if live is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return wrap(copy.deepcopy(live))


@app.put("/v1/devices/{serial}/live")
async def update_live_device(serial: str, request: Request, user: CurrentUser) -> dict:
    body = await request.json()
    zones = body.get("zones", [])
    live = state.update_live_zones(serial, zones)
    if live is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return wrap(copy.deepcopy(live))


@app.put("/v1/devices/{serial}/live/zones/{zone_id}")
async def update_live_zone(
    serial: str, zone_id: str, request: Request, user: CurrentUser
) -> dict:
    body = await request.json()
    on: Optional[bool] = body.get("on")
    temp: Optional[float] = body.get("temp")
    if on is None and temp is None:
        raise HTTPException(status_code=400, detail="on or temp required")
    live = state.update_live_zone(serial, zone_id, on=on, temp=temp)
    if live is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return wrap(copy.deepcopy(live))


# ── Sleep configuration endpoints ────────────────────────────────────────────

@app.post("/v1/sleep-configurations/user-away")
async def set_user_away(request: Request, user: CurrentUser) -> dict:
    body = await request.json()
    is_away = bool(body.get("is_away", False))
    for device in state.list_devices():
        state.set_away(device["serial_number"], is_away)
    return wrap({"is_away": is_away, "devices": [public_device(d) for d in state.list_devices()]})


@app.put("/v1/sleep-configurations/temperature")
async def set_temperature(request: Request, user: CurrentUser) -> dict:
    body = await request.json()
    device_id = body.get("deviceId")
    temp = body.get("temperature")
    zone_id_override = body.get("zone_id")
    if device_id:
        device = state.get_device_by_id(device_id)
        if device:
            zone_id = zone_id_override or device.get("default_zone_id", "zone_a")
            state.update_live_zone(device["serial_number"], zone_id, temp=temp)
    return wrap({"success": True})


# ── Schedule endpoints ────────────────────────────────────────────────────────

@app.get("/v1/sleep-schedules")
async def get_schedules(user: CurrentUser) -> dict:
    user_id = user["id"]
    schedules = state.get_schedules(user_id)
    today_day = date.today().weekday()  # 0=Monday
    today_sched = next((s for s in schedules if s["day"] == today_day), schedules[0])
    return wrap({
        "schedules": {user_id: schedules},
        "today_sleep_schedule": {user_id: today_sched},
        "recommendations": {user_id: []},
    })


@app.put("/v1/sleep-schedules")
async def update_schedules(request: Request, user: CurrentUser) -> dict:
    body = await request.json()
    updates = body.get("schedules", [])
    if updates:
        state.update_schedules(user["id"], updates)
    return wrap({"success": True})


# ── Insights endpoint ─────────────────────────────────────────────────────────

@app.get("/v2/insights")
async def get_insights(
    user: CurrentUser,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
) -> dict:
    # Returns empty insight data — real data requires the physical device connection
    return {
        "user_id": user["id"],
        "data": {},
        "overview": {},
    }


# ── Admin endpoints (not part of the real Orion API) ─────────────────────────

@app.post("/admin/devices")
async def admin_register_device(request: Request) -> dict:
    """Register a device serial number. Not auth-protected — local admin only."""
    body = await request.json()
    serial = body.get("serial_number", "").strip()
    name = body.get("name")
    if not serial:
        raise HTTPException(status_code=400, detail="serial_number required")
    device = state.register_device(serial, name)
    logger.info("Admin registered device: %s", serial)
    return {"registered": True, "device": public_device(device)}


@app.get("/admin/devices")
async def admin_list_devices() -> dict:
    return {"devices": [public_device(d) for d in state.list_devices()]}


@app.put("/admin/devices/{serial}/sensors")
async def admin_update_sensors(serial: str, request: Request) -> dict:
    """Inject simulated sensor readings — useful for testing without a real device."""
    body = await request.json()
    live = state.get_live(serial)
    if not live:
        raise HTTPException(status_code=404, detail="Device not found")
    sensors = live["status"]["sensors"]
    for sensor_key in ("sensor1", "sensor2"):
        if sensor_key in body:
            sensors[sensor_key].update(body[sensor_key])
    state._broadcast(serial, "live_device.update", live)
    return {"success": True}


# ── WebSocket endpoint ────────────────────────────────────────────────────────
# Handles: wss://live.api1.orionbed.com/device/{serial}?token=JWT

@app.websocket("/device/{serial}")
async def websocket_live(websocket: WebSocket, serial: str, token: Optional[str] = Query(None)) -> None:
    user = state.get_user_by_token(token) if token else None
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    live = state.get_live(serial)
    if live is None:
        await websocket.close(code=4004, reason="Device not found")
        return

    await websocket.accept()
    logger.info("WS connected: serial=%s user=%s", serial, user["id"])

    # Send initial snapshot immediately (matches real server behaviour)
    await websocket.send_text(json.dumps({
        "type": "live_device.snapshot",
        "payload": copy.deepcopy(live),
    }))

    # Queue for mutation-triggered updates
    update_queue: asyncio.Queue[dict] = asyncio.Queue()

    async def on_update(msg: dict) -> None:
        await update_queue.put(msg)

    state.register_ws_listener(serial, on_update)

    try:
        sender_task = asyncio.create_task(_ws_sender(websocket, serial, update_queue))
        # Absorb any inbound frames (the real server ignores them too)
        receiver_task = asyncio.create_task(_ws_receiver(websocket))
        done, pending = await asyncio.wait(
            [sender_task, receiver_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS error for %s: %s", serial, exc)
    finally:
        state.unregister_ws_listener(serial, on_update)
        logger.info("WS disconnected: serial=%s", serial)


async def _ws_sender(
    websocket: WebSocket, serial: str, queue: asyncio.Queue[dict]
) -> None:
    """Send queued updates, or an idle heartbeat every ws_idle_interval seconds."""
    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=config.ws_idle_interval)
        except asyncio.TimeoutError:
            live = state.get_live(serial)
            if live is None:
                break
            msg = {"type": "live_device.update", "payload": copy.deepcopy(live)}
        await websocket.send_text(json.dumps(msg))


async def _ws_receiver(websocket: WebSocket) -> None:
    while True:
        await websocket.receive_text()
