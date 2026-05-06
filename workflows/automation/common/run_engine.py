from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .run_config import RunConfig, UnifiedStep




def _ole_automation_date(dt: datetime) -> float:
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) - epoch).total_seconds() / 86400.0


def build_time_columns(now: datetime) -> Dict[str, Any]:
    return {
        "Time": now.strftime("%H:%M:%S"),
        "Milliseconds": int(now.microsecond / 1000),
        "OLE Automation Date": _ole_automation_date(now),
    }
class EngineState(str, Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    RUNNING_STEP = "RUNNING_STEP"
    STOPPING = "STOPPING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class LegacyPowerPolicy(str, Enum):
    STRICT = "strict"
    ALLOW_ZERO_POWER = "allow_zero_power"
    LEGACY_VOLTAGE_MODE = "legacy_voltage_mode"


@dataclass
class EnginePaths:
    csv_path: Path
    metadata_path: Path


class DualDeviceRunEngine:
    def __init__(
        self,
        tec_adapter: Any,
        bath_adapter: Any,
        output_directory: str | Path,
        sample_hz: float = 2.0,
    ):
        self.tec_adapter = tec_adapter
        self.bath_adapter = bath_adapter
        self.output_directory = Path(output_directory)
        self.sample_hz = sample_hz
        self.state = EngineState.IDLE
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(
        self,
        run_config: RunConfig,
        *,
        input_origin: str = "unified_steps",
        legacy_power_policy: str = LegacyPowerPolicy.STRICT.value,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        row_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> EnginePaths:
        started_at = datetime.now(timezone.utc)
        stem = (run_config.run_name or started_at.strftime("%Y%m%d_%H%M%S")).replace(" ", "_")
        self.output_directory.mkdir(parents=True, exist_ok=True)
        paths = EnginePaths(
            csv_path=self.output_directory / f"run_timeline_{stem}.csv",
            metadata_path=self.output_directory / f"run_timeline_{stem}.metadata.json",
        )
        metadata: Dict[str, Any] = {
            "started_at": started_at.isoformat(),
            "engine_state": self.state.value,
            "safety": {
                "tec_power_w_on_stop": run_config.safety.tec_power_w_on_stop,
                "bath_standby_setpoint_c": run_config.safety.bath_standby_setpoint_c,
                "pump_on_in_safe_state": run_config.safety.pump_on_in_safe_state,
            },
            "connectivity": {},
            "capabilities": {},
            "events": [],
            "legacy_interpretation": {
                "input_origin": input_origin,
                "policy": legacy_power_policy,
                "warnings": [],
            },
        }

        def emit(event: str, **extra: Any) -> None:
            record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "state": self.state.value, **extra}
            metadata["events"].append(record)
            if event_callback:
                event_callback(record)

        try:
            self._set_state(EngineState.CONNECTING, emit)
            self._check_legacy_policy(run_config, input_origin, legacy_power_policy, metadata, emit)

            if not self.tec_adapter.connect():
                raise RuntimeError("TEC adapter connect() returned False")
            if not self.bath_adapter.connect():
                raise RuntimeError("Bath adapter connect() returned False")

            metadata["connectivity"] = {"tec": True, "bath": True}
            metadata["capabilities"] = {
                "bath_supports_pump_control": bool(getattr(self.bath_adapter, "supports_pump_control", False)),
                "tec_supports_legacy_voltage_mode": bool(getattr(self.tec_adapter, "supports_legacy_voltage_mode", False)),
            }

            interval = 1.0 / max(self.sample_hz, 0.1)
            fields = [
                "Time",
                "Milliseconds",
                "OLE Automation Date",
                "engine_state",
                "step_index",
                "step_name",
                "bath_setpoint_c",
                "tec_power_w",
                "tec_voltage_v",
                "tec_current_a",
                "bath_temp_c",
                "bath_current_setpoint_c",
                "tec_actual_power_w",
            ]

            with open(paths.csv_path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()

                for step_index, step in enumerate(run_config.steps):
                    self._set_state(EngineState.RUNNING_STEP, emit, step_index=step_index, step_name=step.name)
                    self._apply_step(step, legacy_power_policy)

                    deadline = time.monotonic() + step.duration_s
                    while time.monotonic() < deadline:
                        if self._stop_requested:
                            self._set_state(EngineState.STOPPING, emit)
                            emit("stop_requested")
                            self._run_safety_cleanup(run_config, metadata, emit)
                            self._set_state(EngineState.COMPLETED, emit)
                            self._write_metadata(paths.metadata_path, metadata)
                            return paths
                        row = self._sample_row(step_index, step)
                        writer.writerow(row)
                        handle.flush()
                        if row_callback:
                            row_callback(row)
                        time.sleep(interval)

            self._run_safety_cleanup(run_config, metadata, emit)
            self._set_state(EngineState.COMPLETED, emit)
        except Exception as exc:
            self._set_state(EngineState.ERROR, emit, error=str(exc))
            metadata["error"] = str(exc)
            self._run_safety_cleanup(run_config, metadata, emit)
        finally:
            self.tec_adapter.close()
            self.bath_adapter.close()
            self._write_metadata(paths.metadata_path, metadata)
        return paths

    def _set_state(self, state: EngineState, emit: Callable[..., None], **extra: Any) -> None:
        self.state = state
        emit("state_transition", next_state=state.value, **extra)

    def _apply_step(self, step: UnifiedStep, legacy_power_policy: str) -> None:
        if step.bath_setpoint_c is not None:
            self.bath_adapter.set_setpoint(step.bath_setpoint_c)
        has_tec_request = step.tec_power_w is not None or step.tec_voltage_v is not None or step.tec_current_a is not None
        if not has_tec_request:
            return
        tec_power_w = float(step.tec_power_w or 0.0)
        if legacy_power_policy == LegacyPowerPolicy.LEGACY_VOLTAGE_MODE.value and hasattr(self.tec_adapter, "apply_legacy_step"):
            self.tec_adapter.apply_legacy_step(step)
            return
        if tec_power_w == 0.0 and step.tec_voltage_v is None and step.tec_current_a is None and hasattr(self.tec_adapter, "set_voltage_current"):
            # Belt-and-suspenders zeroing for unified runs:
            # clear explicit V/I setpoints before disabling output to avoid residual bias.
            self.tec_adapter.set_voltage_current(0.0, 0.0)
            self.tec_adapter.set_power(0.0)
            return
        if (step.tec_voltage_v is not None or step.tec_current_a is not None) and hasattr(self.tec_adapter, "set_voltage_current"):
            voltage_v = float(step.tec_voltage_v or 0.0)
            current_a = float(step.tec_current_a or 0.0)
            self.tec_adapter.set_voltage_current(voltage_v, current_a)
            return
        self.tec_adapter.set_power(tec_power_w)

    def _sample_row(self, step_index: int, step: UnifiedStep) -> Dict[str, Any]:
        row = build_time_columns(datetime.now(timezone.utc))
        row.update(
            {
                "engine_state": self.state.value,
                "step_index": step_index,
                "step_name": step.name,
                "bath_setpoint_c": step.bath_setpoint_c,
                "tec_power_w": step.tec_power_w,
                "tec_voltage_v": step.tec_voltage_v,
                "tec_current_a": step.tec_current_a,
                "bath_temp_c": self.bath_adapter.read_bath_temp(),
                "bath_current_setpoint_c": self.bath_adapter.read_setpoint(),
                "tec_actual_power_w": self.tec_adapter.read_actual_power(),
            }
        )
        return row

    def _run_safety_cleanup(self, run_config: RunConfig, metadata: Dict[str, Any], emit: Callable[..., None]) -> None:
        emit("safety_cleanup_start")
        safety_actions: List[Dict[str, Any]] = metadata.setdefault("safety_actions", [])

        self.tec_adapter.safe_output(run_config.safety.tec_power_w_on_stop)
        safety_actions.append({"action": "tec_safe_output", "power_w": run_config.safety.tec_power_w_on_stop})

        standby_ok = self.bath_adapter.set_setpoint(run_config.safety.bath_standby_setpoint_c)
        safety_actions.append({"action": "bath_standby_setpoint", "setpoint_c": run_config.safety.bath_standby_setpoint_c, "ok": standby_ok})

        if getattr(self.bath_adapter, "supports_pump_control", False):
            pump_ok = self.bath_adapter.set_pump_state(run_config.safety.pump_on_in_safe_state)
            safety_actions.append({"action": "bath_pump_safe_state", "pump_on": run_config.safety.pump_on_in_safe_state, "ok": pump_ok})
        else:
            safety_actions.append({"action": "bath_pump_safe_state", "pump_on": run_config.safety.pump_on_in_safe_state, "ok": False, "reason": "unsupported"})
            emit("pump_safe_state_skipped", reason="unsupported")

        emit("safety_cleanup_complete")

    def _check_legacy_policy(self, run_config: RunConfig, input_origin: str, policy: str, metadata: Dict[str, Any], emit: Callable[..., None]) -> None:
        if input_origin != "legacy_power_schedule":
            return
        ambiguous = [
            idx
            for idx, step in enumerate(run_config.steps)
            if (step.tec_power_w or 0.0) == 0.0 and getattr(step, "_legacy_nonzero_intent", False)
        ]
        if not ambiguous:
            return
        warning = f"Detected legacy zero-power ambiguity at steps {ambiguous}"
        metadata["legacy_interpretation"]["warnings"].append(warning)
        emit("legacy_zero_power_ambiguity", warning=warning, steps=ambiguous)
        if policy == LegacyPowerPolicy.STRICT.value:
            raise RuntimeError(f"{warning}; strict policy blocks run start")

    def _write_metadata(self, path: Path, metadata: Dict[str, Any]) -> None:
        metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
        metadata["engine_state"] = self.state.value
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
            handle.write("\n")
