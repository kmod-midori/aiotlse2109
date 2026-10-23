import asyncio
import unittest
from pathlib import Path

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiotlse2109 import TLSE2109, AuthenticationError, ConnectionError, ProtocolError

HTML = (Path(__file__).parent / "fixtures" / "main.htm").read_text()


def logon(code=0):
    return f"<script>var logonInfo = new Array({code},0,0);</script>"


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.login_count = 0
        self.read_count = 0
        self.expire_count = 0
        self.login_error = 0
        self.cookie_enabled = True
        self.root_cookie = False
        self.login_html = None
        self.read_status = 200
        self.read_delay = 0
        self.refresh_cookie = False
        self.read_started = asyncio.Event()
        self.encoding = 0
        self.html = HTML
        self.cookie = ""
        app = web.Application()
        app.router.add_get("/", self.root)
        app.router.add_post("/logon.cgi", self.login)
        app.router.add_get("/MainRpm.htm", self.status)
        self.server = TestServer(app)
        self.addAsyncCleanup(self.server.close)
        await self.server.start_server()
        self.host = str(self.server.make_url("/")).rstrip("/")
        self.client = TLSE2109(self.host, "admin", "test-password")
        self.addAsyncCleanup(self.client.close)

    async def root(self, request):
        response = web.Response(
            text=logon() + f"<script>var encryptType = {self.encoding};</script>"
        )
        if self.root_cookie:
            response.set_cookie("SessionID", "unauthenticated", path="/")
        return response

    async def login(self, request):
        self.login_count += 1
        form = await request.post()
        assert form["username"] == "admin"
        expected = (
            "77VtUtxvyPU0wwK"
            if self.encoding == 0
            else "dfb450efddbb5387197c84460623675b"
        )
        assert form["password"] == expected
        assert form["logon"] == "登录"
        response = web.Response(
            text=logon(self.login_error) if self.login_html is None else self.login_html
        )
        if not self.login_error and self.cookie_enabled:
            self.cookie = f"session-{self.login_count}"
            response.set_cookie("SessionID", self.cookie, path="/", httponly=True)
        return response

    async def status(self, request):
        self.read_count += 1
        self.read_started.set()
        assert request.cookies.get("SessionID") == self.cookie
        if self.expire_count:
            self.expire_count -= 1
            return web.Response(text=logon(5))
        if self.read_delay:
            await asyncio.sleep(self.read_delay)
        response = web.Response(text=self.html, status=self.read_status)
        if self.refresh_cookie:
            self.cookie += "-refreshed"
            response.set_cookie("SessionID", self.cookie, path="/")
        return response

    async def test_auto_login_and_read_ip_host(self):
        status = await self.client.get_status()
        assert len(status.ports) == 9
        assert status.port(1).negotiated_speed_mbps == 2500
        assert self.login_count == self.read_count == 1
        assert (await self.client.get_port(9)).tx_mbps == 1.351
        assert len(await self.client.get_ports()) == 9
        assert self.login_count == 1

    async def test_context_manager_closes_owned_session(self):
        async with self.client:
            await self.client.get_status()
            session = self.client._session
        assert session.closed

    async def test_login_failure_closes_context(self):
        self.login_error = 1
        with self.assertRaisesRegex(AuthenticationError, "Invalid username"):
            async with self.client:
                self.fail("Invalid credentials were accepted")
        assert self.client._session is None
        assert self.read_count == 0

    async def test_missing_cookie_is_authentication_failure(self):
        self.cookie_enabled = False
        with self.assertRaises(AuthenticationError):
            await self.client.get_status()
        assert self.read_count == 0

    async def test_root_cookie_does_not_count_as_login_cookie(self):
        self.root_cookie = True
        self.cookie_enabled = False
        with self.assertRaises(AuthenticationError):
            await self.client.get_status()
        assert self.read_count == 0

    async def test_malformed_login_response_is_rejected(self):
        self.login_html = "<html>unexpected response</html>"
        with self.assertRaises(ProtocolError):
            await self.client.get_status()
        assert self.read_count == 0
        assert self.client._session_id is None

    async def test_session_cookie_refresh_is_used_on_the_next_read(self):
        self.refresh_cookie = True
        await self.client.get_status()
        await self.client.get_status()
        assert self.login_count == 1

    async def test_expired_session_is_renewed_once(self):
        self.expire_count = 1
        assert len((await self.client.get_status()).ports) == 9
        assert self.login_count == self.read_count == 2

    async def test_persistent_expiry_is_bounded(self):
        self.expire_count = 10
        with self.assertRaises(AuthenticationError):
            await self.client.get_status()
        assert self.login_count == self.read_count == 2

    async def test_http_forbidden_is_bounded(self):
        self.read_status = 403
        with self.assertRaises(AuthenticationError):
            await self.client.get_status()
        assert self.login_count == self.read_count == 2

    async def test_server_error_does_not_trigger_login_loop(self):
        self.read_status = 500
        with self.assertRaisesRegex(ConnectionError, "HTTP 500"):
            await self.client.get_status()
        assert self.login_count == self.read_count == 1

    async def test_concurrent_reads_share_one_login(self):
        snapshots = await asyncio.gather(*(self.client.get_status() for _ in range(8)))
        assert len(snapshots) == self.read_count == 8
        assert self.login_count == 1

    async def test_external_session_is_not_closed_and_accepts_ip_cookies(self):
        async with aiohttp.ClientSession() as session:
            async with TLSE2109(
                self.host, "admin", "test-password", session=session
            ) as c:
                assert len(await c.get_ports()) == 9
            assert not session.closed

    async def test_malformed_response_does_not_trigger_login_loop(self):
        self.html = "<html>not firmware data</html>"
        with self.assertRaises(ProtocolError):
            await self.client.get_status()
        assert self.login_count == self.read_count == 1

    async def test_timeout(self):
        self.read_delay = 0.3
        async with TLSE2109(self.host, "admin", "test-password", timeout=0.1) as c:
            with self.assertRaises(ConnectionError):
                await c.get_status()

    async def test_cancellation_propagates_and_lock_is_released(self):
        await self.client.login()
        self.read_delay = 0.1
        task = asyncio.create_task(self.client.get_status())
        await asyncio.wait_for(self.read_started.wait(), timeout=1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.read_delay = 0
        assert len(await self.client.get_ports()) == 9

    async def test_polling(self):
        stream = self.client.poll(interval=0.001)
        try:
            for _ in range(2):
                assert len((await anext(stream)).ports) == 9
            assert self.read_count == 2
        finally:
            await stream.aclose()

    async def test_invalid_polling_interval(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                await anext(self.client.poll(value))
        assert self.login_count == 0

    async def test_invalid_port_is_rejected_before_network_io(self):
        for number in (0, -1, 10, True, 1.5, "1"):
            with self.assertRaises(ValueError):
                await self.client.get_port(number)
        assert self.login_count == 0

    async def test_md5_firmware_mode(self):
        self.encoding = 5
        assert len(await self.client.get_ports()) == 9

    async def test_invalid_encoding_is_rejected_before_submitting_credentials(self):
        for encoding in (99, '"5"'):
            self.encoding = encoding
            with self.assertRaises(ProtocolError):
                await self.client.get_status()
        assert self.login_count == 0


class ConfigTests(unittest.TestCase):
    def test_invalid_origins(self):
        for host in (
            "",
            "ftp://switch",
            "http://switch/path",
            "http://user:pass@switch",
            "http://switch?token=secret",
            "http://switch/#fragment",
            "http://switch:invalid",
            "http://switch:99999",
        ):
            with self.assertRaises(ValueError):
                TLSE2109(host, "admin", "password")

    def test_invalid_timeout_and_credentials(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                TLSE2109("switch", "admin", "password", timeout=timeout)
        for username, password in (("", "password"), ("admin", "")):
            with self.assertRaises(ValueError):
                TLSE2109("switch", username, password)
