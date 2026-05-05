#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal Textual test"""

import sys
print("[*] Starting minimal Textual test", file=sys.stderr, flush=True)

from textual.app import App, ComposeResult
from textual.widgets import Static

print("[*] Imports successful", file=sys.stderr, flush=True)

class MinimalApp(App):
    def compose(self) -> ComposeResult:
        print("[compose] called", file=sys.stderr, flush=True)
        yield Static("Hello, World!")

    def on_mount(self) -> None:
        print("[on_mount] called", file=sys.stderr, flush=True)

if __name__ == "__main__":
    print("[*] Creating app", file=sys.stderr, flush=True)
    app = MinimalApp()

    print("[*] Calling app.run()", file=sys.stderr, flush=True)
    app.run()

    print("[*] App finished", file=sys.stderr, flush=True)
