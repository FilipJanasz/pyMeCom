import sys
import types
import unittest

serial_stub = types.ModuleType('serial')
serial_stub.Serial = object
serial_stub.serialutil = types.SimpleNamespace(SerialException=Exception)
sys.modules.setdefault('serial', serial_stub)

from mecom.calibration import CalibrationConfig, CalibrationStep, SafeChannelController


class DummySession:
    def __init__(self):
        self.calls = []
        self.ser = type('SerialHandle', (), {'is_open': True})()

    def set_parameter(self, **kwargs):
        self.calls.append(("set_parameter", kwargs))

    def set_parameter_raw(self, **kwargs):
        self.calls.append(("set_parameter_raw", kwargs))


class SafeChannelControllerTests(unittest.TestCase):
    def test_missing_output_setpoint_path_keeps_output_disabled(self):
        session = DummySession()
        config = CalibrationConfig(serial_port='COM1')
        controller = SafeChannelController(session, config)

        controller.apply_step(CalibrationStep(name='step', power=1.0, set_voltage=4.0, set_current=1.0, enable_output=True))

        output_enable_calls = [call for call in session.calls if call[1].get('parameter_name') == 'Output Enable Status']
        self.assertTrue(output_enable_calls)
        self.assertEqual(output_enable_calls[-1][1]['value'], config.disable_output_value)
        setpoint_calls = [call for call in session.calls if call[1].get('parameter_name') in {'Set Voltage', 'Set Current'}]
        self.assertEqual(setpoint_calls, [])

    def test_named_voltage_current_fallback_is_opt_in(self):
        session = DummySession()
        config = CalibrationConfig(serial_port='COM1', allow_named_voltage_current_fallback=True)
        controller = SafeChannelController(session, config)

        controller.apply_step(CalibrationStep(name='step', power=1.0, set_voltage=4.0, set_current=1.0, enable_output=True))

        setpoint_calls = [call for call in session.calls if call[1].get('parameter_name') in {'Set Voltage', 'Set Current'}]
        self.assertEqual([call[1]['parameter_name'] for call in setpoint_calls], ['Set Voltage', 'Set Current'])
        output_enable_calls = [call for call in session.calls if call[1].get('parameter_name') == 'Output Enable Status']
        self.assertEqual(output_enable_calls[-1][1]['value'], config.enable_output_value)


if __name__ == '__main__':
    unittest.main()
