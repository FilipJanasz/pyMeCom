from __future__ import annotations

from typing import Final

HUBER_PROTOCOL_PP: Final[str] = "pp"
HUBER_PROTOCOL_PB: Final[str] = "pb"
HUBER_PROTOCOLS: Final[tuple[str, str]] = (HUBER_PROTOCOL_PP, HUBER_PROTOCOL_PB)


def normalize_protocol(protocol: str | None) -> str:
    value = (protocol or HUBER_PROTOCOL_PP).strip().lower().replace("_", "-")
    aliases = {
        "": HUBER_PROTOCOL_PP,
        "legacy": HUBER_PROTOCOL_PP,
        "legacy-pp": HUBER_PROTOCOL_PP,
        "pp-text": HUBER_PROTOCOL_PP,
        "text": HUBER_PROTOCOL_PP,
        "pb-hex": HUBER_PROTOCOL_PB,
    }
    value = aliases.get(value, value)
    if value not in HUBER_PROTOCOLS:
        raise ValueError(f"unsupported Huber protocol {protocol!r}; expected one of {', '.join(HUBER_PROTOCOLS)}")
    return value


def connection_class_for_protocol(protocol: str | None):
    protocol = normalize_protocol(protocol)
    if protocol == HUBER_PROTOCOL_PB:
        from huber.pb import ThermostatConnection
    else:
        from huber.legacy_pp import ThermostatConnection
    return ThermostatConnection


def create_connection(*, protocol: str | None = None, port: str | None = None, debug: bool = False):
    connection_class = connection_class_for_protocol(protocol)
    return connection_class(port=port, debug=debug)
