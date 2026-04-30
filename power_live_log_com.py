from __future__ import annotations

import sys
from typing import Optional, Sequence

from workflows.automation.common.live_logger import LiveLogger, LiveLoggerConfig, configure_logging


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Continuous 1Hz COM logger with Meerstetter-style CSV headers")
    parser.add_argument("--config", required=True, help="Path to JSON config")
    parser.add_argument("--hz", type=float, default=1.0, help="Sample rate in Hz (default: 1.0)")
    parser.add_argument("--duration-seconds", type=float, default=None, help="Optional duration limit")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    config = LiveLoggerConfig.from_json_file(args.config)
    logger = LiveLogger(config)
    try:
        output = logger.run(hz=args.hz, duration_seconds=args.duration_seconds)
    except KeyboardInterrupt:
        return 130
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
