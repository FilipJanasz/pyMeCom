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
        "recipe_step_name": "step_1",
        "recipe_duration_s": "60",
        "recipe_bath_temp_c": "",
        "recipe_tec_voltage_v": "",
        "recipe_tec_current_a": "",
        "recipe_tec_power_w": "",
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


class FakePortInfo:
    def __init__(self, device, description="", hwid=""):
        self.device = device
        self.description = description
        self.hwid = hwid


def test_format_serial_port_choices_shows_device_description_and_hwid():
    choices = LiveLoggerGui._format_serial_port_choices(
        [
            FakePortInfo("COM3", "USB Serial Device", "VID:PID=1234:5678"),
            FakePortInfo("COM4"),
        ]
    )

    assert choices == "COM3 — USB Serial Device | VID:PID=1234:5678\nCOM4"


def test_summarize_serial_port_choices_explains_how_to_use_ports():
    summary = LiveLoggerGui._summarize_serial_port_choices(
        [
            FakePortInfo("COM3", "USB Serial Device", "VID:PID=1234:5678"),
            FakePortInfo("COM4", "Bluetooth Serial"),
        ]
    )

    assert summary == (
        "COM scan: found 2 port(s): COM3 (USB Serial Device), COM4 (Bluetooth Serial). "
        "Copy a COM name into the TEC or Huber Port field, then click Detect."
    )



def test_connection_status_text_is_clipped_for_wrapping_labels():
    long_text = "TEC: " + "very long diagnostic detail " * 20
    clipped = LiveLoggerGui._clip_status_text(long_text, max_chars=80)

    assert len(clipped) == 80
    assert clipped.endswith("…")
    assert "\n" not in clipped


def test_connection_color_supports_separate_detect_indicator_states():
    assert LiveLoggerGui._connection_color("green") == "forest green"
    assert LiveLoggerGui._connection_color("red") == "firebrick"
    assert LiveLoggerGui._connection_color("gray") == "gray50"


def test_detect_mode_identifies_huber_only_shared_steps():
    gui = make_gui()

    mode = gui._detect_mode_from_content({"steps": [{"name": "bath", "bath_setpoint_c": 28, "duration_s": 5}]})

    assert mode == "Huber-only"


def test_validate_huber_only_rejects_tec_requests():
    gui = make_gui()

    error = gui._validate_mode_compatibility(
        {"steps": [{"name": "both", "bath_setpoint_c": 28, "tec_power_w": 1, "duration_s": 5}]},
        "Huber-only",
    )

    assert "cannot run steps with TEC" in error


def test_recipe_payload_preserves_huber_only_steps():
    gui = make_gui()
    gui.recipe_points = [{"name": "bath", "duration_s": 30.0, "progression_mode": "time", "bath_setpoint_c": 26.5}]

    payload = gui._build_recipe_payload()

    assert payload["run_name"] == "gui_recipe"
    assert payload["steps"] == gui.recipe_points
    assert payload["safety"]["bath_standby_setpoint_c"] == 25.0


def test_recipe_preview_points_builds_stepwise_tec_and_huber_curves():
    tec_points, bath_points = LiveLoggerGui._recipe_preview_points(
        [
            {"duration_s": 10, "tec_power_w": 1.5},
            {"duration_s": 5, "bath_setpoint_c": 27.0},
        ]
    )

    assert tec_points == [(0.0, 1.5), (10.0, 1.5)]
    assert bath_points == [(10.0, 27.0), (15.0, 27.0)]


def test_parse_numeric_field_raises_friendly_field_label():
    try:
        LiveLoggerGui._parse_numeric_field("abc", "TEC power W")
    except ValueError as exc:
        assert str(exc) == "TEC power W must be a number"
    else:
        raise AssertionError("expected bad numeric input to fail")


def test_recipe_step_from_inputs_derives_power_from_voltage_current():
    gui = make_gui(
        recipe_step_name="vi",
        recipe_duration_s="12",
        recipe_bath_temp_c="28.5",
        recipe_tec_voltage_v="2.0",
        recipe_tec_current_a="0.4",
        recipe_tec_power_w="",
    )
    gui.recipe_points = []

    step = gui._recipe_step_from_inputs()

    assert step == {
        "name": "vi",
        "duration_s": 12.0,
        "progression_mode": "time",
        "bath_setpoint_c": 28.5,
        "tec_voltage_v": 2.0,
        "tec_current_a": 0.4,
        "tec_power_w": 0.8,
    }


def test_recipe_step_from_inputs_requires_voltage_current_pair():
    gui = make_gui(recipe_tec_voltage_v="2.0", recipe_tec_current_a="")
    gui.recipe_points = []

    try:
        gui._recipe_step_from_inputs()
    except ValueError as exc:
        assert "voltage and current" in str(exc)
    else:
        raise AssertionError("expected partial TEC V/I inputs to fail")


class FakeTecSessionManager:
    def __init__(self, session):
        self.session = session
        self.exited = False

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        self.exited = True


class FakeTecLogger:
    def __init__(self, session, endpoint="COM7"):
        self.manager = FakeTecSessionManager(session)
        self.endpoint = endpoint

    def _open_session(self):
        return self.manager, self.endpoint


class FakeIdentifySession:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def identify(self, address):
        self.calls.append(address)
        if self.error is not None:
            raise self.error
        return self.result


def test_probe_tec_controller_keeps_port_when_address_query_fails():
    session = FakeIdentifySession(error=RuntimeError("timeout"))
    logger = FakeTecLogger(session)

    endpoint, detected_address, identify_error = LiveLoggerGui._probe_tec_controller(logger, "1")

    assert endpoint == "COM7"
    assert detected_address is None
    assert identify_error == "timeout"
    assert session.calls == [1]
    assert logger.manager.exited is True


def test_probe_tec_controller_reports_address_when_identify_succeeds():
    session = FakeIdentifySession(result=23)
    logger = FakeTecLogger(session, endpoint="COM8")

    endpoint, detected_address, identify_error = LiveLoggerGui._probe_tec_controller(logger, "2")

    assert endpoint == "COM8"
    assert detected_address == 23
    assert identify_error is None
    assert session.calls == [2]
    assert logger.manager.exited is True
