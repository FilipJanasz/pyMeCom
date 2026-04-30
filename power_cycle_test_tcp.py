"""Run a timed power-step test over TCP and write structured logs to disk."""

from __future__ import annotations

from workflows.automation.tcp.tcp_calibration_runner import main

if __name__ == "__main__":
    raise SystemExit(main())
