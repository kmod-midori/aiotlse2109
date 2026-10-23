# Exporter reference

[Back to README](../README.md)

Install the optional exporter dependency:

```sh
pip install '.[exporter]'
```

Run one process per switch. Configure `SE2109_HOST`, `SE2109_USER`, and
`SE2109_PASSWORD` in the process environment, then run:

```sh
aiotlse2109-exporter
```

Alternatively, provide the host, username, and a password file:

```sh
aiotlse2109-exporter --host 192.0.2.10 --username admin \
  --password-file /path/to/switch-password
```

The password file takes precedence over `SE2109_PASSWORD`; a final newline
is stripped. `--host` and `--username` override their environment defaults.
The exporter serves `/metrics` at `127.0.0.1:9109` by default. Use
`--listen-address 0.0.0.0` to accept connections from other hosts and `--port`
to change the listening port. `python -m aiotlse2109.exporter` also works.

Each scrape reads a fresh switch snapshot. `--timeout` (default 10 seconds)
bounds the entire read, including authentication, retries, and waiting for
concurrent reads. The exporter starts even if the switch is unavailable.
The same login session is reused across scrapes; an expired session is renewed.
Shutdown closes its switch client.

Example Prometheus configuration for an exporter on the same host:

```yaml
scrape_configs:
  - job_name: tlse2109
    scrape_interval: 30s
    scrape_timeout: 15s
    static_configs:
      - targets: ["127.0.0.1:9109"]
        labels:
          switch: office
```

For additional switches, run additional exporter processes on distinct ports
and add their addresses to Prometheus. Keep `scrape_timeout` longer than the
exporter's `--timeout`.

All exported metrics are gauges. Port labels use chassis numbers `1`–`9`.

| Metric | Meaning |
| --- | --- |
| `tlse2109_up` | 1 when the switch read succeeds; otherwise 0 |
| `tlse2109_scrape_duration_seconds` | Duration of the switch read |
| `tlse2109_info{model,firmware}` | Switch model and firmware, value 1 |
| `tlse2109_port_enabled{port}` | Administrative state, 1 or 0 |
| `tlse2109_port_link_up{port}` | Link state, 1 or 0 |
| `tlse2109_port_negotiated_speed_bits_per_second{port}` | Physical link speed |
| `tlse2109_port_full_duplex{port}` | 1 for full duplex, 0 for half duplex |
| `tlse2109_port_receive_bits_per_second{port}` | Current receive rate |
| `tlse2109_port_transmit_bits_per_second{port}` | Current transmit rate |

Unknown link speed and duplex samples are omitted. Receive and transmit rates
are already per-second values: query them directly, without PromQL `rate()`.
For Mbps, divide by `1e6`.

On a switch error or timeout, `/metrics` returns HTTP 200 with `tlse2109_up 0`
and the scrape duration. It omits port and device metrics so old readings
cannot appear current. Alert on `tlse2109_up == 0` for switch failures and
Prometheus's own `up == 0` for exporter connectivity failures. No credentials,
MAC addresses, management addresses, or device descriptions are exported.

### Docker

Build the exporter image:

```sh
docker build -t aiotlse2109-exporter .
```

With `SE2109_HOST`, `SE2109_USER`, and `SE2109_PASSWORD` exported in your shell:

```sh
docker run --rm --name tlse2109-exporter \
  -p 127.0.0.1:9109:9109 \
  -e SE2109_HOST -e SE2109_USER -e SE2109_PASSWORD \
  aiotlse2109-exporter
```

Metrics are available at `http://127.0.0.1:9109/metrics`. To expose the exporter
to Prometheus on another host, use `-p 9109:9109`. The container runs as a
non-root user and listens on `0.0.0.0:9109` internally. Supply credentials at runtime.
Append exporter options after the image name, for example `--timeout 5`.

### Docker Compose

The [Compose example](../examples/compose.yaml) builds locally and accepts the same
three environment variables. From the repository root, with them exported:

```sh
docker compose -f examples/compose.yaml up -d --build
```

You can also use Compose's `--env-file` option to load your configuration file.
Metrics are exposed on `127.0.0.1:9109`; change the port mapping in the example
if Prometheus runs on another host.

To use a published image, set `EXPORTER_IMAGE=ghcr.io/OWNER/REPOSITORY:latest`
(replace the owner and repository with their lowercase names), then run:

```sh
docker compose -f examples/compose.yaml pull
docker compose -f examples/compose.yaml up -d --no-build
```
