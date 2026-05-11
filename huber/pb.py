from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from enum import IntEnum
from typing import Final, Optional, Sequence

import serial
import serial.tools.list_ports


HUBER_DEFAULT_BAUDRATE: Final[int] = 9600
HUBER_DEFAULT_TIMEOUT: Final[float] = 1.0
HUBER_RESPONSE_SIZE: Final[int] = 14
HUBER_COMMAND_TERMINATOR: Final[bytes] = b"\r\n"
HUBER_AVAILABLE: Final[bool] = True
HUBER_CLIENT_SOURCE: Final[str] = __name__
HUBER_TEMPERATURE_SCALE: Final[float] = 100.0

logger = logging.getLogger("huber.pb")


class PBVariable(IntEnum):
    SETPOINT = 0x00
    BATH_TEMPERATURE = 0x01
    PROCESS_TEMPERATURE = 0x07
    TEMP_CONTROL_ACTIVE = 0x14
    CIRCULATION_ACTIVE = 0x16


class PBProtocolError(Exception):
    """Raised when a Huber PB response cannot be parsed or validated."""


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


def encode_i32(value: int) -> int:
    if value < 0:
        value = (1 << 32) + value
    return value & 0xFFFFFFFF


def decode_i32(value: int) -> int:
    if value & 0x80000000:
        return value - (1 << 32)
    return value


def compose_command(addr: int, value: Optional[int] = None) -> bytes:
    payload = "********" if value is None else f"{encode_i32(value):08X}"
    return f"{{M{addr:02X}{payload}\r\n".encode("ascii")


def parse_response(response: bytes, expected_addr: int, expected_value: Optional[int] = None) -> Optional[int]:
    if len(response) != HUBER_RESPONSE_SIZE:
        raise PBProtocolError(f"invalid PB response size: expected {HUBER_RESPONSE_SIZE}, got {len(response)}")
    decoded = response.decode("ascii", errors="strict")
    if decoded[0:2] != "{S" or decoded[12:14] != "\r\n":
        raise PBProtocolError(f"invalid PB response framing: {decoded!r}")
    addr = int(decoded[2:4], 16)
    if addr != expected_addr:
        raise PBProtocolError(f"unexpected PB response address: expected 0x{expected_addr:02X}, got 0x{addr:02X}")
    value_text = decoded[4:12]
    value = None if value_text == "********" else decode_i32(int(value_text, 16))
    if expected_value is not None and value != expected_value:
        raise PBProtocolError(f"unexpected PB response value: expected {expected_value}, got {value}")
    return value


class HuberThermostatPB:
    """Huber PB protocol client using `{M...}` requests and `{S...}` responses."""

    def __init__(self, interface_serial: serial.Serial, debug: bool = False):
        self._serial = interface_serial
        self._logger = TLogger(debug)
        self._logger.info("HuberThermostatPB initialized")

    def _exchange(self, addr: int, value: Optional[int] = None) -> Optional[int]:
        command = compose_command(addr, value)
        self._logger.debug_msg(f"Sending PB command: {command!r}")
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()
        self._serial.write(command)
        self._serial.flush()
        response = self._serial.read(HUBER_RESPONSE_SIZE)
        self._logger.debug_msg(f"Received PB response: {response!r}")
        return parse_response(response, expected_addr=addr, expected_value=value)

    def ping(self) -> bool:
        try:
            return self.read_bath_temperature() is not None
        except (OSError, serial.SerialException, ValueError, PBProtocolError) as exc:
            self._logger.error(f"PB ping failed: {exc}")
            return False

    def read_bath_temperature(self) -> Optional[float]:
        return self.read_temperature(PBVariable.BATH_TEMPERATURE)

    def read_process_temperature(self) -> Optional[float]:
        return self.read_temperature(PBVariable.PROCESS_TEMPERATURE)

    def read_temperature(self, variable: PBVariable) -> Optional[float]:
        try:
            value = self._exchange(int(variable))
            if value is None:
                return None
            return value / HUBER_TEMPERATURE_SCALE
        except (OSError, serial.SerialException, ValueError, PBProtocolError) as exc:
            self._logger.error(f"Failed to read PB temperature {variable.name}: {exc}")
            return None

    def read_setpoint(self) -> Optional[float]:
        try:
            value = self._exchange(int(PBVariable.SETPOINT))
            if value is None:
                return None
            return value / HUBER_TEMPERATURE_SCALE
        except (OSError, serial.SerialException, ValueError, PBProtocolError) as exc:
            self._logger.error(f"Failed to read PB setpoint: {exc}")
            return None

    def set_setpoint(self, value_celsius: float) -> bool:
        value = int(round(value_celsius * HUBER_TEMPERATURE_SCALE))
        try:
            self._exchange(int(PBVariable.SETPOINT), value)
            return True
        except (OSError, serial.SerialException, ValueError, PBProtocolError) as exc:
            self._logger.error(f"Failed to set PB setpoint to {value_celsius}: {exc}")
            return False

    def set_thermoregulation(self, state: bool) -> bool:
        try:
            self._exchange(int(PBVariable.TEMP_CONTROL_ACTIVE), 1 if state else 0)
            return True
        except (OSError, serial.SerialException, ValueError, PBProtocolError) as exc:
            self._logger.error(f"Failed to set PB thermoregulation to {state}: {exc}")
            return False

    def set_pump_state(self, on_off: bool) -> bool:
        try:
            self._exchange(int(PBVariable.CIRCULATION_ACTIVE), 1 if on_off else 0)
            return True
        except (OSError, serial.SerialException, ValueError, PBProtocolError) as exc:
            self._logger.error(f"Failed to set PB pump/circulation to {on_off}: {exc}")
            return False


class HuberThermostatTools:
    @staticmethod
    def auto_detect_huber_port(
        baudrate: int = HUBER_DEFAULT_BAUDRATE,
        timeout: float = HUBER_DEFAULT_TIMEOUT,
        debug: bool = False,
    ) -> Optional[str]:
        debug_logger = TLogger(debug)
        ports = [p.device for p in serial.tools.list_ports.comports()]
        debug_logger.info(f"Scanning PB ports: {ports}")
        print(f"Scanning PB ports: {ports}")

        for port in ports:
            try:
                debug_logger.debug_msg(f"Trying PB port: {port}")
                with serial.Serial(port, baudrate=baudrate, timeout=timeout) as ser:
                    if HuberThermostatPB(ser, debug=debug).ping():
                        debug_logger.info(f"Huber PB thermostat detected on {port}")
                        print(f"Huber PB thermostat detected on {port}")
                        return port
            except (OSError, serial.SerialException) as exc:
                debug_logger.debug_msg(f"PB port {port} failed: {exc}")
                continue

        debug_logger.warning("No Huber PB thermostat detected")
        print("No Huber PB thermostat detected.")
        return None


class ThermostatConnection:
    """Connection wrapper for the Huber PB client."""

    def __init__(self, port: str = None, debug: bool = False):
        self.port = port
        self.debug = debug
        self.serial_conn = None
        self.thermostat = None
        self.last_error_code = None
        self.last_error_message = None
        self._mock_temp = 20.0
        self._mock_setpoint = 25.0
        self._mock_pump_state = False
        self._mock_thermoregulation = False

    def _set_error(self, code: str, message: str) -> None:
        self.last_error_code = code
        self.last_error_message = message
        logger.error(
            "huber_pb_error",
            extra={"event": "huber_pb_error", "error_code": code, "error_message": message, "port": self.port},
        )

    def clear_error(self) -> None:
        self.last_error_code = None
        self.last_error_message = None

    def connect(self) -> bool:
        try:
            self.close()
            self.clear_error()
            if not self.port:
                self.port = HuberThermostatTools.auto_detect_huber_port(debug=self.debug)
            if not self.port:
                self._set_error("HUBER_PB_PORT_NOT_FOUND", "No Huber PB thermostat port detected.")
                return False
            self.serial_conn = serial.Serial(
                self.port,
                baudrate=HUBER_DEFAULT_BAUDRATE,
                timeout=HUBER_DEFAULT_TIMEOUT,
            )
            self.thermostat = HuberThermostatPB(self.serial_conn, debug=self.debug)
            if self.thermostat.ping():
                logger.info("huber_pb_connect_ok", extra={"event": "huber_pb_connect_ok", "port": self.port})
                return True
            self.close()
            self._set_error("HUBER_PB_PING_FAILED", f"Huber PB thermostat did not respond on port {self.port}.")
            return False
        except (serial.SerialException, OSError, ValueError) as exc:
            self.close()
            self._set_error("HUBER_PB_CONNECT_ERROR", f"PB connection error on port {self.port}: {exc}")
            return False

    def read_temperature(self) -> Optional[float]:
        if not self.thermostat:
            self.clear_error()
            self._mock_temp += (self._mock_setpoint - self._mock_temp) * 0.05
            return round(self._mock_temp, 2)
        self.clear_error()
        return self.thermostat.read_bath_temperature()

    def read_setpoint(self) -> Optional[float]:
        if not self.thermostat:
            self.clear_error()
            return self._mock_setpoint
        self.clear_error()
        return self.thermostat.read_setpoint()

    def set_setpoint(self, value: float) -> bool:
        if not self.thermostat:
            self.clear_error()
            self._mock_setpoint = value
            return True
        self.clear_error()
        return self.thermostat.set_setpoint(value)

    def set_thermoregulation(self, state: bool) -> bool:
        if not self.thermostat:
            self.clear_error()
            self._mock_thermoregulation = state
            return True
        self.clear_error()
        return self.thermostat.set_thermoregulation(state)

    def set_pump_state(self, on_off: bool) -> bool:
        if not self.thermostat:
            self.clear_error()
            self._mock_pump_state = on_off
            return True
        self.clear_error()
        return self.thermostat.set_pump_state(on_off)

    def start_process(self) -> bool:
        return self.set_thermoregulation(True)

    def stop_process(self) -> bool:
        return self.set_thermoregulation(False)

    def close(self) -> None:
        if self.serial_conn:
            self.serial_conn.close()
            logger.info("huber_pb_serial_closed", extra={"event": "huber_pb_serial_closed", "port": self.port})
        self.serial_conn = None
        self.thermostat = None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read/control a Huber thermostat with the PB serial protocol.")
    parser.add_argument("--port", help="Serial port to use. If omitted, scan available ports with a PB bath-temperature read.")
    parser.add_argument("--debug", action="store_true", help="Print serial debug messages to stderr.")
    parser.add_argument("--read", action="store_true", help="Read and print bath temperature and setpoint.")
    parser.add_argument("--setpoint", type=float, help="Set a bath setpoint in degrees Celsius.")
    parser.add_argument("--start", action="store_true", help="Enable Huber thermoregulation/process control.")
    parser.add_argument("--stop", action="store_true", help="Disable Huber thermoregulation/process control.")
    parser.add_argument("--pump-on", action="store_true", help="Enable PB circulation/pump control.")
    parser.add_argument("--pump-off", action="store_true", help="Disable PB circulation/pump control.")
    args = parser.parse_args(argv)

    connection = ThermostatConnection(port=args.port, debug=args.debug)
    if not connection.connect():
        detail = connection.last_error_message or connection.last_error_code or "connect() returned False"
        print(f"Huber PB connection failed: {detail}", file=sys.stderr)
        return 1

    try:
        if args.setpoint is not None and not connection.set_setpoint(args.setpoint):
            print("Huber PB setpoint command failed", file=sys.stderr)
            return 2
        if args.start and not connection.start_process():
            print("Huber PB start-process command failed", file=sys.stderr)
            return 3
        if args.stop and not connection.stop_process():
            print("Huber PB stop-process command failed", file=sys.stderr)
            return 4
        if args.pump_on and not connection.set_pump_state(True):
            print("Huber PB pump-on command failed", file=sys.stderr)
            return 5
        if args.pump_off and not connection.set_pump_state(False):
            print("Huber PB pump-off command failed", file=sys.stderr)
            return 6
        if args.read or not any((args.setpoint is not None, args.start, args.stop, args.pump_on, args.pump_off)):
            print(f"Bath temperature: {connection.read_temperature()} °C")
            print(f"Current setpoint: {connection.read_setpoint()} °C")
    finally:
        connection.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
