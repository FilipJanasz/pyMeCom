from __future__ import annotations

import csv
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from mecom.calibration import CalibrationStep, SafeChannelController
from mecom.mecom import MeComSerial, MeComTcp

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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiveParameterSpec":
        return cls(**data)


def default_live_parameters(channel: int = 1) -> List[LiveParameterSpec]:
    return [
        LiveParameterSpec("error_number", f"105.1: Error Number", parameter_name="Error Number", instance=1),
        LiveParameterSpec(f"ch{channel}_nom_i", f"1012.{channel}: CH{channel} Nom I", parameter_id=1012, parameter_format="FLOAT32", instance=channel),
        LiveParameterSpec(f"ch{channel}_nom_u", f"1013.{channel}: CH{channel} Nom U", parameter_id=1013, parameter_format="FLOAT32", instance=channel),
        LiveParameterSpec(f"ch{channel}_act_i", f"1020.{channel}: CH{channel} Act I", parameter_name="Actual Output Current", instance=channel),
        LiveParameterSpec(f"ch{channel}_act_u", f"1021.{channel}: CH{channel} Act U", parameter_name="Actual Output Voltage", instance=channel),
        LiveParameterSpec(f"ch{channel}_act_p", f"1022.{channel}: CH{channel} Act P", parameter_name="Actual Output Power", instance=channel),
        LiveParameterSpec("lr1_temp", "1044.1: LR1 Temp", parameter_id=1044, parameter_format="FLOAT32", instance=1),
        LiveParameterSpec("lr2_temp", "1044.2: LR2 Temp", parameter_id=1044, parameter_format="FLOAT32", instance=2),
        LiveParameterSpec("hr1_temp", "1045.1: HR1 Temp", parameter_id=1045, parameter_format="FLOAT32", instance=1),
        LiveParameterSpec("hr2_temp", "1045.2: HR2 Temp", parameter_id=1045, parameter_format="FLOAT32", instance=2),
        LiveParameterSpec("diff_voltage_1", "1046.1: Differential Voltage", parameter_id=1046, parameter_format="FLOAT32", instance=1),
        LiveParameterSpec("diff_voltage_2", "1046.2: Differential Voltage", parameter_id=1046, parameter_format="FLOAT32", instance=2),
    ]


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
        return cls(**data)


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
    write_metadata_sidecar: bool = True
    parameters: List[LiveParameterSpec] = field(default_factory=list)
    power_schedule: List[PowerScheduleStep] = field(default_factory=list)
    allow_named_voltage_current_fallback: bool = False
    duration_seconds: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiveLoggerConfig":
        payload = dict(data)
        payload["parameters"] = [LiveParameterSpec.from_dict(item) for item in payload.get("parameters", [])]
        payload["power_schedule"] = [PowerScheduleStep.from_dict(item) for item in payload.get("power_schedule", [])]
        return cls(**payload)

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

    def run(self, hz: float = 1.0, duration_seconds: Optional[float] = None) -> Path:
        interval = 1.0 / hz
        out_dir = Path(self.config.output_directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc)
        stem = f"{self.config.output_prefix}_{started_at.strftime('%Y%m%d_%H%M%S')}"
        csv_path = out_dir / f"{stem}.csv"

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
            handle.flush()

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
                handle.flush()

                if schedule and step_deadline is not None and time.monotonic() >= step_deadline:
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
                        step_deadline = time.monotonic() + max(0.0, step.duration_seconds)
                    else:
                        schedule = []

                if deadline is not None and time.monotonic() >= deadline:
                    break
                sleep_for = interval - (time.monotonic() - tick)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        return csv_path

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
