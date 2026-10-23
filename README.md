# aiotlse2109

An asyncio-based, read-only Python client and Prometheus exporter for the
TP-Link TL-SE2109 Ethernet switch. Requires Python 3.11 or newer.

Reads device information and all nine ports, including administrative state,
link status, negotiated speed, duplex, and receive/transmit throughput.

Tested with firmware **1.8.0 Build 20250331 Rel.32620**. Other firmware versions
may require changes; see [protocol and verification notes](docs/protocol.md).

## Installation

From this checkout:

```sh
pip install .
```

## Library usage

Pass the host and credentials to the client:

```python
import asyncio

from aiotlse2109 import TLSE2109


async def main():
    async with TLSE2109("192.0.2.10", "admin", "your-password") as switch:
        status = await switch.get_status()
        for port in status.ports:
            print(
                port.number,
                port.status.value,
                port.negotiated_speed_mbps,
                port.rx_mbps,
                port.tx_mbps,
            )


asyncio.run(main())
```

Port numbers are 1–9. Receive and transmit rates are measured from the
switch's perspective. Unknown negotiated speed and duplex are `None`.

Reuse the client for repeated reads. It retains its login session and renews
it when needed. To poll continuously:

```python
async with TLSE2109(host, username, password) as switch:
    async for status in switch.poll(interval=5):
        print(status.ports)
```

See the [library reference](docs/library.md) for per-port queries, units,
custom HTTP sessions, and errors. The runnable
[status example](examples/status.py) accepts credentials through environment
variables.

## Prometheus exporter

Install and run with `SE2109_HOST`, `SE2109_USER`, and `SE2109_PASSWORD`
exported in the process environment:

```sh
pip install '.[exporter]'
aiotlse2109-exporter
```

Metrics are available at `http://127.0.0.1:9109/metrics`. Run one exporter per
switch. The login session is reused across scrapes.

Use `--listen-address 0.0.0.0` for access from other hosts, `--port` to change
the listening port, and `--timeout` to change the default 10-second scrape
timeout. A password file is also supported:

```sh
aiotlse2109-exporter --host 192.0.2.10 --username admin \
  --password-file /path/to/switch-password
```

Example Prometheus configuration:

```yaml
scrape_configs:
  - job_name: tlse2109
    scrape_interval: 30s
    scrape_timeout: 15s
    static_configs:
      - targets: ["127.0.0.1:9109"]
```

Keep Prometheus's `scrape_timeout` longer than the exporter's `--timeout`.
Traffic metrics are already rates in bits per second; query them directly
without PromQL `rate()`. `tlse2109_up` reports whether the switch read succeeded.

See the [exporter reference](docs/exporter.md) for all metrics, configuration
options, and failure behavior.

## Docker Compose

With the same three environment variables exported, run the
[Compose example](examples/compose.yaml) from the repository root:

```sh
docker compose -f examples/compose.yaml up -d --build
```

Use Compose's `--env-file` option to load a configuration file. Metrics are
exposed on `127.0.0.1:9109`; adjust the port mapping for access from other hosts.

To use a published image instead of building locally:

```sh
export EXPORTER_IMAGE=ghcr.io/owner/repository:latest
docker compose -f examples/compose.yaml pull
docker compose -f examples/compose.yaml up -d --no-build
```

Replace `owner/repository` with the GitHub repository's lowercase name.
Version tags such as `:0.1.0` are also available; `latest` follows the newest
stable release. See the [Docker instructions](docs/exporter.md#docker) to run
without Compose.

## Development

See [development and releases](docs/development.md) for local checks, CI,
package builds, and GHCR publishing, and [protocol notes](docs/protocol.md)
for firmware details.
