import sys
import types
import unittest
from datetime import datetime, timezone

serial_stub = types.ModuleType('serial')
serial_stub.Serial = object
serial_stub.serialutil = types.SimpleNamespace(SerialException=Exception)
sys.modules.setdefault('serial', serial_stub)

from workflows.automation.common.live_logger import build_time_columns, default_live_parameters, ole_automation_date


class LiveLoggerFormattingTests(unittest.TestCase):
    def test_ole_automation_date_epoch(self):
        dt = datetime(1899, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(ole_automation_date(dt), 0.0)

    def test_time_columns_format(self):
        dt = datetime(2026, 4, 30, 12, 34, 56, 789000, tzinfo=timezone.utc)
        row = build_time_columns(dt)
        self.assertEqual(row['Time'], '12:34:56')
        self.assertEqual(row['Milliseconds'], 789)
        self.assertAlmostEqual(row['OLE Automation Date'], ole_automation_date(dt))

    def test_default_parameters_include_hr_temp_differential_inputs(self):
        labels = [spec.label for spec in default_live_parameters(channel=1)]
        self.assertIn('1048.1: HR Temp Differential Input', labels)
        self.assertIn('1048.2: HR Temp Differential Input', labels)


if __name__ == '__main__':
    unittest.main()
