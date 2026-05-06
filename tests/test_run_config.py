import json
import tempfile
import unittest
from pathlib import Path

from workflows.automation.common.run_config import RunConfig


class RunConfigTests(unittest.TestCase):
    def test_unified_valid_defaults(self):
        cfg = RunConfig.from_dict(
            {
                "run_name": "demo",
                "steps": [
                    {
                        "name": "step1",
                        "bath_setpoint_c": 32.5,
                        "tec_power_w": 12,
                        "duration_s": 300,
                    }
                ],
            }
        )
        self.assertEqual(cfg.run_name, "demo")
        self.assertEqual(len(cfg.steps), 1)
        self.assertEqual(cfg.steps[0].progression_mode, "time")
        self.assertEqual(cfg.safety.tec_power_w_on_stop, 0.0)

    def test_invalid_progression_mode(self):
        with self.assertRaisesRegex(ValueError, "invalid progression_mode"):
            RunConfig.from_dict(
                {
                    "steps": [
                        {
                            "name": "bad",
                            "bath_setpoint_c": 25,
                            "tec_power_w": 10,
                            "duration_s": 5,
                            "progression_mode": "invalid",
                        }
                    ]
                }
            )

    def test_stability_fields_supported(self):
        cfg = RunConfig.from_dict(
            {
                "steps": [
                    {
                        "name": "stable",
                        "bath_setpoint_c": 20,
                        "tec_power_w": 8,
                        "duration_s": 60,
                        "progression_mode": "stability",
                        "stability_band_c": 0.2,
                        "stability_hold_s": 30,
                        "stability_timeout_s": 600,
                    }
                ]
            }
        )
        step = cfg.steps[0]
        self.assertEqual(step.progression_mode, "stability")
        self.assertEqual(step.stability_band_c, 0.2)

    def test_backward_compat_power_schedule_mapping(self):
        cfg = RunConfig.from_dict(
            {
                "power_schedule": [
                    {"name": "legacy", "power": 4.2, "duration_seconds": 10}
                ]
            }
        )
        step = cfg.steps[0]
        self.assertEqual(step.name, "legacy")
        self.assertEqual(step.tec_power_w, 4.2)
        self.assertEqual(step.duration_s, 10.0)
        self.assertIsNone(step.bath_setpoint_c)
        self.assertEqual(step.progression_mode, "time")

    def test_shared_steps_can_be_tec_only_or_huber_only(self):
        cfg = RunConfig.from_dict(
            {
                "steps": [
                    {"name": "tec", "tec_power_w": 1.5, "duration_s": 10},
                    {"name": "bath", "bath_setpoint_c": 30.0, "duration_s": 20},
                ]
            }
        )
        self.assertEqual(cfg.steps[0].tec_power_w, 1.5)
        self.assertIsNone(cfg.steps[0].bath_setpoint_c)
        self.assertIsNone(cfg.steps[1].tec_power_w)
        self.assertEqual(cfg.steps[1].bath_setpoint_c, 30.0)

    def test_legacy_top_level_steps_map_to_shared_config(self):
        cfg = RunConfig.from_dict(
            {
                "steps": [
                    {
                        "name": "legacy",
                        "power": 0.25,
                        "dwell_seconds": 5,
                        "set_voltage": 1.0,
                        "set_current": 0.2,
                    }
                ]
            }
        )
        step = cfg.steps[0]
        self.assertEqual(step.duration_s, 5.0)
        self.assertEqual(step.tec_power_w, 0.25)
        self.assertEqual(step.tec_voltage_v, 1.0)
        self.assertEqual(step.tec_current_a, 0.2)

    def test_from_json_file(self):
        payload = {
            "steps": [
                {
                    "name": "json",
                    "bath_setpoint_c": 30,
                    "tec_power_w": 1,
                    "duration_s": 2,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cfg = RunConfig.from_json_file(path)
        self.assertEqual(cfg.steps[0].name, "json")


    def test_invalid_duration_rejected(self):
        with self.assertRaisesRegex(ValueError, "duration_s"):
            RunConfig.from_dict(
                {
                    "steps": [
                        {
                            "name": "bad_duration",
                            "bath_setpoint_c": 25,
                            "tec_power_w": 1,
                            "duration_s": 0,
                        }
                    ]
                }
            )

    def test_missing_duration_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing required keys"):
            RunConfig.from_dict({"steps": [{"name": "s1", "tec_power_w": 1}]})

    def test_step_without_any_device_request_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one device setpoint"):
            RunConfig.from_dict({"steps": [{"name": "s1", "duration_s": 10}]})

    def test_legacy_mapping_default_name(self):
        cfg = RunConfig.from_dict({"power_schedule": [{"power": 1.1, "duration_seconds": 7}]})
        self.assertEqual(cfg.steps[0].name, "step_1")

    def test_safety_overrides(self):
        cfg = RunConfig.from_dict(
            {
                "steps": [{"name": "s", "bath_setpoint_c": 25, "tec_power_w": 2, "duration_s": 4}],
                "safety": {
                    "tec_power_w_on_stop": 0.5,
                    "bath_standby_setpoint_c": 22.5,
                    "pump_on_in_safe_state": False,
                },
            }
        )
        self.assertEqual(cfg.safety.tec_power_w_on_stop, 0.5)
        self.assertEqual(cfg.safety.bath_standby_setpoint_c, 22.5)
        self.assertFalse(cfg.safety.pump_on_in_safe_state)


if __name__ == "__main__":
    unittest.main()
