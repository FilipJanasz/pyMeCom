#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test all imports from main.py"""

import sys
print("[*] Testing imports", file=sys.stderr, flush=True)

try:
    print("[1] from textual.app import App, ComposeResult", file=sys.stderr, flush=True)
    from textual.app import App, ComposeResult
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[2] from textual.containers import Horizontal, Vertical", file=sys.stderr, flush=True)
    from textual.containers import Horizontal, Vertical
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[3] from textual.widgets import Static, Input, Label, RichLog, Checkbox, Button", file=sys.stderr, flush=True)
    from textual.widgets import Static, Input, Label, RichLog, Checkbox, Button
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[4] from textual.reactive import reactive", file=sys.stderr, flush=True)
    from textual.reactive import reactive
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[5] from textual.screen import ModalScreen", file=sys.stderr, flush=True)
    from textual.screen import ModalScreen
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[6] import asyncio", file=sys.stderr, flush=True)
    import asyncio
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[7] from datetime import datetime", file=sys.stderr, flush=True)
    from datetime import datetime
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[8] from typing import Optional", file=sys.stderr, flush=True)
    from typing import Optional
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[9] import csv", file=sys.stderr, flush=True)
    import csv
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[10] import os", file=sys.stderr, flush=True)
    import os
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[11] from pathlib import Path", file=sys.stderr, flush=True)
    from pathlib import Path
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[12] import serial", file=sys.stderr, flush=True)
    import serial
    print("[✓] Success", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[13] from huber_thermostat import ...", file=sys.stderr, flush=True)
    from huber_thermostat import (
        HuberThermostatI,
        HuberThermostatTools,
        TemperatureVar,
        HUBER_DEFAULT_BAUDRATE,
        HUBER_DEFAULT_TIMEOUT,
    )
    print("[✓] Success", file=sys.stderr, flush=True)
except ImportError as e:
    print(f"[!] ImportError (expected): {e}", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

try:
    print("[14] import matplotlib", file=sys.stderr, flush=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    print("[✓] Success", file=sys.stderr, flush=True)
except ImportError as e:
    print(f"[!] ImportError (expected): {e}", file=sys.stderr, flush=True)
except Exception as e:
    print(f"[✗] Error: {e}", file=sys.stderr, flush=True)

print("\n[*] All imports tested", file=sys.stderr, flush=True)
