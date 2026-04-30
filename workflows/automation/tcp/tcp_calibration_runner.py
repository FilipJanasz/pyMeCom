#!/usr/bin/env python3
"""TCP calibration wrapper for TEC1161 using MeComTcp transport.

This keeps the existing serial runner (`mecom.calibration`) untouched while
providing an equivalent stepped loop over TCP.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from mecom.calibration import (
    CalibrationConfig,
    CalibrationDataLogger,
    MeasurementReader,
    ParameterSpec,
    SafeChannelController,
    configure_logging,
)
from mecom.mecom import MeComTcp

LOGGER = logging.getLogger(__name__)


class TcpSafeChannelController(SafeChannelController):
    """Safe-state helper variant for TCP sessions."""

    def _session_is_open(self) -> bool:
        tcp_handle = getattr(self.session, "tcp", None)
        if tcp_handle is None:
            return False
        try:
            return tcp_handle.fileno() >= 0
        except Exception:
            return False


class TcpCalibrationRunner:
    """Runs stepped calibration using MeComTcp."""

    def __init__(self, config: CalibrationConfig, host: str, port: int):
        self.config = config
        self.host = host
        self.port = port
        if not config.steps:
            raise ValueError("Calibration config must define at least one step")

        self.run_started_at = datetime.now(timezone.utc)
        run_name = config.run_name or self.run_started_at.strftime("%Y%m%dT%H%M%SZ")
        run_stem = f"{config.device_label.lower()}_ch{config.channel}_{run_name}"
        self.logger = CalibrationDataLogger(Path(config.output_directory), run_stem)
        self.safe_controller: Optional[TcpSafeChannelController] = None

    def run(self) -> int:
        metadata = self._build_metadata()
        if self.config.write_header_metadata:
            self.logger.write_metadata(metadata)

        LOGGER.info("Starting TCP calibration run for %s channel %s at %s:%s", self.config.device_label, self.config.channel, self.host, self.port)
        try:
            with MeComTcp(ipaddress=self.host, ipport=self.port, timeout=self.config.timeout) as session:
                self.safe_controller = TcpSafeChannelController(session, self.config)
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
                    self.logger.append_record(
                        {
                            "timestamp": measured_at.isoformat(),
                            "step_started_at": step_started_at.isoformat(),
                            "requested_dwell_seconds": step.dwell_seconds,
                            "actual_dwell_seconds": (measured_at - step_started_at).total_seconds(),
                            "run_started_at": self.run_started_at.isoformat(),
                            "transport": "tcp",
                            "tcp_host": self.host,
                            "tcp_port": self.port,
                            "device_label": self.config.device_label,
                            "address": self.config.address,
                            "channel": self.config.channel,
                            "step_index": index,
                            "step_name": step.name,
                            "step_metadata": step.metadata,
                            "target": {
                                "power": step.power,
                                "set_voltage": step.set_voltage,
                                "set_current": step.set_current,
                                "output_enabled": step.enable_output,
                            },
                            "measurements": self._read_measurements(reader),
                        }
                    )

                LOGGER.info("Calibration steps complete, driving output to zero")
                self.safe_controller.apply_zero_output(disable_output=True)
                return 0
        except Exception:
            LOGGER.exception("TCP calibration run failed")
            if self.safe_controller is not None:
                self.safe_controller.force_safe_state()
            return 1
        finally:
            if self.safe_controller is not None:
                self.safe_controller.force_safe_state()
                self.safe_controller.disarm()

    def _read_measurements(self, reader: MeasurementReader) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for key, pname in (
            ("actual_output_voltage", "Actual Output Voltage"),
            ("actual_output_current", "Actual Output Current"),
            ("actual_output_power", "Actual Output Power"),
            ("device_status", "Device Status"),
            ("error_number", "Error Number"),
        ):
            try:
                payload[key] = reader.read(ParameterSpec(key=key, parameter_name=pname))
            except Exception as exc:
                payload[f"{key}_error"] = str(exc)
        return payload

    def _build_metadata(self) -> Dict[str, Any]:
        return {
            "created_at": self.run_started_at.isoformat(),
            "transport": "tcp",
            "tcp_host": self.host,
            "tcp_port": self.port,
            "device_label": self.config.device_label,
            "address": self.config.address,
            "channel": self.config.channel,
            "timeout": self.config.timeout,
            "settle_seconds": self.config.settle_seconds,
            "steps": [asdict(step) for step in self.config.normalized_steps()],
        }


def _load_tcp_config(path: str | Path) -> tuple[CalibrationConfig, str, int]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    host = data.pop("host")
    port = int(data.pop("port", 50000))
    data.pop("transport", None)

    # CalibrationConfig requires serial_port. Keep a virtual descriptor so shared
    # logging/metadata structures remain compatible with existing tooling.
    data.setdefault("serial_port", f"tcp://{host}:{port}")
    return CalibrationConfig.from_dict(data), host, port


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run stepped TEC1161 calibration over TCP")
    parser.add_argument("--config", required=True, help="Path to TCP JSON configuration file")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    configure_logging(verbose=args.verbose)
    config, host, port = _load_tcp_config(args.config)
    runner = TcpCalibrationRunner(config, host=host, port=port)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
