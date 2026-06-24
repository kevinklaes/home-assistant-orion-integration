"""Entry point — launches uvicorn with optional TLS."""

from __future__ import annotations

import logging
import os
import ssl
import sys

import uvicorn

from .app import app
from .config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _build_ssl_context(cert: str, key: str) -> ssl.SSLContext:
    if not os.path.exists(cert):
        logger.error("TLS cert not found: %s — run `python setup_certs.py` first", cert)
        sys.exit(1)
    if not os.path.exists(key):
        logger.error("TLS key not found: %s — run `python setup_certs.py` first", key)
        sys.exit(1)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    # Force TLS 1.2+ only
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def run() -> None:
    ssl_ctx = None
    if config.use_tls:
        ssl_ctx = _build_ssl_context(config.cert_file, config.key_file)
        scheme = "https"
    else:
        scheme = "http"
        logger.warning("TLS disabled — running plain HTTP on port %d", config.port)

    logger.info(
        "Starting local Orion server on %s://%s:%d",
        scheme, config.host, config.port,
    )
    logger.info(
        "REST: %s://api1.orionbed.com → %s:%d  (after DNS redirect)",
        scheme, config.host, config.port,
    )
    logger.info(
        "WS:   wss://live.api1.orionbed.com → %s:%d/device/{{serial}}",
        config.host, config.port,
    )

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        ssl=ssl_ctx,
        log_level="info",
        # Force HTTP/1.1 — same reason as the HA WS client (Cloudflare negotiates h2
        # in the real server, but our uvicorn WS only speaks HTTP/1.1).
        http="h11",
    )


if __name__ == "__main__":
    run()
