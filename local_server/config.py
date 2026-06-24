"""Configuration for local Orion server, read from environment variables."""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 443
    use_tls: bool = True
    cert_file: str = "certs/server.crt"
    key_file: str = "certs/server.key"
    # When True, verification codes are printed to stdout instead of sent
    console_codes: bool = True
    # Pre-registered device serials (comma-separated via env var)
    device_serials: List[str] = field(default_factory=list)
    # When True, send a live_device.update idle push every N seconds
    ws_idle_interval: float = 2.0


def load() -> Config:
    serials_raw = os.environ.get("ORION_DEVICE_SERIALS", "").strip()
    device_serials = [s.strip() for s in serials_raw.split(",") if s.strip()]

    return Config(
        host=os.environ.get("ORION_HOST", "0.0.0.0"),
        port=int(os.environ.get("ORION_PORT", "443")),
        use_tls=os.environ.get("ORION_TLS", "1") not in ("0", "false", "no"),
        cert_file=os.environ.get("ORION_CERT", "certs/server.crt"),
        key_file=os.environ.get("ORION_KEY", "certs/server.key"),
        console_codes=os.environ.get("ORION_CONSOLE_CODES", "1") not in ("0", "false", "no"),
        device_serials=device_serials,
        ws_idle_interval=float(os.environ.get("ORION_WS_IDLE_INTERVAL", "2.0")),
    )


config = load()
