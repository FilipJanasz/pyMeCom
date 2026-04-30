from __future__ import annotations

import sys
from typing import Optional, Sequence

from workflows.automation.common.live_logger import LiveLogger, LiveLoggerConfig, configure_logging, default_live_parameters


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Quick COM live logging smoke test wrapper")
    parser.add_argument("--serial-port", default=None, help="COM port (example: COM3). If omitted, auto-detect is used.")
    parser.add_argument("--channel", type=int, default=1, help="Controller channel instance for CHx measurements")
    parser.add_argument("--address", type=int, default=1, help="MeCom device address")
    parser.add_argument("--hz", type=float, default=1.0, help="Sample rate in Hz")
    parser.add_argument("--duration-seconds", type=float, default=120.0, help="Capture duration")
    parser.add_argument("--output-directory", default="live_logs", help="Output directory for CSV/metadata")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    config = LiveLoggerConfig(
        transport="com",
        serial_port=args.serial_port,
        serial_port_autodetect=args.serial_port is None,
        address=args.address,
        channel=args.channel,
        output_directory=args.output_directory,
        output_prefix="power_live_log_test_com",
        parameters=default_live_parameters(channel=args.channel),
    )
    output = LiveLogger(config).run(hz=args.hz, duration_seconds=args.duration_seconds)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
