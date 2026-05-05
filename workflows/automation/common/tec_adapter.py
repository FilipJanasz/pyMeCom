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
        self._controller.apply_step(
            CalibrationStep(
                name="unified_step",
                power=float(power_w),
                dwell_seconds=1,
                set_voltage=0.0,
                set_current=0.0,
                enable_output=bool(power_w != 0.0),
            )
        )

    def read_actual_power(self) -> Any:
        if self._session is None:
            return None
        return self._session.get_parameter(parameter_name="Actual Output Power", address=self.config.address, parameter_instance=self.config.channel)

    def safe_output(self, power_w: float = 0.0) -> None:
        self.set_power(power_w)

    def close(self) -> None:
        if self._session_manager is not None:
            self._session_manager.__exit__(None, None, None)
            self._session_manager = None
            self._session = None
            self._controller = None
