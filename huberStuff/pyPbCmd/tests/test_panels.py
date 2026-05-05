#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Debug with panels"""

import sys
print("[*] Starting with panels", file=sys.stderr, flush=True)

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Label, RichLog
from textual.reactive import reactive
import asyncio

print("[*] Imports successful", file=sys.stderr, flush=True)

class TemperaturePanel(Static):
    temperature = reactive("20.0 °C")

    def compose(self) -> ComposeResult:
        print("[TemperaturePanel.compose] called", file=sys.stderr, flush=True)
        yield Label(id="temp_value")
        yield Label(id="temp_countdown")

    def on_mount(self) -> None:
        print("[TemperaturePanel.on_mount] called", file=sys.stderr, flush=True)
        self.border_title = "Temperature"

class TestApp(App):
    def compose(self) -> ComposeResult:
        print("[compose] Starting", file=sys.stderr, flush=True)
        with Horizontal():
            with Vertical(id="main_container"):
                with Horizontal(id="input_row"):
                    print("[compose] Creating Input", file=sys.stderr, flush=True)
                    yield Input(placeholder="Test", id="main_input")

                    print("[compose] Creating TemperaturePanel", file=sys.stderr, flush=True)
                    yield TemperaturePanel(id="temp_panel")
                    print("[compose] Created TemperaturePanel", file=sys.stderr, flush=True)

                yield Label("Test")
                yield RichLog(id="output")
        print("[compose] Done", file=sys.stderr, flush=True)

    def on_mount(self) -> None:
        print("[on_mount] Starting", file=sys.stderr, flush=True)

if __name__ == "__main__":
    print("[*] Creating app", file=sys.stderr, flush=True)
    app = TestApp()

    print("[*] Running app", file=sys.stderr, flush=True)
    app.run()

    print("[*] Done", file=sys.stderr, flush=True)
