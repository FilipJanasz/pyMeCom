from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from enum import Enum
from typing import Final, Optional, Sequence

import serial
import serial.tools.list_ports


HUBER_DEFAULT_BAUDRATE: Final[int] = 9600
HUBER_DEFAULT_TIMEOUT: Final[float] = 1.0
HUBER_RESPONSE_SIZE: Final[int] = 14
HUBER_COMMAND_TERMINATOR: Final[bytes] = b"\r\n"
HUBER_PING_COMMAND: Final[bytes] = b"TI?\r\n"
HUBER_AVAILABLE: Final[bool] = True
HUBER_CLIENT_SOURCE: Final[str] = __name__

logger = logging.getLogger("huber.legacy_pp")


class TemperatureVar(Enum):
    BATH = "TI"
    PROCESS = "TE"


class TLogger:
    def __init__(self, debug: bool = False):
        self.debug = debug

    def log(self, message: str, level: str = "INFO") -> None:
        if self.debug:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] [{level}] {message}", file=sys.stderr)

    def info(self, message: str) -> None:
        self.log(message, "INFO")

    def debug_msg(self, message: str) -> None:
        self.log(message, "DEBUG")

    def warning(self, message: str) -> None:
        self.log(message, "WARNING")

    def error(self, message: str) -> None:
        self.log(message, "ERROR")


class HuberThermostatI:
    """Standalone legacy Huber PP/text protocol client used by older Huber chillers.

    This intentionally preserves the working old-device command set:
    - TI? / TE? for bath/process temperature
    - SP? / SP@ for current and temporary setpoint
    - CA@+00001 / CA@+00000 for thermoregulation on/off
    """

    def __init__(self, interface_serial: serial.Serial, debug: bool = False):
        self._serial = interface_serial
        self._logger = TLogger(debug)
        self._logger.info("HuberThermostatI initialized")

    def _query(self, command: str) -> str:
        self._logger.debug_msg(f"Sending command: {command}")
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()
        cmd_bytes = (command + "\r\n").encode("ascii")
        self._serial.write(cmd_bytes)
        self._serial.flush()
        response = self._serial.read(HUBER_RESPONSE_SIZE)
        decoded = response.decode("ascii", errors="ignore").strip()
        self._logger.debug_msg(f"Received response: {decoded} (raw: {response})")
        return decoded

    def ping(self, command: bytes = HUBER_PING_COMMAND) -> bool:
        try:
            self._logger.debug_msg(f"Pinging device with command: {command}")
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self._serial.write(command)
            self._serial.flush()
            response = self._serial.read(HUBER_RESPONSE_SIZE).decode("ascii", errors="ignore")
            success = response.startswith("TI")
            self._logger.info(f"Ping {'successful' if success else 'failed'}: {response}")
            return success
        except (OSError, serial.SerialException) as exc:
            self._logger.error(f"Ping failed with exception: {exc}")
            return False

    def read_temperature(self, var: TemperatureVar) -> Optional[float]:
        try:
            self._logger.debug_msg(f"Reading temperature for variable: {var.value}")
            raw = self._query(f"{var.value}?")
            val_str = raw[len(var.value):].strip()
            temp = int(val_str) / 100.0
            self._logger.info(f"Temperature {var.value}: {temp:.2f} °C")
            return temp
        except (ValueError, serial.SerialException) as exc:
            self._logger.error(f"Failed to read temperature {var.value}: {exc}")
            return None

    def read_bath_temperature(self) -> Optional[float]:
        return self.read_temperature(TemperatureVar.BATH)

    def read_process_temperature(self) -> Optional[float]:
        return self.read_temperature(TemperatureVar.PROCESS)

    def set_setpoint(self, value_celsius: float, permanent: bool = False) -> bool:
        val_str = f"{value_celsius:+07.2f}".replace(".", "")
        cmd = f"SP{'&' if permanent else '@'}{val_str}"
        self._logger.info(
            f"Setting setpoint to {value_celsius:.2f} °C ({'permanent' if permanent else 'temporary'})"
        )
        result = self._query(cmd).startswith("SP")
        self._logger.debug_msg(f"Set setpoint result: {result}")
        return result

    def read_setpoint(self) -> Optional[float]:
        self._logger.debug_msg("Reading current setpoint")
        resp = self._query("SP?")
        try:
            sp = int(resp[2:].strip()) / 100.0
            self._logger.info(f"Current setpoint: {sp:.2f} °C")
            return sp
        except ValueError as exc:
            self._logger.error(f"Failed to parse setpoint: {exc}")
            return None

    def set_thermoregulation(self, state: bool) -> bool:
        self._logger.info(f"Setting thermoregulation: {'ON' if state else 'OFF'}")
        cmd = f"CA@+0000{1 if state else 0}"
        result = self._query(cmd).startswith("CA")
        self._logger.debug_msg(f"Set thermoregulation result: {result}")
        return result


class HuberThermostatTools:
    @staticmethod
    def auto_detect_huber_port(
        baudrate: int = HUBER_DEFAULT_BAUDRATE,
        timeout: float = HUBER_DEFAULT_TIMEOUT,
        debug: bool = False,
    ) -> Optional[str]:
        debug_logger = TLogger(debug)
        ports = [p.device for p in serial.tools.list_ports.comports()]
        debug_logger.info(f"Scanning ports: {ports}")
        print(f"Scanning ports: {ports}")

        for port in ports:
            try:
                debug_logger.debug_msg(f"Trying port: {port}")
                with serial.Serial(port, baudrate=baudrate, timeout=timeout) as ser:
                    if HuberThermostatI(ser, debug=debug).ping():
                        debug_logger.info(f"Huber thermostat detected on {port}")
                        print(f"Huber thermostat detected on {port}")
                        return port
            except (OSError, serial.SerialException) as exc:
                debug_logger.debug_msg(f"Port {port} failed: {exc}")
                continue

        debug_logger.warning("No Huber thermostat detected")
        print("No Huber thermostat detected.")
        return None


class ThermostatConnection:
    """Connection wrapper for the legacy PP/text Huber client."""

    def __init__(self, port: str = None, debug: bool = False):
        self.port = port
        self.debug = debug
        self.serial_conn = None
        self.thermostat = None
        self.last_error_code = None
        self.last_error_message = None
        self._mock_temp = 20.0
        self._mock_setpoint = 25.0

    def _set_error(self, code: str, message: str) -> None:
        self.last_error_code = code
        self.last_error_message = message
        logger.error(
            "huber_error",
            extra={
                "event": "huber_error",
                "error_code": code,
                "error_message": message,
                "port": self.port,
            },
        )

    def clear_error(self) -> None:
        if self.last_error_code is not None:
            logger.info(
                "huber_error_cleared",
                extra={
                    "event": "huber_error_cleared",
                    "error_code": self.last_error_code,
                    "port": self.port,
                },
            )
        self.last_error_code = None
        self.last_error_message = None

    def connect(self) -> bool:
        try:
            self.close()
            self.clear_error()
            if not self.port:
                self.port = HuberThermostatTools.auto_detect_huber_port(debug=self.debug)
            if not self.port:
                self._set_error("HUBER_PORT_NOT_FOUND", "No Huber thermostat port detected.")
                return False

            self.serial_conn = serial.Serial(
                self.port,
                baudrate=HUBER_DEFAULT_BAUDRATE,
                timeout=HUBER_DEFAULT_TIMEOUT,
            )
            self.thermostat = HuberThermostatI(self.serial_conn, debug=self.debug)
            if self.thermostat.ping():
                logger.info("huber_connect_ok", extra={"event": "huber_connect_ok", "port": self.port})
                return True

            self.close()
            self._set_error("HUBER_PING_FAILED", f"Huber thermostat did not respond on port {self.port}.")
            return False
        except (serial.SerialException, OSError, ValueError) as exc:
            self.close()
            self._set_error("HUBER_CONNECT_ERROR", f"Connection error on port {self.port}: {exc}")
            return False

    def read_temperature(self) -> Optional[float]:
        if not self.thermostat:
            self.clear_error()
            self._mock_temp += (self._mock_setpoint - self._mock_temp) * 0.05
            return round(self._mock_temp, 2)
        try:
            self.clear_error()
            return self.thermostat.read_bath_temperature()
        except (serial.SerialException, OSError, ValueError) as exc:
            self._set_error("HUBER_READ_TEMP_ERROR", f"Failed to read bath temperature: {exc}")
            return None

    def read_setpoint(self) -> Optional[float]:
        if not self.thermostat:
            self.clear_error()
            return self._mock_setpoint
        try:
            self.clear_error()
            return self.thermostat.read_setpoint()
        except (serial.SerialException, OSError, ValueError) as exc:
            self._set_error("HUBER_READ_SETPOINT_ERROR", f"Failed to read setpoint: {exc}")
            return None

    def set_setpoint(self, value: float) -> bool:
        if not self.thermostat:
            self.clear_error()
            self._mock_setpoint = value
            return True
        try:
            self.clear_error()
            return self.thermostat.set_setpoint(value)
        except (serial.SerialException, OSError, ValueError) as exc:
            self._set_error("HUBER_SET_SETPOINT_ERROR", f"Failed to set setpoint to {value}: {exc}")
            return False

    def set_thermoregulation(self, state: bool) -> bool:
        if not self.thermostat:
            self.clear_error()
            return True
        try:
            self.clear_error()
            return self.thermostat.set_thermoregulation(state)
        except (serial.SerialException, OSError, ValueError) as exc:
            self._set_error("HUBER_THERMOREG_ERROR", f"Failed to set thermoregulation to {state}: {exc}")
            return False

    def start_process(self) -> bool:
        return self.set_thermoregulation(True)

    def stop_process(self) -> bool:
        return self.set_thermoregulation(False)

    def close(self) -> None:
        if self.serial_conn:
            self.serial_conn.close()
            logger.info("huber_serial_closed", extra={"event": "huber_serial_closed", "port": self.port})
        self.serial_conn = None
        self.thermostat = None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read/control an old Huber thermostat with the legacy PP/text serial protocol.")
    parser.add_argument("--port", help="Serial port to use. If omitted, scan available ports with TI?.")
    parser.add_argument("--debug", action="store_true", help="Print serial debug messages to stderr.")
    parser.add_argument("--read", action="store_true", help="Read and print bath temperature and setpoint.")
    parser.add_argument("--setpoint", type=float, help="Set a temporary bath setpoint in degrees Celsius.")
    parser.add_argument("--start", action="store_true", help="Enable Huber thermoregulation/process control.")
    parser.add_argument("--stop", action="store_true", help="Disable Huber thermoregulation/process control.")
    args = parser.parse_args(argv)

    connection = ThermostatConnection(port=args.port, debug=args.debug)
    if not connection.connect():
        detail = connection.last_error_message or connection.last_error_code or "connect() returned False"
        print(f"Huber connection failed: {detail}", file=sys.stderr)
        return 1

    try:
        if args.setpoint is not None:
            if not connection.set_setpoint(args.setpoint):
                print("Huber setpoint command failed", file=sys.stderr)
                return 2
            print(f"Setpoint set to {args.setpoint:g} °C")
        if args.start:
            if not connection.start_process():
                print("Huber start-process command failed", file=sys.stderr)
                return 3
            print("Thermoregulation enabled")
        if args.stop:
            if not connection.stop_process():
                print("Huber stop-process command failed", file=sys.stderr)
                return 4
            print("Thermoregulation disabled")
        if args.read or (args.setpoint is None and not args.start and not args.stop):
            bath_temp = connection.read_temperature()
            setpoint = connection.read_setpoint()
            print(f"Bath temperature: {bath_temp} °C")
            print(f"Current setpoint: {setpoint} °C")
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
