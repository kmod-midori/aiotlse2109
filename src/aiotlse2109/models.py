"""Immutable snapshots. All speeds use decimal SI units."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PortStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    DISABLED = "disabled"


class Duplex(StrEnum):
    FULL = "full"
    HALF = "half"


@dataclass(frozen=True, slots=True)
class Port:
    """One physical port, numbered from 1 as on the switch chassis.

    Receive/transmit directions are from the switch's perspective. Traffic
    rates are the firmware's latest sample, not a lifetime byte counter.
    Negotiated speed and duplex are None when no link speed is available.
    """

    number: int
    enabled: bool
    link_up: bool
    negotiated_speed_mbps: int | None
    duplex: Duplex | None
    rx_bps: int
    tx_bps: int
    configured_speed_code: int
    port_type_code: int

    @property
    def status(self) -> PortStatus:
        if not self.enabled:
            return PortStatus.DISABLED
        return PortStatus.UP if self.link_up else PortStatus.DOWN

    @property
    def rx_mbps(self) -> float:
        return self.rx_bps / 1_000_000

    @property
    def tx_mbps(self) -> float:
        return self.tx_bps / 1_000_000


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    model: str
    firmware_version: str
    description: str
    mac_address: str
    ip_address: str
    netmask: str
    gateway: str
    dns_server: str
    uptime: str
    cloud_connected: bool


@dataclass(frozen=True, slots=True)
class SwitchStatus:
    device: DeviceInfo
    ports: tuple[Port, ...]
    sampled_at: datetime

    def port(self, number: int) -> Port:
        """Look up a physical port using its 1-based chassis number."""
        if type(number) is not int or not 1 <= number <= len(self.ports):
            raise ValueError(f"Port number must be between 1 and {len(self.ports)}")
        return self.ports[number - 1]
