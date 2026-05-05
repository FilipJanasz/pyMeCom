# -*- coding: utf-8 -*-
from typing import Optional
import logging
import serial

try:
    from huber_thermostat import (
        HuberThermostatI,
        HuberThermostatTools,
        HUBER_DEFAULT_BAUDRATE,
        HUBER_DEFAULT_TIMEOUT,
    )
    HUBER_AVAILABLE = True
except ImportError:
    HUBER_AVAILABLE = False


logger = logging.getLogger("huber.adapter")


class ThermostatConnection:
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
        if not HUBER_AVAILABLE:
            self.clear_error()
            logger.info(
                "huber_connect_simulation_mode",
                extra={"event": "huber_connect_simulation_mode", "port": self.port},
            )
            return True
            
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
                timeout=HUBER_DEFAULT_TIMEOUT
            )
            self.thermostat = HuberThermostatI(self.serial_conn, debug=self.debug)
            if self.thermostat.ping():
                logger.info("huber_connect_ok", extra={"event": "huber_connect_ok", "port": self.port})
                return True

            self.close()
            self._set_error("HUBER_PING_FAILED", f"Huber thermostat did not respond on port {self.port}.")
            return False
        except (serial.SerialException, OSError, ValueError) as e:
            self.close()
            self._set_error("HUBER_CONNECT_ERROR", f"Connection error on port {self.port}: {e}")
            return False
    
    def read_temperature(self) -> Optional[float]:
        if not HUBER_AVAILABLE or not self.thermostat:
            self.clear_error()
            self._mock_temp += (self._mock_setpoint - self._mock_temp) * 0.05
            return round(self._mock_temp, 2)
        try:
            self.clear_error()
            return self.thermostat.read_bath_temperature()
        except (serial.SerialException, OSError, ValueError) as e:
            self._set_error("HUBER_READ_TEMP_ERROR", f"Failed to read bath temperature: {e}")
            return None
    
    def read_setpoint(self) -> Optional[float]:
        if not HUBER_AVAILABLE or not self.thermostat:
            self.clear_error()
            return self._mock_setpoint
        try:
            self.clear_error()
            return self.thermostat.read_setpoint()
        except (serial.SerialException, OSError, ValueError) as e:
            self._set_error("HUBER_READ_SETPOINT_ERROR", f"Failed to read setpoint: {e}")
            return None
    
    def set_setpoint(self, value: float) -> bool:
        if not HUBER_AVAILABLE or not self.thermostat:
            self.clear_error()
            self._mock_setpoint = value
            return True
        try:
            self.clear_error()
            return self.thermostat.set_setpoint(value)
        except (serial.SerialException, OSError, ValueError) as e:
            self._set_error("HUBER_SET_SETPOINT_ERROR", f"Failed to set setpoint to {value}: {e}")
            return False
    
    def set_thermoregulation(self, state: bool) -> bool:
        if not HUBER_AVAILABLE or not self.thermostat:
            self.clear_error()
            return True
        try:
            self.clear_error()
            return self.thermostat.set_thermoregulation(state)
        except (serial.SerialException, OSError, ValueError) as e:
            self._set_error("HUBER_THERMOREG_ERROR", f"Failed to set thermoregulation to {state}: {e}")
            return False
    
    def close(self):
        if self.serial_conn:
            self.serial_conn.close()
            logger.info("huber_serial_closed", extra={"event": "huber_serial_closed", "port": self.port})
        self.serial_conn = None
        self.thermostat = None
