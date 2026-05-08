from workflows.automation.huber.adapter import HuberWorkflowAdapter


class FakeConnection:
    def __init__(self, thermostat=None):
        self.thermostat = thermostat
        self.port = "COM9"
        self.last_error_code = None
        self._temp = 19.5
        self._setpoint = 22.0
        self.thermoregulation_state = None

    def connect(self):
        return True

    def read_temperature(self):
        return self._temp

    def read_setpoint(self):
        return self._setpoint

    def set_setpoint(self, value):
        self._setpoint = value
        return True

    def set_thermoregulation(self, state):
        self.thermoregulation_state = state
        return True

    def close(self):
        self.closed = True


class PumpCapableThermostat:
    def __init__(self):
        self.pump_state = None

    def set_pump_state(self, on_off):
        self.pump_state = on_off
        return True


def test_adapter_simulation_like_path_without_pump_control():
    conn = FakeConnection(thermostat=None)
    adapter = HuberWorkflowAdapter(connection=conn)

    assert adapter.connect() is True
    assert adapter.supports_pump_control is False
    assert adapter.read_bath_temp() == 19.5
    assert adapter.read_setpoint() == 22.0
    assert adapter.set_setpoint(27.5) is True
    assert adapter.read_setpoint() == 27.5
    assert adapter.start_process() is True
    assert conn.thermoregulation_state is True
    assert adapter.stop_process() is True
    assert conn.thermoregulation_state is False
    assert adapter.set_pump_state(True) is False
    assert adapter.safe_standby(20.0, False) is True


def test_adapter_with_pump_capability():
    thermostat = PumpCapableThermostat()
    conn = FakeConnection(thermostat=thermostat)
    adapter = HuberWorkflowAdapter(connection=conn)

    assert adapter.connect() is True
    assert adapter.supports_pump_control is True
    assert adapter.set_pump_state(True) is True
    assert thermostat.pump_state is True
    assert adapter.safe_standby(18.0, False) is True
    assert thermostat.pump_state is False
