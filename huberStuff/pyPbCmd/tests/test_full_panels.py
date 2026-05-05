#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Debug with all panels and workers"""

import sys
print("[*] Starting with full panels", file=sys.stderr, flush=True)

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Label, RichLog
from textual.reactive import reactive
import asyncio

print("[*] Imports successful", file=sys.stderr, flush=True)

class TemperaturePanel(Static):
    temperature = reactive("20.0 °C")
    countdown = reactive(5)
    update_interval = reactive(5)

    def compose(self) -> ComposeResult:
        print("[TemperaturePanel.compose]", file=sys.stderr, flush=True)
        yield Label(id="temp_value")
        yield Label(id="temp_countdown")

    def on_mount(self) -> None:
        print("[TemperaturePanel.on_mount]", file=sys.stderr, flush=True)
        self.border_title = "Temperature"
        self.set_interval(1, self.tick)
        print("[TemperaturePanel.on_mount] set_interval done", file=sys.stderr, flush=True)
        self.run_worker(self.update_temperature_loop(), exclusive=False)
        print("[TemperaturePanel.on_mount] run_worker done", file=sys.stderr, flush=True)

    def tick(self) -> None:
        if self.countdown > 0:
            self.countdown -= 1

    async def update_temperature_loop(self) -> None:
        print("[update_temperature_loop] started", file=sys.stderr, flush=True)
        for i in range(3):
            await asyncio.sleep(1)
            print(f"[update_temperature_loop] tick {i}", file=sys.stderr, flush=True)

class SetpointPanel(Static):
    setpoint = reactive("25.0 °C")

    def compose(self) -> ComposeResult:
        print("[SetpointPanel.compose]", file=sys.stderr, flush=True)
        yield Label(id="sp_value")

    def on_mount(self) -> None:
        print("[SetpointPanel.on_mount]", file=sys.stderr, flush=True)
        self.border_title = "Setpoint"

class LoggerPanel(Static):
    is_logging = reactive(False)

    def compose(self) -> ComposeResult:
        print("[LoggerPanel.compose]", file=sys.stderr, flush=True)
        yield Label(id="logger_status")

    def on_mount(self) -> None:
        print("[LoggerPanel.on_mount]", file=sys.stderr, flush=True)
        self.border_title = "Logger"

class TestApp(App):
    def compose(self) -> ComposeResult:
        print("[compose] Starting", file=sys.stderr, flush=True)
        with Horizontal():
            with Vertical(id="main_container"):
                with Horizontal(id="input_row"):
                    print("[compose] Input", file=sys.stderr, flush=True)
                    yield Input(placeholder="Test", id="main_input")

                    print("[compose] TemperaturePanel", file=sys.stderr, flush=True)
                    yield TemperaturePanel(id="temp_panel")

                    print("[compose] SetpointPanel", file=sys.stderr, flush=True)
                    yield SetpointPanel(id="setpoint_panel")

                    print("[compose] LoggerPanel", file=sys.stderr, flush=True)
                    yield LoggerPanel(id="logger_panel")

                yield Label("", id="suggestions")
                yield RichLog(id="output")
        print("[compose] Done", file=sys.stderr, flush=True)

    def on_mount(self) -> None:
        print("[on_mount] Starting", file=sys.stderr, flush=True)
        self.query_one("#main_input", Input).focus()
        print("[on_mount] Done", file=sys.stderr, flush=True)

if __name__ == "__main__":
    print("[*] Creating app", file=sys.stderr, flush=True)
    app = TestApp()

    print("[*] Running app", file=sys.stderr, flush=True)
    app.run()

    print("[*] Done", file=sys.stderr, flush=True)
