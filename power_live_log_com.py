from __future__ import annotations

import sys
from typing import Optional, Sequence

from workflows.automation.common.live_logger import LiveLogger, LiveLoggerConfig, configure_logging


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Continuous COM logger with Meerstetter-style CSV headers")
    parser.add_argument("--config", required=True, help="Path to JSON config")
    parser.add_argument("--hz", type=float, default=None, help="Sample rate in Hz (defaults to acquisition_hz from config, else 10.0)")
    parser.add_argument("--duration-seconds", type=float, default=None, help="Optional duration limit (overrides config)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    config = LiveLoggerConfig.from_json_file(args.config)
    logger = LiveLogger(config)
    try:
        duration_seconds = args.duration_seconds if args.duration_seconds is not None else config.duration_seconds
        hz = args.hz if args.hz is not None else config.acquisition_hz
        output = logger.run(hz=hz, duration_seconds=duration_seconds)
    except KeyboardInterrupt:
        return 130
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
