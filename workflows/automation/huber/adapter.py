from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("workflows.automation.huber")


class HuberWorkflowAdapter:
    """Workflow-level wrapper around the existing Huber ThermostatConnection."""

    def __init__(self, port: Optional[str] = None, debug: bool = False, connection: Optional[Any] = None):
        if connection is None:
            from huberStuff.pyPbCmd.huber_adapter import ThermostatConnection
            connection = ThermostatConnection(port=port, debug=debug)
        self._connection = connection
        self.supports_pump_control = False

    def _log(self, event: str, **kwargs) -> None:
        logger.info(event, extra={"event": event, **kwargs})

    def _warn(self, event: str, **kwargs) -> None:
        logger.warning(event, extra={"event": event, **kwargs})

    def connect(self) -> bool:
        ok = self._connection.connect()
        self.supports_pump_control = hasattr(self._connection.thermostat, "set_pump_state")
        self._log(
            "huber_adapter_connect",
            ok=ok,
            port=self._connection.port,
            supports_pump_control=self.supports_pump_control,
            error_code=self._connection.last_error_code,
        )
        return ok

    def read_bath_temp(self) -> Optional[float]:
        value = self._connection.read_temperature()
        self._log("huber_adapter_read_bath_temp", value=value, error_code=self._connection.last_error_code)
        return value

    def read_setpoint(self) -> Optional[float]:
        value = self._connection.read_setpoint()
        self._log("huber_adapter_read_setpoint", value=value, error_code=self._connection.last_error_code)
        return value

    def set_setpoint(self, temp_c: float) -> bool:
        ok = self._connection.set_setpoint(temp_c)
        self._log("huber_adapter_set_setpoint", temp_c=temp_c, ok=ok, error_code=self._connection.last_error_code)
        return ok

    def set_pump_state(self, on_off: bool) -> bool:
        if hasattr(self._connection.thermostat, "set_pump_state"):
            ok = bool(self._connection.thermostat.set_pump_state(on_off))
            self.supports_pump_control = True
            self._log("huber_adapter_set_pump_state", on_off=on_off, ok=ok)
            return ok

        self.supports_pump_control = False
        self._warn("huber_adapter_pump_control_unsupported", requested_state=on_off)
        return False

    def safe_standby(self, standby_temp_c: float, pump_state: bool) -> bool:
        setpoint_ok = self.set_setpoint(standby_temp_c)
        pump_ok = self.set_pump_state(pump_state)
        ok = setpoint_ok and (pump_ok or not self.supports_pump_control)
        self._log(
            "huber_adapter_safe_standby",
            standby_temp_c=standby_temp_c,
            pump_state=pump_state,
            setpoint_ok=setpoint_ok,
            pump_ok=pump_ok,
            ok=ok,
        )
        return ok

    def close(self) -> None:
        self._connection.close()
        self._log("huber_adapter_close", port=self._connection.port)
