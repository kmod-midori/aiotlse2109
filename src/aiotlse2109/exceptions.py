"""Errors raised by the switch client."""


class SwitchError(Exception):
    """Base class for switch communication errors."""


class AuthenticationError(SwitchError):
    """Login failed, access was denied, or a session could not be renewed."""


class ConnectionError(SwitchError):
    """The switch could not be reached or returned an HTTP error."""


class ProtocolError(SwitchError):
    """The firmware returned an unsupported or malformed response."""
