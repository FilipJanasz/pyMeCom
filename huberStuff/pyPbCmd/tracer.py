#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Python tracer
Hooks into sys.settrace() and sys.excepthook() for detailed execution tracing
"""

import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime
import traceback as tb

class DetailedTracer:
    def __init__(self, log_file=None, max_depth=10):
        self.log_file = log_file or f"detailed_trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self.start_time = datetime.now()
        self.max_depth = max_depth
        self.call_depth = 0
        self.log_handle = None
        self.original_excepthook = None
        self.original_settrace = None

    def write_log(self, message, force_flush=False):
        """Write to log file"""
        try:
            if self.log_handle:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                self.log_handle.write(f"[{timestamp}] {message}\n")
                if force_flush:
                    self.log_handle.flush()
        except Exception as e:
            print(f"[TRACER ERROR] {e}", file=sys.stderr, flush=True)

    def start_logging(self):
        """Initialize logging and hooks"""
        try:
            self.log_handle = open(self.log_file, 'w', encoding='utf-8', buffering=1)
            self.write_log("=" * 100)
            self.write_log(f"pyPbCmd Detailed Runtime Trace")
            self.write_log(f"Started: {self.start_time}")
            self.write_log(f"Python: {sys.version}")
            self.write_log(f"Platform: {sys.platform}")
            self.write_log(f"Working dir: {os.getcwd()}")
            self.write_log("=" * 100)
            self.write_log("")
            return True
        except Exception as e:
            print(f"[ERROR] Cannot open log file: {e}", file=sys.stderr)
            return False

    def trace_calls(self, frame, event, arg):
        """Trace function calls"""
        if self.call_depth > self.max_depth:
            return None

        try:
            code = frame.f_code
            filename = code.co_filename

            # Skip internal/system modules
            if '/site-packages/' in filename or '\\site-packages\\' in filename:
                return None
            if '/lib/python' in filename or '\\lib\\python' in filename:
                return None

            if event == 'call':
                self.call_depth += 1
                indent = "  " * self.call_depth
                func_name = code.co_name
                lineno = frame.f_lineno
                self.write_log(f"{indent}→ CALL: {func_name} ({filename}:{lineno})")

                # Log local variables for important functions
                if func_name in ['__init__', 'run', 'on_mount', 'compose', 'connect', 'execute_command']:
                    for var_name, var_value in frame.f_locals.items():
                        if not var_name.startswith('_'):
                            try:
                                val_str = repr(var_value)[:100]
                                self.write_log(f"{indent}  {var_name} = {val_str}")
                            except:
                                pass

            elif event == 'return':
                indent = "  " * self.call_depth
                func_name = code.co_name
                try:
                    ret_str = repr(arg)[:100]
                    self.write_log(f"{indent}← RETURN: {func_name} = {ret_str}")
                except:
                    self.write_log(f"{indent}← RETURN: {func_name}")
                self.call_depth = max(0, self.call_depth - 1)

            elif event == 'exception':
                indent = "  " * self.call_depth
                exc_type, exc_value, exc_tb = arg
                self.write_log(f"{indent}⚠ EXCEPTION: {exc_type.__name__}: {exc_value}")

        except Exception as e:
            pass

        return self.trace_calls

    def excepthook(self, exc_type, exc_value, exc_traceback):
        """Custom exception hook"""
        self.write_log("")
        self.write_log("=" * 100)
        self.write_log(f"UNHANDLED EXCEPTION: {exc_type.__name__}")
        self.write_log("=" * 100)
        self.write_log(f"Message: {exc_value}")
        self.write_log("")
        self.write_log("TRACEBACK:")
        for line in tb.format_exception(exc_type, exc_value, exc_traceback):
            self.write_log(line.rstrip())
        self.write_log("=" * 100)
        self.write_log("")

        # Call original hook
        if self.original_excepthook:
            self.original_excepthook(exc_type, exc_value, exc_traceback)

    def run_traced(self, command, cwd=None):
        """Run command with tracing"""
        self.write_log(f"Executing: {' '.join(command)}")
        self.write_log(f"Working directory: {cwd or os.getcwd()}")
        self.write_log("")
        self.write_log("--- EXECUTION START ---")
        self.write_log("")

        # Create subprocess with logging
        stderr_file = open(self.log_file.replace('.log', '_stderr.log'), 'w', encoding='utf-8')

        try:
            process = subprocess.Popen(
                command,
                stdout=sys.stdout,
                stderr=stderr_file,
                stdin=sys.stdin,
                cwd=cwd,
                env=os.environ.copy()
            )

            return_code = process.wait()

            self.write_log("")
            self.write_log("--- EXECUTION END ---")
            self.write_log(f"Process exited with code: {return_code}")

            # Merge stderr log
            stderr_file.close()
            try:
                with open(stderr_file.name, 'r', encoding='utf-8') as f:
                    stderr_content = f.read()
                    if stderr_content:
                        self.write_log("")
                        self.write_log("=== STDERR OUTPUT ===")
                        for line in stderr_content.split('\n'):
                            if line:
                                self.write_log(line)
                        self.write_log("=== END STDERR ===")
            except:
                pass

            return return_code

        except Exception as e:
            self.write_log(f"[FATAL ERROR] {e}")
            self.write_log(tb.format_exc())
            stderr_file.close()
            return 1

    def stop_logging(self):
        """Finalize logging"""
        try:
            duration = (datetime.now() - self.start_time).total_seconds()
            self.write_log("")
            self.write_log("=" * 100)
            self.write_log(f"Trace finished in {duration:.2f} seconds")
            self.write_log("=" * 100)

            if self.log_handle:
                self.log_handle.close()

            print(f"\n[✓] Detailed trace saved to: {self.log_file}", file=sys.stderr)
            print(f"[✓] Stderr log saved to: {self.log_file.replace('.log', '_stderr.log')}", file=sys.stderr)
            return self.log_file
        except Exception as e:
            print(f"[ERROR] Cannot finalize log: {e}", file=sys.stderr)
            return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Detailed runtime tracer for pyPbCmd")
    parser.add_argument("script", help="Python script to trace")
    parser.add_argument("--log", help="Log file path (default: auto-generated)")
    parser.add_argument("--depth", type=int, default=10, help="Max call stack depth to trace (default: 10)")
    parser.add_argument("args", nargs="*", help="Arguments to pass to script")

    args = parser.parse_args()

    tracer = DetailedTracer(log_file=args.log, max_depth=args.depth)

    if not tracer.start_logging():
        sys.exit(1)

    try:
        command = [sys.executable, args.script] + args.args
        exit_code = tracer.run_traced(command)
        log_path = tracer.stop_logging()

        sys.exit(exit_code)

    except KeyboardInterrupt:
        tracer.write_log("[INTERRUPTED] User interrupted execution")
        log_path = tracer.stop_logging()
        sys.exit(1)
    except Exception as e:
        tracer.write_log(f"[FATAL] Unhandled exception: {e}")
        tracer.write_log(tb.format_exc())
        log_path = tracer.stop_logging()
        sys.exit(2)


if __name__ == "__main__":
    main()
