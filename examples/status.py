"""Run with: uv run --env-file .env python examples/status.py."""

import asyncio
import os

from aiotlse2109 import TLSE2109


async def main() -> None:
    async with TLSE2109(
        os.environ["SE2109_HOST"],
        os.environ["SE2109_USER"],
        os.environ["SE2109_PASSWORD"],
    ) as switch:
        status = await switch.get_status()
        print(f"{status.device.model} — {status.device.firmware_version}")
        print("Port  Status     Link Mbps    RX Mbps    TX Mbps")
        for port in status.ports:
            speed = str(port.negotiated_speed_mbps or "—")
            print(
                f"{port.number:>4}  {port.status.value:<8}  {speed:>9}  "
                f"{port.rx_mbps:>9.3f}  {port.tx_mbps:>9.3f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
