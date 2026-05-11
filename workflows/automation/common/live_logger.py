from __future__ import annotations

import csv
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mecom.calibration import CalibrationStep, SafeChannelController
from mecom.mecom import MeComSerial, MeComTcp

from .logging_io import flush_csv_row

LOGGER = logging.getLogger(__name__)


def ole_automation_date(dt: datetime) -> float:
    epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) - epoch).total_seconds() / 86400.0


def build_time_columns(now: datetime) -> Dict[str, Any]:
    return {
        "Time": now.strftime("%H:%M:%S"),
        "Milliseconds": int(now.microsecond / 1000),
        "OLE Automation Date": ole_automation_date(now),
    }


def autodetect_serial_port(port_hint: Optional[str] = None) -> Optional[str]:
    try:
        from serial.tools import list_ports
    except Exception:
        return None
    ports = list(list_ports.comports())
    if not ports:
        return None
    # Keep selection deterministic and Windows-friendly (COMx first, then name sort)
    ports.sort(key=lambda p: (0 if str(p.device).upper().startswith("COM") else 1, str(p.device)))
    if port_hint:
        hint = port_hint.strip().lower()
        if hint:
            for port in ports:
                haystack = " ".join(
                    [
                        str(getattr(port, "device", "") or ""),
                        str(getattr(port, "name", "") or ""),
                        str(getattr(port, "description", "") or ""),
                        str(getattr(port, "manufacturer", "") or ""),
                        str(getattr(port, "hwid", "") or ""),
                    ]
                ).lower()
                if hint in haystack:
                    return str(port.device)
    return str(ports[0].device)


@dataclass
class LiveParameterSpec:
    key: str
    label: str
    parameter_name: Optional[str] = None
    parameter_id: Optional[int] = None
    parameter_format: Optional[str] = None
    instance: int = 1
    value: Optional[Any] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiveParameterSpec":
        return cls(**data)


def default_live_parameters(channel: int = 1) -> List[LiveParameterSpec]:
    return [
        LiveParameterSpec(f"ch{channel}_act_i", f"1020.{channel}: CH{channel} Act I", parameter_id=1020, parameter_format="FLOAT32", instance=channel),
        LiveParameterSpec(f"ch{channel}_act_u", f"1021.{channel}: CH{channel} Act U", parameter_id=1021, parameter_format="FLOAT32", instance=channel),
        LiveParameterSpec(f"ch{channel}_act_p", f"1022.{channel}: CH{channel} Act P", parameter_name="Actual Output Power", instance=channel),
        LiveParameterSpec("lr1_temp", "1044.1: LR1 Temp", parameter_id=1044, parameter_format="FLOAT32", instance=1),
        LiveParameterSpec("diff_voltage_1", "1046.1: Differential Voltage", parameter_id=1046, parameter_format="FLOAT32", instance=1),
        LiveParameterSpec("diff_voltage_2", "1046.2: Differential Voltage", parameter_id=1046, parameter_format="FLOAT32", instance=2),
    ]


UNIFIED_STEP_KEYS = {
    "bath_setpoint_c",
    "tec_power_w",
    "tec_voltage_v",
    "tec_current_a",
    "duration_s",
    "progression_mode",
    "stability_band_c",
    "stability_hold_s",
    "stability_timeout_s",
}
UNIFIED_SAFETY_KEYS = {"tec_power_w_on_stop", "bath_standby_setpoint_c", "pump_on_in_safe_state"}


def looks_like_unified_run_config(content: Dict[str, Any]) -> bool:
    """Return True for JSON that uses the shared step-based run shape.

    Older TEC-only calibration files may also have a top-level ``steps`` array, so
    do not classify a file as shared/unified unless the steps or safety block
    include fields from the shared TEC/Huber schema.
    """
    steps = content.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    if any(isinstance(step, dict) and (UNIFIED_STEP_KEYS & set(step)) for step in steps):
        return True
    safety = content.get("safety")
    return isinstance(safety, dict) and bool(UNIFIED_SAFETY_KEYS & set(safety))


def legacy_tec_steps_to_power_schedule(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map shared/unified or older TEC ``steps`` entries into TEC schedule entries.

    Steps that only request Huber/bath actions are skipped so TEC-only runs can
    load shared JSON files while ignoring devices that are not present.
    """
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return []
    default_dwell = data.get("dwell_seconds_default", 0.0)
    converted: List[Dict[str, Any]] = []
    for idx, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            continue
        has_tec_request = any(key in step for key in ("power", "set_voltage", "set_current", "tec_power_w", "tec_voltage_v", "tec_current_a"))
        if not has_tec_request:
            continue
        duration = step.get("duration_seconds", step.get("dwell_seconds", step.get("duration_s", default_dwell)))
        converted.append(
            {
                "name": str(step.get("name", f"step_{idx + 1}")),
                "power": float(step.get("power", step.get("tec_power_w", 0.0)) or 0.0),
                "duration_seconds": float(duration or 0.0),
                "set_voltage": _optional_float(step.get("set_voltage", step.get("tec_voltage_v"))),
                "set_current": _optional_float(step.get("set_current", step.get("tec_current_a"))),
                "enable_output": bool(step.get("enable_output", True)),
            }
        )
    return converted


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


@dataclass
class PowerScheduleStep:
    name: str
    power: float = 0.0
    duration_seconds: float = 0.0
    set_voltage: Optional[float] = None
    set_current: Optional[float] = None
    enable_output: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PowerScheduleStep":
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {key: value for key, value in data.items() if key in valid_keys}
        filtered.setdefault("name", "step")
        return cls(**filtered)


@dataclass
class LiveLoggerConfig:
    transport: str = "com"
    serial_port: Optional[str] = None
    serial_port_autodetect: bool = True
    serial_port_hint: Optional[str] = None
    address: int = 1
    channel: int = 1
    baudrate: int = 57600
    timeout: float = 1.0
    tcp_host: Optional[str] = None
    tcp_port: int = 50000
    output_directory: str = "live_logs"
    output_prefix: str = "power_live_log_com"
    run_name: Optional[str] = None
    write_metadata_sidecar: bool = True
    parameters: List[LiveParameterSpec] = field(default_factory=list)
    power_schedule: List[PowerScheduleStep] = field(default_factory=list)
    allow_named_voltage_current_fallback: bool = False
    duration_seconds: Optional[float] = None
    acquisition_hz: float = 10.0
    csv_flush_every_rows: int = 1
    channel_setup_parameters: List[LiveParameterSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiveLoggerConfig":
        payload = dict(data)
        if not payload.get("power_schedule"):
            converted_steps = legacy_tec_steps_to_power_schedule(payload)
            if converted_steps:
                payload["power_schedule"] = converted_steps
        payload["parameters"] = [LiveParameterSpec.from_dict(item) for item in payload.get("parameters", [])]
        payload["channel_setup_parameters"] = [LiveParameterSpec.from_dict(item) for item in payload.get("channel_setup_parameters", [])]
        payload["power_schedule"] = [PowerScheduleStep.from_dict(item) for item in payload.get("power_schedule", [])]
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered_payload = {key: value for key, value in payload.items() if key in valid_keys}
        return cls(**filtered_payload)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "LiveLoggerConfig":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls.from_dict(data)


class LiveLogger:
    def __init__(self, config: LiveLoggerConfig):
        self.config = config
        self._read_failure_keys: set[str] = set()

    def resolve_serial_port(self) -> str:
        if self.config.serial_port:
            return self.config.serial_port
        if self.config.serial_port_autodetect:
            port = autodetect_serial_port(self.config.serial_port_hint)
            if port:
                if self.config.serial_port_hint:
                    LOGGER.info("Auto-detected serial port using hint '%s': %s", self.config.serial_port_hint, port)
                else:
                    LOGGER.info("Auto-detected serial port: %s", port)
                return port
        raise ValueError("No serial_port configured and auto-detect did not find any connected controller")

    def _open_session(self):
        transport = self.config.transport.lower()
        if transport == "com":
            serial_port = self.resolve_serial_port()
            return (
                MeComSerial(serialport=serial_port, timeout=self.config.timeout, baudrate=self.config.baudrate, metype="TEC"),
                serial_port,
            )
        if transport == "tcp":
            if not self.config.tcp_host:
                raise ValueError("tcp_host is required when transport=tcp")
            return (
                MeComTcp(ipaddress=self.config.tcp_host, ipport=self.config.tcp_port, timeout=self.config.timeout, metype="TEC"),
                f"{self.config.tcp_host}:{self.config.tcp_port}",
            )
        raise ValueError("transport must be one of: com, tcp")

    def run(
        self,
        hz: float = 10.0,
        duration_seconds: Optional[float] = None,
        started_callback: Optional[Callable[[Path], None]] = None,
        row_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        stop_requested: Optional[Callable[[], bool]] = None,
    ) -> Path:
        interval = 1.0 / hz
        out_dir = Path(self.config.output_directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc)
        suffix = self.config.run_name or started_at.strftime('%Y%m%d_%H%M%S')
        stem = f"{self.config.output_prefix}_{suffix}"
        csv_path = out_dir / f"{stem}.csv"

        if started_callback is not None:
            started_callback(csv_path)

        fields = ["Time", "Milliseconds", "OLE Automation Date"] + [spec.label for spec in self.config.parameters]
        session_manager, endpoint = self._open_session()
        if self.config.write_metadata_sidecar:
            metadata_path = out_dir / f"{stem}.metadata.json"
            with open(metadata_path, "w", encoding="utf-8") as handle:
                json.dump({"started_at": started_at.isoformat(), "endpoint": endpoint, "config": asdict(self.config)}, handle, indent=2)
                handle.write("\n")

        with session_manager as session, open(
            csv_path, "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            flush_csv_row(handle)

            channel_config = type(
                "LiveChannelConfig",
                (),
                {
                    "address": self.config.address,
                    "channel": self.config.channel,
                    "enable_output_value": 1,
                    "disable_output_value": 0,
                    "output_setpoint_parameters": {},
                    "allow_named_voltage_current_fallback": self.config.allow_named_voltage_current_fallback,
                    "output_stage_input_selection": None,
                },
            )()
            controller = SafeChannelController(session, channel_config)
            self._apply_channel_setup_parameters(session)

            schedule = list(self.config.power_schedule)
            schedule_index = 0
            step_deadline: Optional[float] = None
            if schedule:
                first = schedule[0]
                controller.apply_step(
                    CalibrationStep(
                        name=first.name,
                        power=first.power,
                        dwell_seconds=max(1, int(first.duration_seconds)),
                        set_voltage=first.set_voltage,
                        set_current=first.set_current,
                        enable_output=first.enable_output,
                    )
                )
                step_deadline = time.monotonic() + max(0.0, first.duration_seconds)

            deadline = time.monotonic() + duration_seconds if duration_seconds is not None else None
            while True:
                tick = time.monotonic()
                now = datetime.now(timezone.utc)
                row = build_time_columns(now)
                for spec in self.config.parameters:
                    row[spec.label] = self._read_parameter(session, spec)
                writer.writerow(row)
                flush_csv_row(handle)
                if row_callback is not None:
                    row_callback(row)

                if schedule and step_deadline is not None:
                    now_mono = time.monotonic()
                    while schedule and step_deadline is not None and now_mono >= step_deadline:
                        schedule_index += 1
                        if schedule_index < len(schedule):
                            step = schedule[schedule_index]
                            controller.apply_step(
                                CalibrationStep(
                                    name=step.name,
                                    power=step.power,
                                    dwell_seconds=max(1, int(step.duration_seconds)),
                                    set_voltage=step.set_voltage,
                                    set_current=step.set_current,
                                    enable_output=step.enable_output,
                                )
                            )
                            step_deadline += max(0.0, step.duration_seconds)
                        else:
                            schedule = []

                if stop_requested is not None and stop_requested():
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                sleep_for = interval - (time.monotonic() - tick)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        return csv_path

    def _apply_channel_setup_parameters(self, session: MeComSerial) -> None:
        for spec in self.config.channel_setup_parameters:
            if spec.parameter_id is None or spec.parameter_format is None:
                LOGGER.warning(
                    "Skipping channel setup parameter '%s' because parameter_id or parameter_format is missing.",
                    spec.key,
                )
                continue
            session.set_parameter_raw(
                value=spec.value,
                parameter_id=spec.parameter_id,
                parameter_format=spec.parameter_format,
                address=self.config.address,
                parameter_instance=spec.instance,
            )

    def _read_parameter(self, session: MeComSerial, spec: LiveParameterSpec) -> Any:
        try:
            if spec.parameter_name:
                return session.get_parameter(parameter_name=spec.parameter_name, address=self.config.address, parameter_instance=spec.instance)
            return session.get_parameter_raw(
                parameter_id=spec.parameter_id,
                parameter_format=spec.parameter_format,
                address=self.config.address,
                parameter_instance=spec.instance,
            )
        except Exception as exc:
            if spec.key not in self._read_failure_keys:
                LOGGER.warning(
                    "Read failed for %s (%s). Value will be logged as NaN. Error: %r",
                    spec.key,
                    spec.label,
                    exc,
                )
                self._read_failure_keys.add(spec.key)
            return math.nan


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
