from huber.legacy_pp import (
    HUBER_CLIENT_SOURCE,
    HUBER_DEFAULT_BAUDRATE,
    HUBER_DEFAULT_TIMEOUT,
    HuberThermostatI,
    ThermostatConnection,
)


class FakeSerial:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []
        self.closed = False

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def read(self, size):
        assert size == 14
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_legacy_pp_client_protocol_commands():
    serial = FakeSerial([
        b"TI +02000\r\n",
        b"TI +02125\r\n",
        b"SP +02250\r\n",
        b"SP +02375\r\n",
        b"CA +00001\r\n",
        b"CA +00000\r\n",
    ])
    thermostat = HuberThermostatI(serial)

    assert thermostat.ping() is True
    assert thermostat.read_bath_temperature() == 21.25
    assert thermostat.read_setpoint() == 22.5
    assert thermostat.set_setpoint(23.75) is True
    assert thermostat.set_thermoregulation(True) is True
    assert thermostat.set_thermoregulation(False) is True
    assert serial.writes == [
        b"TI?\r\n",
        b"TI?\r\n",
        b"SP?\r\n",
        b"SP@+02375\r\n",
        b"CA@+00001\r\n",
        b"CA@+00000\r\n",
    ]


def test_legacy_pp_client_metadata_and_simulation_path():
    assert HUBER_DEFAULT_BAUDRATE == 9600
    assert HUBER_DEFAULT_TIMEOUT == 1.0
    assert HUBER_CLIENT_SOURCE.endswith("legacy_pp")

    conn = ThermostatConnection(port="COM9")
    assert conn.read_setpoint() == 25.0
    assert conn.set_setpoint(18.5) is True
    assert conn.read_setpoint() == 18.5
    assert conn.set_thermoregulation(True) is True
