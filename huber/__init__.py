"""Standalone Huber device clients.

Use `huber.legacy_pp` for old Huber thermostats that speak the legacy
PP/text serial protocol, or `huber.pb` for the PB `{M...}`/`{S...}` route.
"""

from .protocol import HUBER_PROTOCOL_PB, HUBER_PROTOCOL_PP, HUBER_PROTOCOLS, create_connection, normalize_protocol

__all__ = [
    "HUBER_PROTOCOL_PB",
    "HUBER_PROTOCOL_PP",
    "HUBER_PROTOCOLS",
    "create_connection",
    "normalize_protocol",
]
