# Library reference

[Back to README](../README.md)

Pass the host and credentials explicitly to the constructor.

```python
import asyncio

from aiotlse2109 import TLSE2109


async def main():
    async with TLSE2109("192.0.2.10", "admin", "your-password") as switch:
        status = await switch.get_status()
        print(status.device.model, status.device.firmware_version)

        for port in status.ports:
            print(
                port.number,
                port.status.value,
                port.negotiated_speed_mbps,
                port.rx_mbps,
                port.tx_mbps,
            )

        # Physical chassis numbers are 1–9.
        port = await switch.get_port(9)
        print(port.negotiated_speed_mbps, port.duplex)


asyncio.run(main())
```

`get_status()` retrieves a single snapshot containing device information,
all ports, and a UTC `sampled_at` timestamp. `get_ports()` returns just the
ports; `get_port(number)` retrieves a snapshot and selects that port.
`status.port(number)` selects a port from an existing snapshot without a
network request. Results are immutable dataclasses.

For continuous monitoring, reuse one client:

```python
async with TLSE2109(host, username, password, timeout=10) as switch:
    async for status in switch.poll(interval=5):
        for port in status.ports:
            print(port.number, port.rx_mbps, port.tx_mbps)
```

Polling yields immediately, then waits `interval` seconds after each consumed
snapshot. It stops on cancellation or an exception. Login is automatic on
the first read; expired sessions are renewed once per read. Concurrent calls
on one client are serialized to protect its authentication state.

### Units and directions

`negotiated_speed_mbps` is the physical link speed: 10, 100, 1000, 2500, or
10000 Mbps. It is `None` when disconnected, disabled, or the firmware has
not supplied a concrete speed. `duplex` is likewise `None` when unavailable.

`rx_bps` and `tx_bps` are the latest firmware traffic samples, in **bits per
second**, from the switch's perspective. `rx_mbps` and `tx_mbps` divide those
values by 1,000,000. These are the rates displayed on the switch's home page;
they are not cumulative byte counters or Python-measured transfer speeds.
Disabled and disconnected ports report zero traffic rates, matching the UI.
Polling more often does not force the firmware to resample its counters.

### Host, sessions, and errors

The host can be an IP address, hostname, or HTTP(S) origin including a port,
for example `http://switch.local:8080`. A bare hostname defaults to HTTP.
HTTPS uses normal certificate verification. To configure transport options
such as a custom CA, pass your own `aiohttp.ClientSession`:

```python
import aiohttp

async with aiohttp.ClientSession() as session:
    async with TLSE2109(host, username, password, session=session) as switch:
        status = await switch.get_status()
```

The caller owns a supplied session; the client does not close it. `close()`
releases local resources; it does not send a remote logout request. Use the
instance in a single asyncio event loop.

Failures raise `AuthenticationError`, `ConnectionError`, or `ProtocolError`,
all subclasses of `SwitchError`. `asyncio.CancelledError` propagates normally.
Unsupported data or speed codes raise an error instead of returning fabricated
measurements. A failed `async with` login closes any internally owned session.
