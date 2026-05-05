# -*- coding: utf-8 -*-
import sys
import serial
import serial.tools.list_ports
from enum import Enum
from typing import Final, Optional
from datetime import datetime


HUBER_DEFAULT_BAUDRATE: Final[int] = 9600
HUBER_DEFAULT_TIMEOUT: Final[float] = 1.0
HUBER_RESPONSE_SIZE: Final[int] = 14
HUBER_COMMAND_TERMINATOR: Final[bytes] = b"\r\n"
HUBER_PING_COMMAND: Final[bytes] = b"TI?\r\n"


class TemperatureVar(Enum):
    BATH = "TI"
    PROCESS = "TE"


class TLogger:
    def __init__(self, debug: bool = False):
        self.debug = debug
    
    def log(self, message: str, level: str = "INFO"):
        if self.debug:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] [{level}] {message}", file=sys.stderr)
    
    def info(self, message: str):
        self.log(message, "INFO")
    
    def debug_msg(self, message: str):
        self.log(message, "DEBUG")
    
    def warning(self, message: str):
        self.log(message, "WARNING")
    
    def error(self, message: str):
        self.log(message, "ERROR")


class HuberThermostatI:

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
        except (OSError, serial.SerialException) as e:
            self._logger.error(f"Ping failed with exception: {e}")
            return False

    def read_temperature(self, var: TemperatureVar) -> Optional[float]:
        try:
            self._logger.debug_msg(f"Reading temperature for variable: {var.value}")
            raw = self._query(f"{var.value}?")
            val_str = raw[len(var.value):].strip()
            temp = int(val_str) / 100.0
            self._logger.info(f"Temperature {var.value}: {temp:.2f} °C")
            return temp
        except (ValueError, serial.SerialException) as e:
            self._logger.error(f"Failed to read temperature {var.value}: {e}")
            return None

    def read_bath_temperature(self) -> Optional[float]:
        return self.read_temperature(TemperatureVar.BATH)

    def read_process_temperature(self) -> Optional[float]:
        return self.read_temperature(TemperatureVar.PROCESS)

    def set_setpoint(self, value_celsius: float, permanent: bool = False) -> bool:
        val_str = f"{value_celsius:+07.2f}".replace('.', '')
        cmd = f"SP{'&' if permanent else '@'}{val_str}"
        self._logger.info(f"Setting setpoint to {value_celsius:.2f} °C ({'permanent' if permanent else 'temporary'})")
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
        except ValueError as e:
            self._logger.error(f"Failed to parse setpoint: {e}")
            return None

    def set_second_setpoint(self, value_celsius: float, permanent: bool = False) -> bool:
        val_str = f"{value_celsius:+07.2f}".replace('.', '')
        cmd = f"SP2{'&' if permanent else '@'}{val_str}"
        self._logger.info(f"Setting second setpoint to {value_celsius:.2f} °C")
        result = self._query(cmd).startswith("SP2")
        self._logger.debug_msg(f"Set second setpoint result: {result}")
        return result

    def read_second_setpoint(self) -> Optional[float]:
        self._logger.debug_msg("Reading second setpoint")
        resp = self._query("SP2?")
        try:
            sp2 = int(resp[3:].strip()) / 100.0
            self._logger.info(f"Second setpoint: {sp2:.2f} °C")
            return sp2
        except ValueError as e:
            self._logger.error(f"Failed to parse second setpoint: {e}")
            return None

    def set_limits(self, low: float, high: float) -> bool:
        self._logger.info(f"Setting limits: low={low:.2f} °C, high={high:.2f} °C")
        low_str = f"{low:+07.2f}".replace('.', '')
        high_str = f"{high:+07.2f}".replace('.', '')
        ok1 = self._query(f"LL&{low_str}").startswith("LL")
        ok2 = self._query(f"LH&{high_str}").startswith("LH")
        result = ok1 and ok2
        self._logger.debug_msg(f"Set limits result: {result}")
        return result

    def read_limits(self) -> tuple[Optional[float], Optional[float]]:
        self._logger.debug_msg("Reading limits")
        low, high = None, None
        try:
            resp_low = self._query("LL?")
            low = int(resp_low[2:].strip()) / 100.0
        except ValueError as e:
            self._logger.error(f"Failed to parse low limit: {e}")
        try:
            resp_high = self._query("LH?")
            high = int(resp_high[2:].strip()) / 100.0
        except ValueError as e:
            self._logger.error(f"Failed to parse high limit: {e}")
        self._logger.info(f"Limits: low={low}, high={high}")
        return low, high

    def set_alarm_limits(self, low: float, high: float) -> bool:
        self._logger.info(f"Setting alarm limits: low={low:.2f} °C, high={high:.2f} °C")
        low_str = f"{low:+07.2f}".replace('.', '')
        high_str = f"{high:+07.2f}".replace('.', '')
        ok1 = self._query(f"AI@{low_str}").startswith("AI")
        ok2 = self._query(f"AA@{high_str}").startswith("AA")
        result = ok1 and ok2
        self._logger.debug_msg(f"Set alarm limits result: {result}")
        return result

    def read_alarm_limits(self) -> tuple[Optional[float], Optional[float]]:
        self._logger.debug_msg("Reading alarm limits")
        low, high = None, None
        try:
            resp_low = self._query("AI?")
            low = int(resp_low[2:].strip()) / 100.0
        except ValueError as e:
            self._logger.error(f"Failed to parse alarm low limit: {e}")
        try:
            resp_high = self._query("AA?")
            high = int(resp_high[2:].strip()) / 100.0
        except ValueError as e:
            self._logger.error(f"Failed to parse alarm high limit: {e}")
        self._logger.info(f"Alarm limits: low={low}, high={high}")
        return low, high

    def set_thermoregulation(self, state: bool) -> bool:
        self._logger.info(f"Setting thermoregulation: {'ON' if state else 'OFF'}")
        cmd = f"CA@+0000{1 if state else 0}"
        result = self._query(cmd).startswith("CA")
        self._logger.debug_msg(f"Set thermoregulation result: {result}")
        return result

    def set_watchdog(self, seconds: int, mode: int = 1) -> bool:
        if seconds < 0 or seconds > 150:
            self._logger.warning(f"Invalid watchdog seconds: {seconds} (must be 0-150)")
            return False
        self._logger.info(f"Setting watchdog: {seconds}s, mode={mode}")
        cmd = f"WD{mode}@+{seconds:05d}"
        result = self._query(cmd).startswith(f"WD{mode}")
        self._logger.debug_msg(f"Set watchdog result: {result}")
        return result

    def disable_watchdog(self, mode: int = 1) -> bool:
        self._logger.info(f"Disabling watchdog (mode={mode})")
        result = self._query(f"WD{mode}@+00000").startswith(f"WD{mode}")
        self._logger.debug_msg(f"Disable watchdog result: {result}")
        return result


class HuberThermostatTools:

    @staticmethod
    def auto_detect_huber_port(
        baudrate: int = HUBER_DEFAULT_BAUDRATE,
        timeout: float = HUBER_DEFAULT_TIMEOUT,
        debug: bool = False
    ) -> Optional[str]:
        logger = TLogger(debug)
        ports = [p.device for p in serial.tools.list_ports.comports()]
        logger.info(f"Scanning ports: {ports}")
        print(f"Scanning ports: {ports}")

        for port in ports:
            try:
                logger.debug_msg(f"Trying port: {port}")
                with serial.Serial(port, baudrate=baudrate, timeout=timeout) as ser:
                    if HuberThermostatI(ser, debug=debug).ping():
                        logger.info(f"Huber thermostat detected on {port}")
                        print(f"Huber thermostat detected on {port}")
                        return port
            except (OSError, serial.SerialException) as e:
                logger.debug_msg(f"Port {port} failed: {e}")
                continue

        logger.warning("No Huber thermostat detected")
        print("No Huber thermostat detected.")
        return None


if __name__ == '__main__':
    print("=== HUBER THERMOSTAT TEST RUN ===")
    

    DEBUG_MODE = False

    port = HuberThermostatTools.auto_detect_huber_port(debug=DEBUG_MODE)
    if not port:
        raise RuntimeError("Huber port not found.")

    with serial.Serial(port, baudrate=HUBER_DEFAULT_BAUDRATE, timeout=HUBER_DEFAULT_TIMEOUT) as ser:
        thermostat = HuberThermostatI(ser, debug=DEBUG_MODE)

        if not thermostat.ping():
            raise RuntimeError("Device did not respond to ping command.")

        bath = thermostat.read_bath_temperature()
        proc = thermostat.read_process_temperature()



        thermostat.set_setpoint(22.60)

        import time
        time.sleep(5)

        sp = thermostat.read_setpoint()

        print(f" Bath temperature:    {bath:.2f} °C")
        print(f" Process temperature: {proc:.2f} °C")
        print(f" Current setpoint:    {sp:.2f} °C")

