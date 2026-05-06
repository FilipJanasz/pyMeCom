import subprocess
import sys
from pathlib import Path

from huberStuff.pyPbCmd import huber_adapter


def test_huber_adapter_uses_bundled_legacy_client_when_package_is_not_installed():
    assert huber_adapter.HUBER_AVAILABLE is True
    assert huber_adapter.HUBER_CLIENT_SOURCE.endswith("huber_thermostat")
    assert huber_adapter.HUBER_DEFAULT_BAUDRATE == 9600
    assert huber_adapter.HUBER_DEFAULT_TIMEOUT == 1.0
    assert hasattr(huber_adapter.HuberThermostatTools, "auto_detect_huber_port")


def test_huber_adapter_imports_from_legacy_project_directory():
    project_dir = Path(__file__).resolve().parents[1] / "huberStuff" / "pyPbCmd"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import huber_adapter; print(huber_adapter.HUBER_AVAILABLE, huber_adapter.HUBER_CLIENT_SOURCE)",
        ],
        cwd=project_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.startswith("True ")
    assert "huber_thermostat" in result.stdout
