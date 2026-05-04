import sys
import types
import unittest
from datetime import datetime, timezone

serial_stub = types.ModuleType('serial')
serial_stub.Serial = object
serial_stub.serialutil = types.SimpleNamespace(SerialException=Exception)
sys.modules.setdefault('serial', serial_stub)

from workflows.automation.common.live_logger import LiveLoggerConfig, build_time_columns, default_live_parameters, ole_automation_date


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

    def test_default_parameters_omit_error_number_and_lr2_temp(self):
        labels = [spec.label for spec in default_live_parameters(channel=1)]
        self.assertNotIn('105.1: Error Number', labels)
        self.assertNotIn('1044.2: LR2 Temp', labels)

    def test_live_logger_config_defaults_and_parses_csv_flush_rows(self):
        self.assertEqual(LiveLoggerConfig().csv_flush_every_rows, 1)
        config = LiveLoggerConfig.from_dict({"csv_flush_every_rows": 25})
        self.assertEqual(config.csv_flush_every_rows, 25)


if __name__ == '__main__':
    unittest.main()
