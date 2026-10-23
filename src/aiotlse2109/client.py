"""aiohttp transport for the TL-SE2109's local web management interface."""

import asyncio
import math
from collections.abc import AsyncIterator
from types import TracebackType
from urllib.parse import urlsplit

import aiohttp

from ._protocol import encode_password, login_code, parse_status, password_encoding
from .exceptions import AuthenticationError, ConnectionError, ProtocolError
from .models import Port, SwitchStatus

_LOGIN_ERRORS = {
    1: "Invalid username or password",
    2: "This user is not allowed to log in",
    3: "The switch's simultaneous-login limit has been reached",
    4: "The switch's simultaneous-login limit has been reached",
    5: "The switch session has expired",
}


class TLSE2109:
    """Read switch status asynchronously; host may be an IP, hostname, or URL.

    Login is automatic on the first read and is renewed once on expiration.
    A supplied aiohttp session remains owned by the caller. Instances should
    be used in one asyncio event loop and closed, preferably via async with.
    Host and credentials are explicit constructor arguments.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        base = host.strip()
        if "://" not in base:
            base = "http://" + base
        url = urlsplit(base)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Host must be an HTTP(S) origin without path or credentials"
            )
        try:
            _ = url.port
        except ValueError as exc:
            raise ValueError("Invalid host port") from exc
        if not username or not password:
            raise ValueError("Username and password must be nonempty")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be finite and positive")
        self._base_url = base.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._owns_session = session is None
        self._session_id: str | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "TLSE2109":
        try:
            await self.login()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Release local resources without sending a remote logout request."""
        async with self._lock:
            if self._owns_session and self._session is not None:
                await self._session.close()
                self._session = None
            self._session_id = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
    ) -> tuple[str, str | None]:
        if self._session is None:
            # SessionID is sent explicitly: aiohttp's default jar rejects IP hosts.
            self._session = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
        if self._session.closed:
            raise ConnectionError("The caller's HTTP session is closed")
        try:
            async with self._session.request(
                method,
                self._base_url + path,
                data=data,
                cookies={"SessionID": self._session_id} if self._session_id else None,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                if response.status in (401, 403):
                    raise AuthenticationError("Switch denied access")
                if 300 <= response.status < 400:
                    location = response.headers.get("Location", "")
                    if urlsplit(location).path.lower() in ("/", "/logon.htm"):
                        raise AuthenticationError("Switch redirected to login")
                    raise ProtocolError("Unexpected HTTP redirect from switch")
                if response.status != 200:
                    raise ConnectionError(f"Switch returned HTTP {response.status}")
                cookie = response.cookies.get("SessionID")
                text = await response.text(encoding="utf-8", errors="replace")
                return text, cookie.value if cookie is not None else None
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ConnectionError("Could not communicate with the switch") from exc

    async def _login(self) -> None:
        self._session_id = None
        page, _ = await self._request("GET", "/")
        encoded = encode_password(self._password, password_encoding(page))
        page, session_id = await self._request(
            "POST",
            "/logon.cgi",
            data={
                "username": self._username,
                "password": encoded,
                "logon": "登录",
            },
        )
        code = login_code(page)
        if code is None:
            raise ProtocolError("Login response did not contain a result code")
        if code != 0:
            raise AuthenticationError(
                _LOGIN_ERRORS.get(code, f"Login failed (code {code})")
            )
        if not session_id:
            raise AuthenticationError("Login response did not establish a SessionID")
        self._session_id = session_id

    async def login(self) -> None:
        """Explicitly establish a new authenticated session."""
        async with self._lock:
            await self._login()

    async def get_status(self) -> SwitchStatus:
        """Read device information and all nine ports in one HTTP snapshot."""
        async with self._lock:
            if self._session_id is None:
                await self._login()
            try:
                return await self._read_status()
            except AuthenticationError:
                await self._login()
                return await self._read_status()

    async def _read_status(self) -> SwitchStatus:
        try:
            page, session_id = await self._request("GET", "/MainRpm.htm")
            if login_code(page) is not None:
                raise AuthenticationError("Switch returned a login page")
            status = parse_status(page)
            if session_id is not None:
                self._session_id = session_id or None
            return status
        except AuthenticationError:
            self._session_id = None
            raise

    async def get_ports(self) -> tuple[Port, ...]:
        """Read the current status and rates of all ports."""
        return (await self.get_status()).ports

    async def get_port(self, number: int) -> Port:
        """Read a single port by its 1-based physical number (1–9)."""
        if type(number) is not int or not 1 <= number <= 9:
            raise ValueError("Port number must be between 1 and 9")
        return (await self.get_status()).port(number)

    async def poll(self, interval: float = 5.0) -> AsyncIterator[SwitchStatus]:
        """Yield snapshots until cancelled or an error occurs.

        The interval is the delay after each consumed snapshot. No background
        tasks are created; cancellation follows normal asyncio semantics.
        """
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Polling interval must be finite and positive")
        while True:
            yield await self.get_status()
            await asyncio.sleep(interval)
