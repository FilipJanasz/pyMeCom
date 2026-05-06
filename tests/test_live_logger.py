import sys
import types
import unittest
from datetime import datetime, timezone

serial_stub = types.ModuleType('serial')
serial_stub.Serial = object
serial_stub.serialutil = types.SimpleNamespace(SerialException=Exception)
sys.modules.setdefault('serial', serial_stub)

from workflows.automation.common.live_logger import LiveLoggerConfig, build_time_columns, default_live_parameters, looks_like_unified_run_config, ole_automation_date


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


class LiveLoggerLegacyConfigTests(unittest.TestCase):
    def test_old_sine_wave_power_schedule_example_stays_tec_only(self):
        config = LiveLoggerConfig.from_json_file('examples/power_live_log_com.SineWave_example.json')
        self.assertEqual(config.transport, 'com')
        self.assertEqual(len(config.power_schedule), 25)
        self.assertAlmostEqual(config.power_schedule[0].set_voltage, 2.0)
        self.assertFalse(looks_like_unified_run_config({
            'power_schedule': [{'name': 's000', 'duration_seconds': 0.2, 'set_voltage': 2.0}],
        }))

    def test_old_tec_steps_convert_to_live_logger_power_schedule(self):
        config = LiveLoggerConfig.from_json_file('examples/tec1161_calibration_config.example.json')
        self.assertEqual(len(config.power_schedule), 3)
        self.assertEqual(config.power_schedule[0].name, 'zero_baseline')
        self.assertEqual(config.power_schedule[0].duration_seconds, 1800)
        self.assertEqual(config.power_schedule[1].power, 0.25)
        self.assertEqual(config.power_schedule[1].set_voltage, 1.0)
        self.assertEqual(config.power_schedule[1].set_current, 0.25)
        self.assertTrue(config.power_schedule[1].enable_output)

    def test_shared_steps_are_valid_for_tec_only_mode(self):
        from power_live_log_gui import LiveLoggerGui
        unified = {
            'transport': 'com',
            'steps': [
                {
                    'name': 'preheat',
                    'bath_setpoint_c': 30.0,
                    'tec_power_w': 5.0,
                    'duration_s': 300,
                }
            ]
        }
        self.assertTrue(looks_like_unified_run_config(unified))
        gui = LiveLoggerGui.__new__(LiveLoggerGui)
        self.assertIsNone(gui._validate_mode_compatibility(unified, 'TEC-only'))
        config = LiveLoggerConfig.from_dict(unified)
        self.assertEqual(len(config.power_schedule), 1)
        self.assertEqual(config.power_schedule[0].power, 5.0)
        self.assertEqual(config.power_schedule[0].duration_seconds, 300.0)

    def test_huber_only_shared_steps_are_ignored_by_tec_schedule(self):
        huber_only = {'steps': [{'name': 'bath_only', 'bath_setpoint_c': 30.0, 'duration_s': 60}]}
        self.assertTrue(looks_like_unified_run_config(huber_only))
        config = LiveLoggerConfig.from_dict(huber_only)
        self.assertEqual(config.power_schedule, [])

    def test_old_tec_steps_are_valid_for_tec_only_mode(self):
        from power_live_log_gui import LiveLoggerGui
        legacy_steps = {
            'steps': [
                {
                    'name': 'power_50pct',
                    'power': 0.5,
                    'dwell_seconds': 1800,
                    'set_voltage': 2.0,
                    'set_current': 0.5,
                }
            ]
        }
        self.assertFalse(looks_like_unified_run_config(legacy_steps))
        gui = LiveLoggerGui.__new__(LiveLoggerGui)
        self.assertIsNone(gui._validate_mode_compatibility(legacy_steps, 'TEC-only'))


if __name__ == '__main__':
    unittest.main()
