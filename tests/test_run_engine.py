import json
from pathlib import Path

from workflows.automation.common.run_config import RunConfig
from workflows.automation.common.run_engine import DualDeviceRunEngine


class FakeTecAdapter:
    supports_legacy_voltage_mode = True

    def __init__(self):
        self.power = 0.0
        self.connected = False
        self.safe_called = False
        self.closed = False
        self.fail_on_set_power = False
        self.legacy_calls = 0
        self.calls = []

    def connect(self):
        self.connected = True
        return True

    def set_power(self, power_w):
        if self.fail_on_set_power:
            raise RuntimeError("set_power failed")
        self.power = power_w
        self.calls.append(("set_power", power_w))

    def set_voltage_current(self, voltage_v, current_a):
        self.calls.append(("set_voltage_current", voltage_v, current_a))

    def apply_legacy_step(self, step):
        self.legacy_calls += 1

    def read_actual_power(self):
        return self.power

    def safe_output(self, power_w):
        self.power = power_w
        self.safe_called = True

    def close(self):
        self.closed = True


class FakeBathAdapter:
    def __init__(self, supports_pump_control=True):
        self.supports_pump_control = supports_pump_control
        self.setpoint = 25.0
        self.temp = 24.8
        self.closed = False
        self.pump_state = None
        self.process_started = False

    def connect(self):
        return True

    def set_setpoint(self, setpoint_c):
        self.setpoint = setpoint_c
        return True

    def start_process(self):
        self.process_started = True
        return True

    def read_bath_temp(self):
        return self.temp

    def read_setpoint(self):
        return self.setpoint

    def set_pump_state(self, on_off):
        self.pump_state = on_off
        return True

    def close(self):
        self.closed = True


def test_normal_progression(tmp_path: Path):
    cfg = RunConfig.from_dict({"run_name": "ok", "steps": [{"name": "s1", "bath_setpoint_c": 22, "tec_power_w": 1.2, "duration_s": 0.05}]})
    engine = DualDeviceRunEngine(FakeTecAdapter(), FakeBathAdapter(), tmp_path, sample_hz=30)
    paths = engine.run(cfg)

    assert engine.state.value == "COMPLETED"
    assert paths.csv_path.exists()
    metadata = json.loads(paths.metadata_path.read_text())
    assert metadata["engine_state"] == "COMPLETED"


def test_huber_setpoint_starts_process(tmp_path: Path):
    cfg = RunConfig.from_dict({"steps": [{"name": "bath", "bath_setpoint_c": 22, "duration_s": 0.05}]})
    bath = FakeBathAdapter()
    engine = DualDeviceRunEngine(FakeTecAdapter(), bath, tmp_path, sample_hz=30)

    engine.run(cfg)

    assert bath.process_started is True


def test_stop_mid_run_transitions_to_completed(tmp_path: Path):
    cfg = RunConfig.from_dict({"steps": [{"name": "s1", "bath_setpoint_c": 20, "tec_power_w": 2, "duration_s": 0.4}]})
    tec = FakeTecAdapter()
    bath = FakeBathAdapter()
    engine = DualDeviceRunEngine(tec, bath, tmp_path, sample_hz=30)
    calls = {"n": 0}

    def row_cb(_):
        calls["n"] += 1
        if calls["n"] == 1:
            engine.request_stop()

    engine.run(cfg, row_callback=row_cb)
    assert engine.state.value == "COMPLETED"
    assert tec.safe_called is True


def test_adapter_failure_goes_error_and_safety(tmp_path: Path):
    cfg = RunConfig.from_dict({"steps": [{"name": "s1", "bath_setpoint_c": 20, "tec_power_w": 2, "duration_s": 0.1}]})
    tec = FakeTecAdapter()
    tec.fail_on_set_power = True
    engine = DualDeviceRunEngine(tec, FakeBathAdapter(), tmp_path, sample_hz=30)
    paths = engine.run(cfg)

    assert engine.state.value == "ERROR"
    assert tec.safe_called is True
    metadata = json.loads(paths.metadata_path.read_text())
    assert "error" in metadata


def test_pump_capability_fallback_logged(tmp_path: Path):
    cfg = RunConfig.from_dict({"steps": [{"name": "s1", "bath_setpoint_c": 20, "tec_power_w": 2, "duration_s": 0.05}]})
    engine = DualDeviceRunEngine(FakeTecAdapter(), FakeBathAdapter(supports_pump_control=False), tmp_path, sample_hz=30)
    paths = engine.run(cfg)
    metadata = json.loads(paths.metadata_path.read_text())
    assert any(a.get("reason") == "unsupported" for a in metadata["safety_actions"])


def test_legacy_zero_power_strict_blocks(tmp_path: Path):
    cfg = RunConfig.from_dict({"power_schedule": [{"name": "legacy", "power": 0.0, "set_voltage": 3.0, "duration_seconds": 1}]})
    engine = DualDeviceRunEngine(FakeTecAdapter(), FakeBathAdapter(), tmp_path)
    paths = engine.run(cfg, input_origin="legacy_power_schedule", legacy_power_policy="strict")
    metadata = json.loads(paths.metadata_path.read_text())
    assert engine.state.value == "ERROR"
    assert metadata["legacy_interpretation"]["warnings"]


def test_legacy_zero_power_allow_continue(tmp_path: Path):
    cfg = RunConfig.from_dict({"power_schedule": [{"name": "legacy", "power": 0.0, "set_current": 0.5, "duration_seconds": 0.05}]})
    engine = DualDeviceRunEngine(FakeTecAdapter(), FakeBathAdapter(), tmp_path, sample_hz=30)
    paths = engine.run(cfg, input_origin="legacy_power_schedule", legacy_power_policy="allow_zero_power")
    metadata = json.loads(paths.metadata_path.read_text())
    assert engine.state.value == "COMPLETED"
    assert metadata["legacy_interpretation"]["warnings"]


def test_legacy_voltage_mode_executes_compatibility_path(tmp_path: Path):
    cfg = RunConfig.from_dict({"power_schedule": [{"name": "legacy", "power": 0.0, "set_current": 0.5, "duration_seconds": 0.05}]})
    tec = FakeTecAdapter()
    engine = DualDeviceRunEngine(tec, FakeBathAdapter(), tmp_path, sample_hz=30)
    engine.run(cfg, input_origin="legacy_power_schedule", legacy_power_policy="legacy_voltage_mode")
    assert tec.legacy_calls >= 1


def test_unified_zero_power_clears_voltage_current_then_disables_output(tmp_path: Path):
    cfg = RunConfig.from_dict(
        {"steps": [{"name": "zero", "bath_setpoint_c": 25.0, "tec_power_w": 0.0, "duration_s": 0.05}]}
    )
    tec = FakeTecAdapter()
    engine = DualDeviceRunEngine(tec, FakeBathAdapter(), tmp_path, sample_hz=30)
    engine.run(cfg)

    assert ("set_voltage_current", 0.0, 0.0) in tec.calls
    assert ("set_power", 0.0) in tec.calls
    assert tec.calls.index(("set_voltage_current", 0.0, 0.0)) < tec.calls.index(("set_power", 0.0))
