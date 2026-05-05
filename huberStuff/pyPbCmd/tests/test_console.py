#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Debug ConsoleApp components"""

import sys
print("[*] Starting ConsoleApp debug", file=sys.stderr, flush=True)

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Label, RichLog

print("[*] Imports successful", file=sys.stderr, flush=True)

class TestApp(App):
    def compose(self) -> ComposeResult:
        print("[compose] Starting", file=sys.stderr, flush=True)
        with Horizontal():
            with Vertical(id="main_container"):
                print("[compose] Creating Input", file=sys.stderr, flush=True)
                yield Input(placeholder="Test", id="main_input")
                print("[compose] Created Input", file=sys.stderr, flush=True)

                yield Label("Test")
                print("[compose] Created Label", file=sys.stderr, flush=True)

                yield RichLog(id="output")
                print("[compose] Created RichLog", file=sys.stderr, flush=True)
        print("[compose] Done", file=sys.stderr, flush=True)

    def on_mount(self) -> None:
        print("[on_mount] Starting", file=sys.stderr, flush=True)
        try:
            self.query_one("#main_input", Input).focus()
            print("[on_mount] Focus done", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[on_mount] Error: {e}", file=sys.stderr, flush=True)

if __name__ == "__main__":
    print("[*] Creating app", file=sys.stderr, flush=True)
    app = TestApp()

    print("[*] Running app", file=sys.stderr, flush=True)
    app.run()

    print("[*] Done", file=sys.stderr, flush=True)
