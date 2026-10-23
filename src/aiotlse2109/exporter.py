"""Prometheus HTTP exporter for one configured TL-SE2109 switch."""

import argparse
import asyncio
import logging
import math
import os
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter

from aiohttp import web
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Gauge,
    generate_latest,
)

from .client import TLSE2109
from .exceptions import SwitchError
from .models import Duplex, SwitchStatus

_LOGGER = logging.getLogger(__name__)


def _render_metrics(status: SwitchStatus | None, duration: float) -> bytes:
    # A registry per response keeps concurrent scrapes and missing data isolated.
    registry = CollectorRegistry()
    Gauge("tlse2109_up", "Whether the switch scrape succeeded.", registry=registry).set(
        status is not None
    )
    Gauge(
        "tlse2109_scrape_duration_seconds",
        "Time spent querying the switch, including time waiting for other queries.",
        registry=registry,
    ).set(duration)
    if status is None:
        return generate_latest(registry)

    Gauge(
        "tlse2109_info",
        "Switch model and firmware.",
        ["model", "firmware"],
        registry=registry,
    ).labels(status.device.model, status.device.firmware_version).set(1)

    measurements = (
        (
            "enabled",
            "Whether the port is administratively enabled.",
            lambda p: p.enabled,
        ),
        ("link_up", "Whether the port has an active link.", lambda p: p.link_up),
        (
            "negotiated_speed_bits_per_second",
            "Negotiated physical link speed.",
            lambda p: (
                p.negotiated_speed_mbps * 1_000_000
                if p.negotiated_speed_mbps is not None
                else None
            ),
        ),
        (
            "full_duplex",
            "Full duplex is 1; half duplex is 0.",
            lambda p: p.duplex == Duplex.FULL if p.duplex is not None else None,
        ),
        (
            "receive_bits_per_second",
            "Latest receive rate at the switch port.",
            lambda p: p.rx_bps,
        ),
        (
            "transmit_bits_per_second",
            "Latest transmit rate at the switch port.",
            lambda p: p.tx_bps,
        ),
    )
    for name, description, value in measurements:
        metric = Gauge(
            f"tlse2109_port_{name}", description, ["port"], registry=registry
        )
        for port in status.ports:
            sample = value(port)
            if sample is not None:
                metric.labels(str(port.number)).set(sample)
    return generate_latest(registry)


def create_app(switch: TLSE2109, *, timeout: float = 10.0) -> web.Application:
    """Create an exporter app that owns and closes the supplied switch client.

    The timeout bounds the entire scrape, including authentication and queued
    requests. Startup does not contact the switch, allowing failures to be
    reported through metrics. No snapshots are cached between requests.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Scrape timeout must be finite and positive")

    async def metrics(request: web.Request) -> web.Response:
        started = perf_counter()
        status = None
        try:
            async with asyncio.timeout(timeout):
                status = await switch.get_status()
        except (SwitchError, TimeoutError) as exc:
            # Exception text can contain device or credential data.
            _LOGGER.warning("Switch scrape failed (%s)", type(exc).__name__)
        return web.Response(
            body=_render_metrics(status, perf_counter() - started),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    async def lifetime(app: web.Application) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await switch.close()

    app = web.Application()
    app.router.add_get("/metrics", metrics)
    app.cleanup_ctx.append(lifetime)
    return app


def main() -> None:
    """Start the exporter using CLI options and process environment variables."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=os.environ.get("SE2109_HOST"),
        help="Switch hostname or URL (default: SE2109_HOST)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("SE2109_USER"),
        help="Switch username (default: SE2109_USER)",
    )
    parser.add_argument(
        "--password-file",
        type=Path,
        help="Read password from this file instead of SE2109_PASSWORD",
    )
    parser.add_argument("--listen-address", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9109)
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Maximum duration of a switch scrape in seconds (default: 10)",
    )
    args = parser.parse_args()
    if not args.host or not args.username:
        parser.error("Provide --host and --username, or SE2109_HOST and SE2109_USER")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        password = (
            args.password_file.read_text().rstrip("\r\n")
            if args.password_file
            else os.environ.get("SE2109_PASSWORD", "")
        )
        if not password:
            parser.error("Provide --password-file or SE2109_PASSWORD")
        switch = TLSE2109(args.host, args.username, password, timeout=args.timeout)
        app = create_app(switch, timeout=args.timeout)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    web.run_app(app, host=args.listen_address, port=args.port, access_log=None)


if __name__ == "__main__":
    main()
