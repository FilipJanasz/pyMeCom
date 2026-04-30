import sys
import types
import unittest
from datetime import datetime, timezone

serial_stub = types.ModuleType('serial')
serial_stub.Serial = object
serial_stub.serialutil = types.SimpleNamespace(SerialException=Exception)
sys.modules.setdefault('serial', serial_stub)

from workflows.automation.common.live_logger import build_time_columns, ole_automation_date


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


if __name__ == '__main__':
    unittest.main()
