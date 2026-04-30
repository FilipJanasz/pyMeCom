"""Calibration workflow helpers for Meerstetter TEC controllers.

This module implements a long-running stepped calibration workflow for TEC1161
controllers on top of the existing :class:`mecom.mecom.MeComSerial` API.

The workflow is intentionally conservative:
- it forces the selected channel output to zero before the first dwell,
- records one structured measurement after each dwell step,
- writes data incrementally to JSONL and CSV files,
- attempts to force the output back to zero on normal exit, signals, and
  unhandled failures.

Several measurement channels required for TEC1161 calibration are device-
 and firmware-specific. Where the repository already exposes stable named
parameters, those are used directly. For signals that may require raw MeCom
parameter access (for example high-resolution ADC / differential-voltage inputs
or model-specific low-resolution temperatures), the configuration can declare
parameter IDs and formats explicitly.
"""

from __future__ import annotations

import atexit
import csv
import json
import logging
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .exceptions import ResponseTimeout
from .mecom import MeComSerial

LOGGER = logging.getLogger(__name__)

DEFAULT_STEP_DWELL_SECONDS = 30 * 60
DEFAULT_SETTLE_SECONDS = 1.0
DEFAULT_OUTPUT_ENABLE = 1
DEFAULT_OUTPUT_DISABLE = 0

# Named parameters that are already represented in mecom/commands.py.
DEFAULT_NAMED_MEASUREMENTS: Tuple[Tuple[str, str], ...] = (
    ("actual_output_voltage", "Actual Output Voltage"),
    ("actual_output_current", "Actual Output Current"),
    ("actual_output_power", "Actual Output Power"),
    ("device_status", "Device Status"),
    ("error_number", "Error Number"),
)


@dataclass
class ParameterSpec:
    """Description of one MeCom parameter to read or write."""

    key: str
    parameter_name: Optional[str] = None
    parameter_id: Optional[int] = None
    parameter_format: Optional[str] = None
    instance: Optional[int] = None
    description: Optional[str] = None
    required: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParameterSpec":
        return cls(**data)

    def target_instance(self, channel: int) -> int:
        return self.instance if self.instance is not None else channel

    def is_configured(self) -> bool:
        return bool(self.parameter_name) or (self.parameter_id is not None and self.parameter_format is not None)


@dataclass
class CalibrationStep:
    """One configured calibration step."""

    name: str
    power: float = 0.0
    dwell_seconds: int = DEFAULT_STEP_DWELL_SECONDS
    set_voltage: Optional[float] = None
    set_current: Optional[float] = None
    enable_output: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationStep":
        payload = dict(data)
        payload.setdefault("power", 0.0)
        return cls(**payload)


@dataclass
class CalibrationConfig:
    """Top-level calibration configuration."""

    serial_port: str
    address: int = 1
    channel: int = 1
    baudrate: int = 57600
    timeout: float = 1.0
    output_directory: str = "calibration_logs"
    run_name: Optional[str] = None
    device_label: str = "TEC1161"
    dwell_seconds_default: int = DEFAULT_STEP_DWELL_SECONDS
    settle_seconds: float = DEFAULT_SETTLE_SECONDS
    enable_output_value: int = DEFAULT_OUTPUT_ENABLE
    disable_output_value: int = DEFAULT_OUTPUT_DISABLE
    output_stage_input_selection: Optional[int] = None
    allow_named_voltage_current_fallback: bool = False
    write_header_metadata: bool = True
    notes: Optional[str] = None
    steps: List[CalibrationStep] = field(default_factory=list)
    measurement_parameters: List[ParameterSpec] = field(default_factory=list)
    output_setpoint_parameters: Dict[str, ParameterSpec] = field(default_factory=dict)
    low_resolution_temperature_parameters: List[ParameterSpec] = field(default_factory=list)
    raw_parameter_placeholders: List[ParameterSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationConfig":
        payload = dict(data)
        payload["steps"] = [CalibrationStep.from_dict(item) for item in payload.get("steps", [])]
        payload["measurement_parameters"] = [ParameterSpec.from_dict(item) for item in payload.get("measurement_parameters", [])]
        payload["low_resolution_temperature_parameters"] = [ParameterSpec.from_dict(item) for item in payload.get("low_resolution_temperature_parameters", [])]
        payload["raw_parameter_placeholders"] = [ParameterSpec.from_dict(item) for item in payload.get("raw_parameter_placeholders", [])]
        payload["output_setpoint_parameters"] = {
            key: ParameterSpec.from_dict(value) for key, value in payload.get("output_setpoint_parameters", {}).items()
        }
        return cls(**payload)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CalibrationConfig":
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return cls.from_dict(data)

    def normalized_steps(self) -> List[CalibrationStep]:
        normalized = []
        for index, step in enumerate(self.steps):
            normalized.append(
                CalibrationStep(
                    name=step.name or f"step_{index:02d}",
                    power=step.power,
                    dwell_seconds=step.dwell_seconds or self.dwell_seconds_default,
                    set_voltage=step.set_voltage,
                    set_current=step.set_current,
                    enable_output=step.enable_output,
                    metadata=dict(step.metadata),
                )
            )
        return normalized


class MeasurementReader:
    """Reads named or raw parameters from a controller session."""

    def __init__(self, session: MeComSerial, address: int, channel: int):
        self.session = session
        self.address = address
        self.channel = channel

    def read(self, spec: ParameterSpec) -> Any:
        kwargs = {
            "address": self.address,
            "parameter_instance": spec.target_instance(self.channel),
        }
        if spec.parameter_name:
            return self.session.get_parameter(parameter_name=spec.parameter_name, **kwargs)
        if spec.parameter_id is None or spec.parameter_format is None:
            raise ValueError(f"Parameter spec '{spec.key}' requires either parameter_name or parameter_id + parameter_format")
        return self.session.get_parameter_raw(parameter_id=spec.parameter_id, parameter_format=spec.parameter_format, **kwargs)


class CalibrationDataLogger:
    """Writes metadata and records durably to disk."""

    def __init__(self, base_dir: Path, run_stem: str):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.base_dir / f"{run_stem}_metadata.json"
        self.jsonl_path = self.base_dir / f"{run_stem}_measurements.jsonl"
        self.csv_path = self.base_dir / f"{run_stem}_measurements.csv"
        self._csv_fieldnames: Optional[List[str]] = None

    def write_metadata(self, metadata: Dict[str, Any]) -> None:
        with open(self.metadata_path, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def append_record(self, record: Dict[str, Any]) -> None:
        with open(self.jsonl_path, "a", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()

        flattened = self._flatten_record(record)
        if self._csv_fieldnames is None:
            self._csv_fieldnames = list(flattened.keys())
            with open(self.csv_path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=self._csv_fieldnames)
                writer.writeheader()
                writer.writerow(flattened)
                handle.flush()
            return

        extra_fields = [field for field in flattened.keys() if field not in self._csv_fieldnames]
        if extra_fields:
            self._rewrite_csv_with_new_fields(extra_fields, flattened)
            return

        with open(self.csv_path, "a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._csv_fieldnames)
            writer.writerow(flattened)
            handle.flush()

    def _rewrite_csv_with_new_fields(self, extra_fields: Sequence[str], newest_row: Dict[str, Any]) -> None:
        assert self._csv_fieldnames is not None
        all_rows: List[Dict[str, Any]] = []
        if self.csv_path.exists():
            with open(self.csv_path, "r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                all_rows.extend(reader)
        self._csv_fieldnames.extend(extra_fields)
        all_rows.append(newest_row)
        with open(self.csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self._csv_fieldnames)
            writer.writeheader()
            for row in all_rows:
                writer.writerow(row)
            handle.flush()

    @staticmethod
    def _flatten_record(record: Dict[str, Any]) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        stack: List[Tuple[str, Any]] = list(record.items())
        while stack:
            key, value = stack.pop(0)
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    stack.append((f"{key}.{child_key}", child_value))
            else:
                flat[key] = value
        return flat


class SafeChannelController:
    """Best-effort safe shutdown helper for one channel."""

    def __init__(self, session: MeComSerial, config: CalibrationConfig):
        self.session = session
        self.config = config
        self._reader = MeasurementReader(session, config.address, config.channel)
        self._armed = False
        self._signal_handlers: Dict[int, Any] = {}
        self._missing_output_setpoint_warning_emitted = False
        self._output_stage_input_selection_timeout_emitted = False

    def arm(self) -> None:
        if self._armed:
            return
        atexit.register(self.force_safe_state)
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            self._signal_handlers[sig] = previous
            signal.signal(sig, self._signal_handler)
        self._armed = True

    def disarm(self) -> None:
        if not self._armed:
            return
        atexit.unregister(self.force_safe_state)
        for sig, previous in self._signal_handlers.items():
            signal.signal(sig, previous)
        self._signal_handlers.clear()
        self._armed = False

    def _signal_handler(self, signum: int, frame: Any) -> None:
        LOGGER.error("Received signal %s, forcing channel %s to a safe state", signum, self.config.channel)
        self.force_safe_state()
        previous = self._signal_handlers.get(signum)
        if callable(previous):
            previous(signum, frame)
        raise SystemExit(128 + signum)

    def force_safe_state(self) -> None:
        if not self._session_is_open():
            LOGGER.debug("Skipping safe-state write for channel %s because the serial port is already closed", self.config.channel)
            return
        try:
            self.apply_zero_output(disable_output=True)
        except Exception:  # pragma: no cover - best effort shutdown path
            LOGGER.exception("Failed to force safe zero-output state for channel %s", self.config.channel)

    def apply_zero_output(self, disable_output: bool = False) -> None:
        self._set_output_setpoints(power=0.0, set_voltage=0.0, set_current=0.0, force_zero=True)
        if disable_output:
            self._set_output_enabled(False)

    def apply_step(self, step: CalibrationStep) -> None:
        if self.config.output_stage_input_selection is not None:
            try:
                self.session.set_parameter(
                    value=self.config.output_stage_input_selection,
                    parameter_name="Output Stage Input Selection",
                    address=self.config.address,
                    parameter_instance=self.config.channel,
                )
            except ResponseTimeout:
                if self._output_stage_input_selection_timeout_emitted:
                    raise
                LOGGER.warning(
                    "Timed out while writing 'Output Stage Input Selection' on channel %s; "
                    "disabling that optional write for the rest of the run. Set "
                    "output_stage_input_selection to null/omit it if your device does not support "
                    "the generic command.",
                    self.config.channel,
                )
                self._output_stage_input_selection_timeout_emitted = True
                self.config.output_stage_input_selection = None
        setpoints_applied = self._set_output_setpoints(
            power=step.power,
            set_voltage=step.set_voltage,
            set_current=step.set_current,
            force_zero=False,
        )
        should_enable_output = step.enable_output and setpoints_applied
        if step.enable_output and not should_enable_output:
            LOGGER.warning(
                "Step '%s' requested output enable on channel %s, but no writable output setpoint path is configured; keeping output disabled for safety.",
                step.name,
                self.config.channel,
            )
        self._set_output_enabled(should_enable_output)

    def _set_output_enabled(self, enabled: bool) -> None:
        value = self.config.enable_output_value if enabled else self.config.disable_output_value
        try:
            self.session.set_parameter(
                value=value,
                parameter_name="Output Enable Status",
                address=self.config.address,
                parameter_instance=self.config.channel,
            )
        except ResponseTimeout:
            if enabled:
                raise
            LOGGER.warning(
                "Timed out while disabling output on channel %s; continuing because safe-state shutdown is best-effort.",
                self.config.channel,
            )

    def _set_output_setpoints(self, power: float, set_voltage: Optional[float], set_current: Optional[float], force_zero: bool = False) -> bool:
        specs = self.config.output_setpoint_parameters
        if "power" in specs:
            self._write_parameter(specs["power"], power)
            return True

        voltage_spec = specs.get("voltage")
        current_spec = specs.get("current")
        if voltage_spec is not None or current_spec is not None:
            voltage = 0.0 if force_zero else set_voltage
            current = 0.0 if force_zero else set_current
            if voltage_spec is not None and voltage is not None:
                self._write_parameter(voltage_spec, voltage)
            if current_spec is not None and current is not None:
                self._write_parameter(current_spec, current)
            return True

        if self.config.allow_named_voltage_current_fallback:
            # Legacy compatibility path for devices that do accept the generic named
            # voltage/current commands. Keep this opt-in because some TEC1161 setups
            # simply do not answer those commands, which can otherwise trigger a serial
            # timeout before the run even starts.
            self._maybe_write_voltage_current(set_voltage=set_voltage, set_current=set_current, force_zero=force_zero)
            return True

        if not self._missing_output_setpoint_warning_emitted:
            LOGGER.warning(
                "No writable output setpoint parameter is configured for channel %s; "
                "skipping power/voltage/current writes. Configure output_setpoint_parameters "
                "or set allow_named_voltage_current_fallback=true if your device supports the generic commands.",
                self.config.channel,
            )
            self._missing_output_setpoint_warning_emitted = True
        return False

    def _maybe_write_voltage_current(self, set_voltage: Optional[float], set_current: Optional[float], force_zero: bool) -> None:
        voltage = 0.0 if force_zero else set_voltage
        current = 0.0 if force_zero else set_current
        if voltage is not None:
            self.session.set_parameter(
                value=voltage,
                parameter_name="Set Voltage",
                address=self.config.address,
                parameter_instance=self.config.channel,
            )
        if current is not None:
            self.session.set_parameter(
                value=current,
                parameter_name="Set Current",
                address=self.config.address,
                parameter_instance=self.config.channel,
            )

    def _session_is_open(self) -> bool:
        serial_handle = getattr(self.session, "ser", None)
        return bool(serial_handle is not None and getattr(serial_handle, "is_open", False))

    def _write_parameter(self, spec: ParameterSpec, value: Any) -> None:
        kwargs = {
            "address": self.config.address,
            "parameter_instance": spec.target_instance(self.config.channel),
        }
        if spec.parameter_name:
            self.session.set_parameter(value=value, parameter_name=spec.parameter_name, **kwargs)
            return
        if spec.parameter_id is None or spec.parameter_format is None:
            raise ValueError(f"Output setpoint parameter '{spec.key}' is missing parameter metadata")
        self.session.set_parameter_raw(value=value, parameter_id=spec.parameter_id, parameter_format=spec.parameter_format, **kwargs)


class TecCalibrationRunner:
    """Runs a stepped calibration sequence and logs structured measurements."""

    def __init__(self, config: CalibrationConfig):
        self.config = config
        if not config.steps:
            raise ValueError("Calibration config must define at least one step")
        self.run_started_at = datetime.now(timezone.utc)
        run_name = config.run_name or self.run_started_at.strftime("%Y%m%dT%H%M%SZ")
        run_stem = f"{config.device_label.lower()}_ch{config.channel}_{run_name}"
        self.logger = CalibrationDataLogger(Path(config.output_directory), run_stem)
        self.session: Optional[MeComSerial] = None
        self.safe_controller: Optional[SafeChannelController] = None

    def run(self) -> int:
        metadata = self._build_metadata()
        if self.config.write_header_metadata:
            self.logger.write_metadata(metadata)
        LOGGER.info("Starting calibration run for %s channel %s", self.config.device_label, self.config.channel)
        try:
            with MeComSerial(serialport=self.config.serial_port, timeout=self.config.timeout, baudrate=self.config.baudrate) as session:
                self.session = session
                self.safe_controller = SafeChannelController(session, self.config)
                self.safe_controller.arm()
                reader = MeasurementReader(session, self.config.address, self.config.channel)

                self.safe_controller.apply_zero_output(disable_output=True)
                time.sleep(self.config.settle_seconds)

                for index, step in enumerate(self.config.normalized_steps()):
                    LOGGER.info("Applying calibration step %s (%s)", index, step.name)
                    step_started_at = datetime.now(timezone.utc)
                    self.safe_controller.apply_step(step)
                    LOGGER.info("Dwelling for %s seconds", step.dwell_seconds)
                    time.sleep(step.dwell_seconds)
                    measured_at = datetime.now(timezone.utc)
                    record = self._collect_record(
                        reader,
                        index,
                        step,
                        step_started_at=step_started_at,
                        measured_at=measured_at,
                    )
                    self.logger.append_record(record)

                LOGGER.info("Calibration steps complete, driving output to zero")
                self.safe_controller.apply_zero_output(disable_output=True)
                return 0
        except Exception:
            LOGGER.exception("Calibration run failed")
            if self.safe_controller is not None:
                self.safe_controller.force_safe_state()
            return 1
        finally:
            if self.safe_controller is not None:
                self.safe_controller.force_safe_state()
                self.safe_controller.disarm()

    def _collect_record(
        self,
        reader: MeasurementReader,
        step_index: int,
        step: CalibrationStep,
        *,
        step_started_at: datetime,
        measured_at: datetime,
    ) -> Dict[str, Any]:
        measurements: Dict[str, Any] = {}
        measurement_errors: Dict[str, str] = {}

        for key, parameter_name in DEFAULT_NAMED_MEASUREMENTS:
            try:
                measurements[key] = reader.read(ParameterSpec(key=key, parameter_name=parameter_name))
            except Exception as exc:
                measurement_errors[key] = str(exc)

        for spec in self.config.measurement_parameters:
            if not spec.is_configured():
                measurements[spec.key] = None
                measurement_errors[spec.key] = 'unconfigured parameter placeholder'
                if spec.required:
                    raise ValueError(f"Required measurement parameter '{spec.key}' is not configured")
                continue
            try:
                measurements[spec.key] = reader.read(spec)
            except Exception as exc:
                measurement_errors[spec.key] = str(exc)
                if spec.required:
                    raise

        low_res_temps: Dict[str, Any] = {}
        for spec in self.config.low_resolution_temperature_parameters:
            if not spec.is_configured():
                low_res_temps[spec.key] = None
                measurement_errors[spec.key] = 'unconfigured parameter placeholder'
                if spec.required:
                    raise ValueError(f"Required low-resolution temperature parameter '{spec.key}' is not configured")
                continue
            try:
                low_res_temps[spec.key] = reader.read(spec)
            except Exception as exc:
                low_res_temps[spec.key] = None
                measurement_errors[spec.key] = str(exc)
                if spec.required:
                    raise

        output_targets = {
            "power": step.power,
            "set_voltage": step.set_voltage,
            "set_current": step.set_current,
            "output_enabled": step.enable_output,
        }
        status = self._read_status_summary(reader)

        actual_dwell_seconds = (measured_at - step_started_at).total_seconds()

        return {
            "timestamp": measured_at.isoformat(),
            "step_started_at": step_started_at.isoformat(),
            "requested_dwell_seconds": step.dwell_seconds,
            "actual_dwell_seconds": actual_dwell_seconds,
            "run_started_at": self.run_started_at.isoformat(),
            "device_label": self.config.device_label,
            "serial_port": self.config.serial_port,
            "address": self.config.address,
            "channel": self.config.channel,
            "step_index": step_index,
            "step_name": step.name,
            "step_metadata": step.metadata,
            "target": output_targets,
            "measurements": measurements,
            "low_resolution_temperatures": low_res_temps,
            "status": status,
            "measurement_errors": measurement_errors,
        }

    def _read_status_summary(self, reader: MeasurementReader) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        for key, parameter_name in (
            ("device_status", "Device Status"),
            ("error_number", "Error Number"),
        ):
            try:
                summary[key] = reader.read(ParameterSpec(key=key, parameter_name=parameter_name))
            except Exception as exc:
                summary[f"{key}_error"] = str(exc)
        return summary

    def _build_metadata(self) -> Dict[str, Any]:
        return {
            "created_at": self.run_started_at.isoformat(),
            "device_label": self.config.device_label,
            "serial_port": self.config.serial_port,
            "address": self.config.address,
            "channel": self.config.channel,
            "baudrate": self.config.baudrate,
            "timeout": self.config.timeout,
            "dwell_seconds_default": self.config.dwell_seconds_default,
            "settle_seconds": self.config.settle_seconds,
            "enable_output_value": self.config.enable_output_value,
            "disable_output_value": self.config.disable_output_value,
            "output_stage_input_selection": self.config.output_stage_input_selection,
            "steps": [asdict(step) for step in self.config.normalized_steps()],
            "measurement_parameters": [asdict(spec) for spec in self.config.measurement_parameters],
            "low_resolution_temperature_parameters": [asdict(spec) for spec in self.config.low_resolution_temperature_parameters],
            "output_setpoint_parameters": {key: asdict(spec) for key, spec in self.config.output_setpoint_parameters.items()},
            "raw_parameter_placeholders": [asdict(spec) for spec in self.config.raw_parameter_placeholders],
            "notes": [
                "Named MeCom parameters are used where already available in mecom/commands.py.",
                "TEC1161-specific high-resolution ADC and low-resolution temperature channels can be configured via raw parameter IDs and formats.",
                "The repository PDFs mention ADC configuration/calibration details, but the exact TEC1161 HR/low-resolution parameter IDs should be confirmed on the target hardware or protocol table before unattended production use.",
            ],
        }


def default_tec1161_calibration_config(serial_port: str, output_directory: str = "calibration_logs") -> CalibrationConfig:
    """Return a conservative starter configuration for TEC1161 CH1 calibration.

    The default step table intentionally starts with a 0-output dwell and includes
    placeholder measurement definitions for the required high-resolution inputs.
    Fill in the raw parameter IDs/formats once they are confirmed from the TEC1161
    protocol table or from live device interrogation.
    """

    return CalibrationConfig(
        serial_port=serial_port,
        output_directory=output_directory,
        channel=1,
        steps=[
            CalibrationStep(name="zero_baseline", power=0.0, dwell_seconds=DEFAULT_STEP_DWELL_SECONDS, set_voltage=0.0, set_current=0.0),
            CalibrationStep(name="step_01", power=0.25, dwell_seconds=DEFAULT_STEP_DWELL_SECONDS),
            CalibrationStep(name="step_02", power=0.50, dwell_seconds=DEFAULT_STEP_DWELL_SECONDS),
            CalibrationStep(name="step_03", power=0.75, dwell_seconds=DEFAULT_STEP_DWELL_SECONDS),
            CalibrationStep(name="step_04", power=1.00, dwell_seconds=DEFAULT_STEP_DWELL_SECONDS),
        ],
        measurement_parameters=[
            ParameterSpec(
                key="hr_input_1_adc_differential_voltage",
                parameter_id=None,
                parameter_format=None,
                description="Placeholder for TEC1161 HR Input 1 / ADC / Differential Voltage raw parameter",
                required=False,
            ),
            ParameterSpec(
                key="hr_input_2_adc_differential_voltage",
                parameter_id=None,
                parameter_format=None,
                description="Placeholder for TEC1161 HR Input 2 / ADC / Differential Voltage raw parameter",
                required=False,
            ),
        ],
        low_resolution_temperature_parameters=[
            ParameterSpec(key="object_temperature", parameter_name="Object Temperature", description="Low-resolution object temperature"),
            ParameterSpec(key="sink_temperature", parameter_name="Sink Temperature", description="Low-resolution sink temperature"),
        ],
        raw_parameter_placeholders=[
            ParameterSpec(
                key="confirm_tec1161_hr_input_ids",
                description="Review TEC Controller Communication Protocol 5136AT.pdf and target hardware for HR input parameter IDs and formats",
            ),
        ],
    )


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run a stepped TEC1161 calibration workflow")
    parser.add_argument("--config", required=True, help="Path to JSON configuration file")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    configure_logging(verbose=args.verbose)
    config = CalibrationConfig.from_json_file(args.config)
    runner = TecCalibrationRunner(config)
    return runner.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
