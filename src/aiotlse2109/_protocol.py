"""Decode firmware data literals without evaluating JavaScript."""

import hashlib
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from .exceptions import ProtocolError
from .models import DeviceInfo, Duplex, Port, SwitchStatus

_KEY = "RDpbLfCPsJZ7fiv"
_ALPHABET = (
    "yLwVl0zKqws7LgKPRQ84Mdt708T1qQ3Ha7xv3H7NyU84p21BriUWBU43odz3iP4r"
    "BL3cD02KZciXTysVXiV8ngg6vL48rPJyAUw0HurW20xqxv9aYb4M9wK1Ae0wlro510"
    "qXeU07kV57fQMc8L6aLgMLwygtc0F10a0Dg70TOoouyFhdysuRMO51yY5ZlOZZLEal1"
    "h0t9YQW0Ko7oBwmCAHoic4HYbUyVeU3sfQ1xtXcPcf1aT303wAQhv66qzW"
)
_SPEEDS: dict[int, tuple[int | None, Duplex | None]] = {
    0: (None, None),
    1: (None, None),  # Firmware displays "auto", with no concrete link speed.
    2: (10, Duplex.HALF),
    3: (10, Duplex.FULL),
    4: (100, Duplex.HALF),
    5: (100, Duplex.FULL),
    6: (1000, Duplex.FULL),
    7: (2500, Duplex.FULL),
    8: (10000, Duplex.FULL),
}


def encode_password(password: str, encrypt_type: int = 0) -> str:
    """Match cryp_new.js securityEncode, or the firmware's MD5 mode."""
    if encrypt_type == 5:
        return hashlib.md5(password.encode(), usedforsecurity=False).hexdigest()
    if encrypt_type != 0:
        raise ProtocolError(f"Unsupported firmware password encoding: {encrypt_type}")
    # JavaScript charCodeAt indexes UTF-16 code units, not Unicode code points.
    raw = password.encode("utf-16-le", errors="surrogatepass")
    units = [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]
    return "".join(
        _ALPHABET[
            (
                (units[i] if i < len(units) else 187)
                ^ (ord(_KEY[i]) if i < len(_KEY) else 187)
            )
            % len(_ALPHABET)
        ]
        for i in range(max(len(units), len(_KEY)))
    )


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.inside = not any(name == "src" for name, _ in attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.inside = False
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.inside:
            self.parts.append(data)


def script_data(html: str) -> str:
    parser = _Scripts()
    parser.feed(html)
    return "".join(parser.parts)


def login_code(html: str) -> int | None:
    match = re.search(
        r"\bvar\s+logonInfo\s*=\s*new\s+Array\s*\(\s*(\d+)", script_data(html)
    )
    return int(match[1]) if match else None


def password_encoding(html: str) -> int:
    source = script_data(html)
    if not re.search(r"\bvar\s+encryptType\s*=", source):
        return 0
    return _integer(_variable(source, "encryptType"), "encryptType")


# Strings are matched first so their contents never get rewritten. Outside
# strings, the firmware differs from JSON only in keys and trailing commas.
_DATA_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|([A-Za-z_$][\w$]*)(?=\s*:)|,(?=\s*[}\]])')


def _json_token(match: re.Match[str]) -> str:
    if match[1] is not None:
        return json.dumps(match[1])
    return "" if match[0] == "," else match[0]


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Duplicate object key")
    return fields


_DECODER = json.JSONDecoder(object_pairs_hook=_unique_fields)


def _variable(source: str, name: str) -> Any:
    match = re.search(r"\bvar\s+" + re.escape(name) + r"\s*=\s*", source)
    if not match:
        raise ProtocolError(f"Missing firmware variable: {name}")
    try:
        normalized = _DATA_TOKEN.sub(_json_token, source[match.end() :])
        value, end = _DECODER.raw_decode(normalized)
        tail = normalized[end:].lstrip(" \t\r")
        if tail and not tail.startswith(";"):
            # Accept the firmware's semicolonless declarations, but not an
            # expression continued on the next line (such as "9\n+1").
            if not tail.startswith("\n") or (
                tail.strip() and not re.match(r"\s*var\s+", tail)
            ):
                raise ValueError("Expected end of assignment")
        return value
    except (ValueError, RecursionError) as exc:
        raise ProtocolError(f"Malformed firmware variable: {name}") from exc


def _integer(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ProtocolError(f"Invalid nonnegative integer: {name}")
    return value


def _flag(source: str, name: str) -> bool:
    value = _integer(_variable(source, name), name)
    if value not in (0, 1):
        raise ProtocolError(f"Invalid boolean flag: {name}")
    return bool(value)


def parse_status(html: str) -> SwitchStatus:
    source = script_data(html)
    count = _integer(_variable(source, "max_port_num"), "max_port_num")
    if count != 9:
        raise ProtocolError("Expected nine physical ports on a TL-SE2109")
    info = _variable(source, "info_ds")
    port_info = _variable(source, "port_info")
    if not isinstance(info, dict) or not isinstance(port_info, dict):
        raise ProtocolError("Expected device and port data objects")
    cloud_status = _flag(source, "cloud_status")
    nms_status = _flag(source, "nms_status")

    def text(name: str) -> str:
        value = info.get(name)
        if not isinstance(value, list) or not value or not isinstance(value[0], str):
            raise ProtocolError(f"Missing or invalid device field: {name}")
        return value[0]

    device = DeviceInfo(
        model=text("hardwareStr"),
        firmware_version=text("firmwareStr"),
        description=text("descriStr"),
        mac_address=text("macStr"),
        ip_address=text("ipStr"),
        netmask=text("netmaskStr"),
        gateway=text("gatewayStr"),
        dns_server=text("dnsStr"),
        uptime=text("workTime"),
        cloud_connected=cloud_status and nms_status,
    )
    if not device.model.startswith("TL-SE2109"):
        raise ProtocolError("The device does not identify itself as a TL-SE2109")

    columns = []
    for name in ("state", "spd_cfg", "spd_act", "port_type", "rx_rate", "tx_rate"):
        value = port_info.get(name)
        if not isinstance(value, list) or len(value) < count:
            raise ProtocolError(f"Missing or truncated port array: {name}")
        columns.append([_integer(item, name) for item in value[:count]])
    ports = []
    for number, (state, configured, actual, port_type, rx, tx) in enumerate(
        zip(*columns, strict=True), start=1
    ):
        if state not in (0, 1) or actual not in _SPEEDS or configured not in _SPEEDS:
            raise ProtocolError(f"Unsupported state or speed code for port {number}")
        enabled = state == 1
        link_up = enabled and actual != 0
        speed, duplex = _SPEEDS[actual] if link_up else (None, None)
        ports.append(
            Port(
                number=number,
                enabled=enabled,
                link_up=link_up,
                negotiated_speed_mbps=speed,
                duplex=duplex,
                # MainRpm.js divides rates by 1000 to display Mbps: raw is kbps.
                rx_bps=rx * 1000 if link_up else 0,
                tx_bps=tx * 1000 if link_up else 0,
                configured_speed_code=configured,
                port_type_code=port_type,
            )
        )
    return SwitchStatus(device, tuple(ports), datetime.now(UTC))
