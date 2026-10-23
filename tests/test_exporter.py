import asyncio
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from prometheus_client.parser import text_string_to_metric_families

from aiotlse2109 import TLSE2109, AuthenticationError, Duplex
from aiotlse2109._protocol import parse_status
from aiotlse2109.exporter import create_app, main

STATUS = parse_status((Path(__file__).parent / "fixtures" / "main.htm").read_text())


def samples(text):
    return {
        (sample.name, sample.labels.get("port")): sample
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


class ExporterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.switch = AsyncMock(spec=TLSE2109)
        self.switch.get_status.return_value = STATUS
        self.client = TestClient(TestServer(create_app(self.switch, timeout=0.05)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def scrape(self):
        response = await self.client.get("/metrics")
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("text/plain")
        return await response.text()

    async def test_metrics_and_units(self):
        body = await self.scrape()
        data = samples(body)
        assert data["tlse2109_up", None].value == 1
        assert data["tlse2109_scrape_duration_seconds", None].value >= 0
        assert data["tlse2109_info", None].labels == {
            "model": STATUS.device.model,
            "firmware": STATUS.device.firmware_version,
        }
        assert (
            data["tlse2109_port_negotiated_speed_bits_per_second", "1"].value == 2.5e9
        )
        assert data["tlse2109_port_receive_bits_per_second", "1"].value == 263_000
        assert data["tlse2109_port_transmit_bits_per_second", "1"].value == 6_259_000
        assert data["tlse2109_port_full_duplex", "1"].value == 1
        assert data["tlse2109_port_link_up", "2"].value == 0
        assert ("tlse2109_port_negotiated_speed_bits_per_second", "2") not in data
        assert ("tlse2109_port_full_duplex", "2") not in data
        assert len([key for key in data if key[0] == "tlse2109_port_enabled"]) == 9
        assert all(
            family.type == "gauge" for family in text_string_to_metric_families(body)
        )
        assert STATUS.device.mac_address not in body
        assert STATUS.device.ip_address not in body

    async def test_failure_drops_old_metrics_and_recovers(self):
        self.switch.get_status.side_effect = [
            STATUS,
            AuthenticationError("private-test-password"),
            STATUS,
        ]
        assert samples(await self.scrape())["tlse2109_up", None].value == 1
        with self.assertLogs("aiotlse2109.exporter", level="WARNING") as logs:
            body = await self.scrape()
        data = samples(body)
        assert data["tlse2109_up", None].value == 0
        assert len(data) == 2
        assert "private-test-password" not in body + "".join(logs.output)
        assert samples(await self.scrape())["tlse2109_up", None].value == 1

    async def test_timeout_cancels_collection(self):
        cancelled = asyncio.Event()

        async def slow_read():
            try:
                await asyncio.sleep(0.2)
                return STATUS
            except asyncio.CancelledError:
                cancelled.set()
                raise

        self.switch.get_status.side_effect = slow_read
        with self.assertLogs("aiotlse2109.exporter", level="WARNING"):
            body = await self.scrape()
        assert samples(body)["tlse2109_up", None].value == 0
        assert cancelled.is_set()

    async def test_startup_is_lazy_and_cleanup_closes_client(self):
        self.switch.get_status.assert_not_awaited()
        await self.client.close()
        self.switch.close.assert_awaited_once()

    async def test_half_duplex_and_disabled_ports(self):
        half = replace(STATUS.ports[0], negotiated_speed_mbps=10, duplex=Duplex.HALF)
        disabled = replace(STATUS.ports[1], enabled=False)
        self.switch.get_status.return_value = replace(
            STATUS,
            ports=(half, disabled, *STATUS.ports[2:]),
        )
        data = samples(await self.scrape())
        assert data["tlse2109_port_negotiated_speed_bits_per_second", "1"].value == 10e6
        assert data["tlse2109_port_full_duplex", "1"].value == 0
        assert data["tlse2109_port_enabled", "2"].value == 0


def test_cli_password_file_overrides_environment(tmp_path):
    password_file = tmp_path / "password"
    password_file.write_text("file-password\n")
    with (
        patch.dict("os.environ", {"SE2109_PASSWORD": "env-password"}, clear=True),
        patch(
            "sys.argv",
            [
                "exporter",
                "--host",
                "switch",
                "--username",
                "admin",
                "--password-file",
                str(password_file),
            ],
        ),
        patch("aiotlse2109.exporter.TLSE2109") as client,
        patch("aiotlse2109.exporter.web.run_app") as run,
    ):
        main()
    client.assert_called_once_with("switch", "admin", "file-password", timeout=10.0)
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 9109


def test_cli_environment_configuration():
    with (
        patch.dict(
            "os.environ",
            {
                "SE2109_HOST": "switch",
                "SE2109_USER": "admin",
                "SE2109_PASSWORD": "env-password",
            },
            clear=True,
        ),
        patch("sys.argv", ["exporter"]),
        patch("aiotlse2109.exporter.TLSE2109") as client,
        patch("aiotlse2109.exporter.web.run_app"),
    ):
        main()
    client.assert_called_once_with("switch", "admin", "env-password", timeout=10.0)
