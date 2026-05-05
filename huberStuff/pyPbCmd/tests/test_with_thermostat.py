#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Debug with ThermostatConnection"""

import sys
print("[*] Starting with ThermostatConnection", file=sys.stderr, flush=True)

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Label, RichLog
from textual.reactive import reactive
import asyncio

print("[*] Imports successful", file=sys.stderr, flush=True)

# Copy ThermostatConnection from main.py
class ThermostatConnection:
    def __init__(self, port: str = None, debug: bool = False):
        print("[ThermostatConnection.__init__]", file=sys.stderr, flush=True)
        self.port = port
        self.debug = debug
        self.serial_conn = None
        self.thermostat = None
        self._mock_temp = 20.0
        self._mock_setpoint = 25.0
        print("[ThermostatConnection.__init__] Done", file=sys.stderr, flush=True)

    def connect(self) -> bool:
        print("[ThermostatConnection.connect] Starting", file=sys.stderr, flush=True)
        # Simplified - just return True for simulation
        print("[ThermostatConnection.connect] Done", file=sys.stderr, flush=True)
        return True

    def read_temperature(self):
        self._mock_temp += (self._mock_setpoint - self._mock_temp) * 0.05
        return round(self._mock_temp, 2)

    def read_setpoint(self):
        return self._mock_setpoint

    def close(self):
        pass

class TemperaturePanel(Static):
    temperature = reactive("20.0 °C")

    def compose(self) -> ComposeResult:
        yield Label(id="temp_value")
        yield Label(id="temp_countdown")

    def on_mount(self) -> None:
        print("[TemperaturePanel.on_mount]", file=sys.stderr, flush=True)
        self.border_title = "Temperature"

class TestApp(App):
    def __init__(self):
        print("[TestApp.__init__] Starting", file=sys.stderr, flush=True)
        super().__init__()
        print("[TestApp.__init__] Creating thermostat", file=sys.stderr, flush=True)
        self.thermostat = ThermostatConnection()
        print("[TestApp.__init__] Thermostat created", file=sys.stderr, flush=True)

    def compose(self) -> ComposeResult:
        print("[compose] Starting", file=sys.stderr, flush=True)
        with Horizontal():
            with Vertical(id="main_container"):
                with Horizontal(id="input_row"):
                    yield Input(placeholder="Test", id="main_input")
                    yield TemperaturePanel(id="temp_panel")

                yield Label("", id="suggestions")
                yield RichLog(id="output")
        print("[compose] Done", file=sys.stderr, flush=True)

    def on_mount(self) -> None:
        print("[on_mount] Starting", file=sys.stderr, flush=True)
        try:
            print("[on_mount] Setting focus", file=sys.stderr, flush=True)
            self.query_one("#main_input", Input).focus()
            print("[on_mount] Focus done", file=sys.stderr, flush=True)

            print("[on_mount] Connecting thermostat", file=sys.stderr, flush=True)
            connected = self.thermostat.connect()
            print(f"[on_mount] Connected: {connected}", file=sys.stderr, flush=True)

            print("[on_mount] Done", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[on_mount] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    print("[*] Creating app", file=sys.stderr, flush=True)
    app = TestApp()

    print("[*] Running app", file=sys.stderr, flush=True)
    app.run()

    print("[*] Done", file=sys.stderr, flush=True)
