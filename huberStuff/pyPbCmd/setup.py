#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pyPbCmd Setup and Launcher
All-in-one setup, diagnostics, and launcher
"""

import sys
import os
import subprocess
import json
import platform
import venv
import argparse
from pathlib import Path
from datetime import datetime

class Setup:
    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.venv_path = self.project_root / "venv"
        self.python_exe = sys.executable

    def print_header(self, text):
        print(f"\n{'='*80}")
        print(f"  {text}")
        print(f"{'='*80}\n")

    def print_ok(self, text):
        print(f"[✓] {text}")

    def print_error(self, text):
        print(f"[✗] {text}")

    def print_info(self, text):
        print(f"[*] {text}")

    def print_warn(self, text):
        print(f"[!] {text}")

    def check_python(self):
        """Check Python availability"""
        self.print_info(f"Python: {sys.version}")
        self.print_ok(f"Python executable: {sys.executable}")
        return True

    def create_venv(self):
        """Create virtual environment"""
        self.print_header("Virtual Environment Setup")

        if self.venv_path.exists():
            self.print_warn(f"Virtual environment already exists")
            response = input("Recreate? (y/n): ").strip().lower()
            if response == 'y':
                self.print_info("Removing old venv...")
                import shutil
                shutil.rmtree(self.venv_path)
            else:
                self.print_ok("Using existing virtual environment")
                return True

        self.print_info(f"Creating venv at {self.venv_path}...")
        try:
            venv.create(self.venv_path, with_pip=True)
            self.print_ok("Virtual environment created")
            return True
        except Exception as e:
            self.print_error(f"Failed to create venv: {e}")
            return False

    def get_pip_exe(self):
        """Get pip executable path"""
        if platform.system() == "Windows":
            pip_path = self.venv_path / "Scripts" / "pip.exe"
        else:
            pip_path = self.venv_path / "bin" / "pip"

        # Fallback to global pip if venv pip doesn't exist
        if not pip_path.exists():
            return "pip"
        return str(pip_path)

    def get_python_exe(self):
        """Get python executable path"""
        if platform.system() == "Windows":
            python_path = self.venv_path / "Scripts" / "python.exe"
        else:
            python_path = self.venv_path / "bin" / "python"

        # Fallback to global python if venv python doesn't exist
        if not python_path.exists():
            return sys.executable
        return str(python_path)

    def install_dependencies(self):
        """Install project dependencies"""
        self.print_header("Installing Dependencies")

        pip_exe = self.get_pip_exe()

        # Upgrade pip
        self.print_info("Upgrading pip...")
        subprocess.run([pip_exe, "install", "--upgrade", "pip"],
                      capture_output=True)

        # Install requirements
        req_file = self.project_root / "requirements.txt"
        if req_file.exists():
            self.print_info("Installing from requirements.txt...")
            result = subprocess.run(
                [pip_exe, "install", "-r", str(req_file)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.print_ok("Dependencies installed")
            else:
                self.print_error(f"Failed to install dependencies: {result.stderr}")
                return False
        else:
            self.print_warn("requirements.txt not found")

        # Install HuberPkg
        huber_setup = self.project_root / "HuberPkg" / "setup.py"
        if huber_setup.exists():
            self.print_info("Installing HuberPkg...")
            result = subprocess.run(
                [pip_exe, "install", "-e", str(self.project_root / "HuberPkg")],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.print_ok("HuberPkg installed")
            else:
                self.print_warn("HuberPkg installation failed - will run in simulation mode")

        return True

    def run_diagnostics(self):
        """Run diagnostics"""
        self.print_header("System Diagnostics")

        python_exe = self.get_python_exe()
        diag_script = self.project_root / "diagnostics.py"

        if not diag_script.exists():
            self.print_warn("diagnostics.py not found")
            return True

        self.print_info("Collecting system information...")
        result = subprocess.run([python_exe, str(diag_script)])
        return result.returncode == 0

    def run_app(self, with_trace=True, new_window=False):
        """Run main application"""
        self.print_header("Starting Application")

        python_exe = self.get_python_exe()
        main_script = self.project_root / "main.py"

        if not main_script.exists():
            self.print_error("main.py not found")
            return False

        self.print_info("Launching pyPbCmd...")

        if with_trace:
            tracer_script = self.project_root / "tracer.py"
            if tracer_script.exists():
                self.print_info("Running with output tracing...")
                if new_window and platform.system() == "Windows":
                    subprocess.Popen(["start", "cmd", "/k", f"{python_exe} {tracer_script} {main_script}"], shell=True)
                    return True
                result = subprocess.run([python_exe, str(tracer_script), str(main_script)])
                return result.returncode == 0

        if new_window and platform.system() == "Windows":
            subprocess.Popen(["start", "cmd", "/k", f"{python_exe} {main_script}"], shell=True)
            return True

        result = subprocess.run([python_exe, str(main_script)])
        return result.returncode == 0

    def setup(self):
        """Run full setup"""
        self.print_header("pyPbCmd Setup")

        self.check_python()

        if not self.create_venv():
            return False

        if not self.install_dependencies():
            return False

        self.print_header("Setup Complete")
        self.print_ok("All components ready!")
        print(f"\nTo run the application: python setup.py run")
        print(f"To run diagnostics only: python setup.py diag")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="pyPbCmd Setup and Launcher",
        epilog="Examples:\n  python setup.py              # Run setup\n  python setup.py run          # Run app with diagnostics and tracing\n  python setup.py run --no-trace  # Run without output tracing\n  python setup.py diag         # Run diagnostics only",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "command",
        nargs="?",
        default="setup",
        choices=["setup", "run", "diag"],
        help="Command to execute (default: setup)"
    )

    parser.add_argument(
        "--skip-diag",
        action="store_true",
        help="Skip diagnostics when running app"
    )

    parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Disable output tracing when running app"
    )

    parser.add_argument(
        "--new-window",
        action="store_true",
        help="Run app in new console window"
    )

    args = parser.parse_args()

    setup = Setup()

    try:
        if args.command == "setup":
            success = setup.setup()
            return 0 if success else 1

        elif args.command == "run":
            if not args.skip_diag:
                setup.run_diagnostics()
                input("\nPress Enter to start application...")
            setup.run_app(with_trace=not args.no_trace, new_window=args.new_window)
            return 0

        elif args.command == "diag":
            setup.run_diagnostics()
            return 0

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n[✗] Error: {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
