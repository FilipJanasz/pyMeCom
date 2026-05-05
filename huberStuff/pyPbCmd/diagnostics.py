# -*- coding: utf-8 -*-
"""
Comprehensive diagnostic tracer for pyPbCmd
Captures all system information that might affect application startup
"""

import sys
import os
import platform
import subprocess
import json
import socket
import locale
import codecs
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import traceback

class Diagnostics:
    def __init__(self):
        self.report = {}
        self.errors = []
        self.warnings = []
        self.timestamp = datetime.now().isoformat()

    def add_section(self, title: str) -> None:
        self.report[title] = {}

    def add_data(self, section: str, key: str, value: Any) -> None:
        if section not in self.report:
            self.add_section(section)
        self.report[section][key] = value

    def add_error(self, section: str, message: str) -> None:
        self.errors.append(f"[{section}] {message}")

    def add_warning(self, section: str, message: str) -> None:
        self.warnings.append(f"[{section}] {message}")

    def run_safe(self, func, section: str, key: str) -> Any:
        """Run function safely and capture errors"""
        try:
            result = func()
            self.add_data(section, key, result)
            return result
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            self.add_error(section, error_msg)
            self.add_data(section, key, f"ERROR: {error_msg}")
            return None

    def diagnose_system(self) -> None:
        """Gather system information"""
        print("[*] Diagnosing system...", flush=True)
        self.add_section("System Information")

        self.run_safe(
            lambda: platform.system(),
            "System Information", "OS"
        )
        self.run_safe(
            lambda: platform.release(),
            "System Information", "OS Version"
        )
        self.run_safe(
            lambda: platform.machine(),
            "System Information", "Architecture"
        )
        self.run_safe(
            lambda: platform.processor(),
            "System Information", "Processor"
        )
        self.run_safe(
            lambda: os.cpu_count(),
            "System Information", "CPU Count"
        )

    def diagnose_python(self) -> None:
        """Gather Python information"""
        print("[*] Diagnosing Python...", flush=True)
        self.add_section("Python Environment")

        self.run_safe(
            lambda: sys.version,
            "Python Environment", "Python Version"
        )
        self.run_safe(
            lambda: sys.executable,
            "Python Environment", "Python Executable"
        )
        self.run_safe(
            lambda: sys.prefix,
            "Python Environment", "Python Prefix"
        )
        self.run_safe(
            lambda: sys.base_prefix,
            "Python Environment", "Python Base Prefix"
        )

        # Check if in venv
        in_venv = (
            hasattr(sys, 'real_prefix') or
            (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
        )
        self.add_data("Python Environment", "In Virtual Environment", in_venv)

        # Python path
        self.add_data("Python Environment", "Python Path Length", len(sys.path))
        self.add_data("Python Environment", "Python Paths", sys.path[:5])  # First 5 paths

    def diagnose_encoding(self) -> None:
        """Check encoding and locale"""
        print("[*] Diagnosing encoding...", flush=True)
        self.add_section("Encoding & Locale")

        self.run_safe(
            lambda: sys.stdout.encoding,
            "Encoding & Locale", "Stdout Encoding"
        )
        self.run_safe(
            lambda: sys.stderr.encoding,
            "Encoding & Locale", "Stderr Encoding"
        )
        self.run_safe(
            lambda: locale.getpreferredencoding(),
            "Encoding & Locale", "Preferred Encoding"
        )
        self.run_safe(
            lambda: locale.getlocale(),
            "Encoding & Locale", "Locale"
        )
        self.run_safe(
            lambda: os.getenv("PYTHONIOENCODING", "NOT SET"),
            "Encoding & Locale", "PYTHONIOENCODING"
        )
        self.run_safe(
            lambda: os.getenv("LANG", "NOT SET"),
            "Encoding & Locale", "LANG Environment"
        )

    def diagnose_network(self) -> None:
        """Check network/connectivity"""
        print("[*] Diagnosing network...", flush=True)
        self.add_section("Network")

        self.run_safe(
            lambda: socket.gethostname(),
            "Network", "Hostname"
        )

        try:
            ip = socket.gethostbyname(socket.gethostname())
            self.add_data("Network", "Local IP", ip)
        except Exception as e:
            self.add_error("Network", f"Cannot resolve hostname: {e}")

    def diagnose_directories(self) -> None:
        """Check project structure and permissions"""
        print("[*] Diagnosing directories...", flush=True)
        self.add_section("Project Structure")

        base_dir = Path(__file__).parent
        self.add_data("Project Structure", "Project Root", str(base_dir))
        self.add_data("Project Structure", "Working Directory", os.getcwd())
        self.add_data("Project Structure", "Script Location", __file__)

        # Check critical files
        critical_files = [
            ("main.py", "Main application"),
            ("requirements.txt", "Dependencies"),
            ("HuberPkg/setup.py", "Package setup"),
            ("HuberPkg/huber_thermostat/__init__.py", "Thermostat module"),
        ]

        file_status = {}
        for filename, description in critical_files:
            filepath = base_dir / filename
            exists = filepath.exists()
            file_status[filename] = {
                "exists": exists,
                "description": description,
                "path": str(filepath),
                "readable": os.access(filepath, os.R_OK) if exists else False,
                "size_bytes": filepath.stat().st_size if exists else None,
            }

        self.add_data("Project Structure", "Files", file_status)

    def diagnose_dependencies(self) -> None:
        """Check if critical packages are installed"""
        print("[*] Diagnosing dependencies...", flush=True)
        self.add_section("Package Dependencies")

        packages_to_check = [
            "textual",
            "huber_thermostat",
            "matplotlib",
            "pyserial",
        ]

        for package in packages_to_check:
            self.run_safe(
                lambda p=package: self._check_package(p),
                "Package Dependencies", package
            )

    def _check_package(self, package_name: str) -> Dict[str, Any]:
        """Check if a package is installed and get version"""
        try:
            module = __import__(package_name)
            version = getattr(module, '__version__', 'unknown')
            location = getattr(module, '__file__', 'unknown')
            return {
                "installed": True,
                "version": version,
                "location": location
            }
        except ImportError:
            return {
                "installed": False,
                "version": None,
                "location": None,
                "error": "Package not installed"
            }

    def diagnose_permissions(self) -> None:
        """Check file permissions and access rights"""
        print("[*] Diagnosing permissions...", flush=True)
        self.add_section("Permissions")

        base_dir = Path(__file__).parent

        # Check project directory permissions
        project_readable = os.access(base_dir, os.R_OK)
        project_writable = os.access(base_dir, os.W_OK)

        self.add_data("Permissions", "Project Dir Readable", project_readable)
        self.add_data("Permissions", "Project Dir Writable", project_writable)

        # Check temp directory
        temp_dir = Path(os.environ.get('TEMP', '/tmp'))
        self.add_data("Permissions", "Temp Dir", str(temp_dir))
        self.add_data("Permissions", "Temp Dir Writable", os.access(temp_dir, os.W_OK))

        # Check home directory
        home_dir = Path.home()
        self.add_data("Permissions", "Home Dir", str(home_dir))
        self.add_data("Permissions", "Home Dir Writable", os.access(home_dir, os.W_OK))

    def diagnose_environment(self) -> None:
        """Check important environment variables"""
        print("[*] Diagnosing environment variables...", flush=True)
        self.add_section("Environment Variables")

        important_vars = [
            "PATH",
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONIOENCODING",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
            "COMSPEC",
            "SHELL",
            "TERM",
            "VIRTUAL_ENV",
        ]

        for var in important_vars:
            value = os.environ.get(var)
            if value:
                # Hide sensitive paths for privacy
                if len(value) > 200:
                    value = value[:200] + "... [truncated]"
                self.add_data("Environment Variables", var, value)
            else:
                self.add_data("Environment Variables", var, "NOT SET")

    def diagnose_powershell(self) -> None:
        """Check PowerShell configuration"""
        print("[*] Diagnosing PowerShell...", flush=True)
        self.add_section("PowerShell Configuration")

        try:
            # Get PowerShell version
            result = subprocess.run(
                ["powershell", "-Command", "$PSVersionTable.PSVersion"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self.add_data("PowerShell Configuration", "PS Version", result.stdout.strip())
            else:
                self.add_error("PowerShell Configuration", "Cannot get PowerShell version")

            # Check execution policy
            result = subprocess.run(
                ["powershell", "-Command", "Get-ExecutionPolicy"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self.add_data("PowerShell Configuration", "Execution Policy", result.stdout.strip())

        except Exception as e:
            self.add_error("PowerShell Configuration", f"Cannot check PowerShell: {e}")

    def diagnose_imports(self) -> None:
        """Try importing main dependencies"""
        print("[*] Diagnosing imports...", flush=True)
        self.add_section("Import Test")

        imports_to_test = [
            "sys",
            "os",
            "asyncio",
            "csv",
            "serial",
            "textual",
            "textual.app",
            "matplotlib",
            "huber_thermostat",
        ]

        for module_name in imports_to_test:
            try:
                __import__(module_name)
                self.add_data("Import Test", module_name, "OK")
            except ImportError as e:
                self.add_warning("Import Test", f"{module_name}: {e}")
                self.add_data("Import Test", module_name, f"FAILED: {e}")
            except Exception as e:
                self.add_error("Import Test", f"{module_name}: {type(e).__name__}: {e}")
                self.add_data("Import Test", module_name, f"ERROR: {e}")

    def generate_report(self) -> str:
        """Generate human-readable report"""
        lines = []
        lines.append("\n" + "=" * 80)
        lines.append("pyPbCmd DIAGNOSTIC REPORT")
        lines.append("=" * 80)
        lines.append(f"Generated: {self.timestamp}")
        lines.append(f"Platform: {platform.system()} {platform.release()}")
        lines.append("=" * 80 + "\n")

        # Main report
        for section, data in self.report.items():
            lines.append(f"\n{'─' * 80}")
            lines.append(f"  {section}")
            lines.append(f"{'─' * 80}")

            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        lines.append(f"  {key}:")
                        lines.append(f"    {json.dumps(value, indent=6, ensure_ascii=False)}")
                    else:
                        lines.append(f"  {key}: {value}")
            else:
                lines.append(f"  {data}")

        # Warnings
        if self.warnings:
            lines.append(f"\n{'─' * 80}")
            lines.append("  WARNINGS")
            lines.append(f"{'─' * 80}")
            for warning in self.warnings:
                lines.append(f"  ⚠ {warning}")

        # Errors
        if self.errors:
            lines.append(f"\n{'─' * 80}")
            lines.append("  ERRORS")
            lines.append(f"{'─' * 80}")
            for error in self.errors:
                lines.append(f"  ✗ {error}")

        lines.append(f"\n{'=' * 80}")
        lines.append("Send this report to the developer for troubleshooting")
        lines.append("=" * 80 + "\n")

        return "\n".join(lines)

    def save_report(self, filename: str = None) -> str:
        """Save report to file"""
        if filename is None:
            filename = f"diagnostic_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

        filepath = Path(filename)
        report_text = self.generate_report()

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report_text)
            return str(filepath)
        except Exception as e:
            print(f"[!] Cannot write to {filepath}: {e}", file=sys.stderr, flush=True)
            # Try writing to temp directory
            temp_file = Path(os.environ.get('TEMP', '/tmp')) / filename
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(report_text)
            return str(temp_file)

    def run_all_diagnostics(self) -> str:
        """Run all diagnostic checks"""
        print("\n" + "=" * 80)
        print("pyPbCmd Diagnostic Tool")
        print("=" * 80 + "\n")

        self.diagnose_system()
        self.diagnose_python()
        self.diagnose_encoding()
        self.diagnose_network()
        self.diagnose_directories()
        self.diagnose_dependencies()
        self.diagnose_permissions()
        self.diagnose_environment()
        self.diagnose_powershell()
        self.diagnose_imports()

        return self.generate_report()


def main():
    """Main entry point"""
    try:
        diagnostics = Diagnostics()
        report = diagnostics.run_all_diagnostics()

        # Print report
        print(report)

        # Save to file
        report_path = diagnostics.save_report()
        print(f"\n[✓] Report saved to: {report_path}")
        print(f"[*] Please send this file to the developer")

        return 0

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[✗] FATAL ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
