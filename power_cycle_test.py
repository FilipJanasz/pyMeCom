"""Backward-compatible wrapper for the COM power-cycle script."""
from power_cycle_test_com import main

if __name__ == "__main__":
    raise SystemExit(main())
