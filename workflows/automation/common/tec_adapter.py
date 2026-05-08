from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from mecom.calibration import CalibrationStep, SafeChannelController
from .live_logger import LiveLoggerConfig, LiveLogger


@dataclass
class TecPowerAdapter:
    """Run-engine adapter for TEC power operations via existing MeCom workflow primitives."""

    config: LiveLoggerConfig

    def __post_init__(self) -> None:
        self._session_manager = None
        self._session = None
        self._controller: Optional[SafeChannelController] = None
        self._logger = LiveLogger(self.config)

    def connect(self) -> bool:
        self._session_manager, _ = self._logger._open_session()
        self._session = self._session_manager.__enter__()
        channel_config = type(
            "UnifiedChannelConfig",
            (),
            {
                "address": self.config.address,
                "channel": self.config.channel,
                "enable_output_value": 1,
                "disable_output_value": 0,
                "output_setpoint_parameters": {},
                "allow_named_voltage_current_fallback": True,
                "output_stage_input_selection": None,
            },
        )()
        self._controller = SafeChannelController(self._session, channel_config)
        return True

    def set_power(self, power_w: float) -> None:
        if self._controller is None:
            raise RuntimeError("TEC adapter not connected")
        if float(power_w) != 0.0:
            raise RuntimeError(
                "TEC power setpoint writes are not supported by this workflow. "
                "Provide tec_voltage_v and tec_current_a instead; tec_power_w is used for preview/logging."
            )
        self._controller.apply_step(
            CalibrationStep(
                name="unified_zero_power",
                power=0.0,
                dwell_seconds=1,
                set_voltage=0.0,
                set_current=0.0,
                enable_output=False,
            )
        )

    def set_voltage_current(self, voltage_v: float, current_a: float) -> None:
        if self._controller is None:
            raise RuntimeError("TEC adapter not connected")
        self._controller.apply_step(
            CalibrationStep(
                name="unified_step_voltage_current",
                power=0.0,
                dwell_seconds=1,
                set_voltage=float(voltage_v),
                set_current=float(current_a),
                enable_output=bool(voltage_v != 0.0 or current_a != 0.0),
            )
        )

    def read_actual_power(self) -> Any:
        if self._session is None:
            return None
        return self._session.get_parameter(parameter_name="Actual Output Power", address=self.config.address, parameter_instance=self.config.channel)

    def safe_output(self, power_w: float = 0.0) -> None:
        # Hardware-safe shutdown uses the known-working voltage/current path.
        self.set_voltage_current(0.0, 0.0)
        self.set_power(0.0)

    def close(self) -> None:
        if self._session_manager is not None:
            self._session_manager.__exit__(None, None, None)
            self._session_manager = None
            self._session = None
            self._controller = None
