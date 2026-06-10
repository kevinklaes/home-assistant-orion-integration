#!/usr/bin/env python3
"""
Convenience launcher for the local Orion server.

Environment variables:
    ORION_HOST              Bind address (default: 0.0.0.0)
    ORION_PORT              Port (default: 443)
    ORION_TLS               0 to disable TLS (default: 1 = enabled)
    ORION_CERT              TLS certificate file (default: certs/server.crt)
    ORION_KEY               TLS private key file (default: certs/server.key)
    ORION_DEVICE_SERIALS    Comma-separated device serial numbers to pre-register
    ORION_WS_IDLE_INTERVAL  WebSocket idle push interval in seconds (default: 2.0)

Quick-start (HTTP, no TLS — good for testing the HA integration first):
    ORION_TLS=0 ORION_PORT=8080 ORION_DEVICE_SERIALS=ABC123 python run_local_server.py

HTTPS on port 443 (requires sudo / CAP_NET_BIND_SERVICE on Linux):
    sudo ORION_DEVICE_SERIALS=ABC123 python run_local_server.py
"""
import sys
import os

# Make sure the package root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from local_server.main import run

if __name__ == "__main__":
    run()
