import json
from power_live_log_gui import LiveLoggerGui


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def make_gui(**values):
    gui = LiveLoggerGui.__new__(LiveLoggerGui)
    defaults = {
        "huber_curve_c": "",
        "voltage_curve_v": "0.5,1.0,1.5",
        "current_curve_a": "0.2,0.2,0.25",
        "step_duration_s": "60",
        "bath_standby_temp_c": "25.0",
        "pump_safe_on": 1,
        "duration": "",
    }
    defaults.update(values)
    for name, value in defaults.items():
        setattr(gui, name, FakeVar(value))
    gui.loaded_schedule_points = []
    gui.loaded_temp_schedule_points = []
    gui.loaded_power_schedule = []
    gui.detected_mode = FakeVar("")
    gui.run_mode = FakeVar("")
    gui._redraw_requested_input_plot = lambda: None
    return gui


def test_unified_builder_blank_huber_creates_tec_only_steps_with_derived_power():
    gui = make_gui()

    payload = gui._build_unified_example_payload()

    assert payload["run_name"] == "gui_tec_curve_template"
    assert len(payload["steps"]) == 3
    assert [step.get("bath_setpoint_c") for step in payload["steps"]] == [None, None, None]
    assert [step["tec_voltage_v"] for step in payload["steps"]] == [0.5, 1.0, 1.5]
    assert [step["tec_current_a"] for step in payload["steps"]] == [0.2, 0.2, 0.25]
    assert [step["tec_power_w"] for step in payload["steps"]] == [0.1, 0.2, 0.375]


def test_unified_builder_huber_only_omits_tec_fields():
    gui = make_gui(huber_curve_c="25,30", voltage_curve_v="", current_curve_a="")

    payload = gui._build_unified_example_payload()

    assert payload["run_name"] == "gui_huber_curve_template"
    assert [step["bath_setpoint_c"] for step in payload["steps"]] == [25.0, 30.0]
    assert all("tec_power_w" not in step for step in payload["steps"])
    assert all("tec_voltage_v" not in step for step in payload["steps"])
    assert all("tec_current_a" not in step for step in payload["steps"])


def test_unified_builder_requires_matching_huber_and_tec_point_counts():
    gui = make_gui(huber_curve_c="25,30")

    try:
        gui._build_unified_example_payload()
    except ValueError as exc:
        assert "same number of points" in str(exc)
    else:
        raise AssertionError("expected mismatched curve point counts to fail")


def test_requested_preview_derives_power_when_legacy_zero_power_has_voltage_current(tmp_path):
    config_path = tmp_path / "legacy_zero_power_unified.json"
    config_path.write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "name": "vi_step",
                        "tec_power_w": 0.0,
                        "tec_voltage_v": 2.0,
                        "tec_current_a": 0.5,
                        "duration_s": 10,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    gui = make_gui()

    gui._load_requested_input_from_config(str(config_path))

    assert gui.loaded_schedule_points == [(0.0, 1.0), (10.0, 1.0)]
    assert gui.duration.get() == "10"


class FakeListbox:
    def __init__(self):
        self.items = []
        self.selected = []

    def delete(self, start, end):
        self.items.clear()
        self.selected.clear()

    def insert(self, end, item):
        self.items.append(item)

    def selection_set(self, idx):
        self.selected.append(idx)


def test_ole_to_unix_timestamp_uses_shared_constants():
    assert LiveLoggerGui._ole_to_unix_timestamp(25569.0) == 0.0
    assert LiveLoggerGui._ole_to_unix_timestamp(25570.0) == 86400.0


def test_configure_live_plot_columns_selects_defaults_and_initializes_buffers():
    gui = LiveLoggerGui.__new__(LiveLoggerGui)
    gui.columns_list = FakeListbox()
    gui.selected_cols = []
    gui.live_data = {}

    gui._configure_live_plot_columns(["bath_temp_c", "tec_actual_power_w", "ignored"], ["tec_actual_power_w", "missing"])

    assert gui.columns_list.items == ["bath_temp_c", "tec_actual_power_w", "ignored"]
    assert gui.selected_cols == ["tec_actual_power_w"]
    assert gui.columns_list.selected == [1]
    assert set(gui.live_data) == {"bath_temp_c", "tec_actual_power_w", "ignored"}
