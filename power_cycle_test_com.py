"""Run a timed power-step test and write structured logs to disk.

This is a convenience wrapper around ``mecom.calibration`` for the common
"did the board execute each requested power step and wait long enough?" use
case. It reads the same JSON config format as the calibration runner and writes
metadata, JSONL, and CSV logs into the configured output directory.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from mecom.calibration import CalibrationConfig, TecCalibrationRunner, configure_logging


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run a timed MeCom power-cycle test and log each step to metadata, "
            "JSONL, and CSV output files."
        )
    )
    parser.add_argument("--config", required=True, help="Path to JSON configuration file")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    configure_logging(verbose=args.verbose)
    config = CalibrationConfig.from_json_file(args.config)
    runner = TecCalibrationRunner(config)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
