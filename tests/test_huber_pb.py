from huber.pb import (
    HUBER_CLIENT_SOURCE,
    HUBER_DEFAULT_BAUDRATE,
    HUBER_DEFAULT_TIMEOUT,
    HuberThermostatPB,
    ThermostatConnection,
    compose_command,
    decode_i32,
    encode_i32,
    parse_response,
)
from huber.protocol import create_connection, normalize_protocol


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


def response(addr, value):
    return f"{{S{addr:02X}{encode_i32(value):08X}\r\n".encode("ascii")


def test_pb_command_format_and_signed_values():
    assert compose_command(0x01) == b"{M01********\r\n"
    assert compose_command(0x00, 2250) == b"{M00000008CA\r\n"
    assert compose_command(0x00, -500) == b"{M00FFFFFE0C\r\n"
    assert decode_i32(0xFFFFFE0C) == -500
    assert parse_response(b"{S01FFFFFE0C\r\n", expected_addr=0x01) == -500


def test_pb_client_protocol_commands():
    serial = FakeSerial([
        response(0x01, 2000),
        response(0x01, 2125),
        response(0x00, 2250),
        response(0x00, 2375),
        response(0x14, 1),
        response(0x16, 1),
        response(0x14, 0),
    ])
    thermostat = HuberThermostatPB(serial)

    assert thermostat.ping() is True
    assert thermostat.read_bath_temperature() == 21.25
    assert thermostat.read_setpoint() == 22.5
    assert thermostat.set_setpoint(23.75) is True
    assert thermostat.set_thermoregulation(True) is True
    assert thermostat.set_pump_state(True) is True
    assert thermostat.set_thermoregulation(False) is True
    assert serial.writes == [
        b"{M01********\r\n",
        b"{M01********\r\n",
        b"{M00********\r\n",
        b"{M0000000947\r\n",
        b"{M1400000001\r\n",
        b"{M1600000001\r\n",
        b"{M1400000000\r\n",
    ]


def test_protocol_factory_and_pb_simulation_path():
    assert HUBER_DEFAULT_BAUDRATE == 9600
    assert HUBER_DEFAULT_TIMEOUT == 1.0
    assert HUBER_CLIENT_SOURCE.endswith("pb")
    assert normalize_protocol("legacy-pp") == "pp"
    assert normalize_protocol("pb-hex") == "pb"
    assert create_connection(protocol="pb", port="COM9").__class__ is ThermostatConnection

    conn = ThermostatConnection(port="COM9")
    assert conn.read_setpoint() == 25.0
    assert conn.set_setpoint(18.5) is True
    assert conn.set_pump_state(True) is True
    assert conn.set_thermoregulation(True) is True
