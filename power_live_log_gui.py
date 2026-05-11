from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Button, Canvas, Checkbutton, Entry, Frame, IntVar, Label, Listbox, Radiobutton, Scrollbar, StringVar, Tk, filedialog, messagebox
from tkinter.ttk import Combobox, Notebook

from serial.tools import list_ports

from huberStuff.pyPbCmd.huber_adapter import HUBER_AVAILABLE as HUBER_HARDWARE_CLIENT_AVAILABLE

from workflows.automation.common.live_logger import CalibrationStep, LiveLogger, LiveLoggerConfig, PowerScheduleStep, SafeChannelController, default_live_parameters, legacy_tec_steps_to_power_schedule, looks_like_unified_run_config
from workflows.automation.common.run_config import RunConfig
from workflows.automation.common.run_engine import DualDeviceRunEngine, LegacyPowerPolicy
from workflows.automation.common.tec_adapter import TecPowerAdapter
from workflows.automation.huber.adapter import HuberWorkflowAdapter

try:
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except Exception:
    mdates = None
    FigureCanvasTkAgg = None
    Figure = None

LAST_CONFIG_PATH = Path('.last_live_logger_gui_config')
MAX_POINTS = 600
MIN_HZ = 0.1
OLE_AUTOMATION_UNIX_EPOCH_OFFSET_DAYS = 25569.0
SECONDS_PER_DAY = 86400.0
UNIFIED_LIVE_COLUMNS = [
    'bath_setpoint_c',
    'bath_temp_c',
    'bath_current_setpoint_c',
    'tec_power_w',
    'tec_actual_power_w',
    'tec_voltage_v',
    'tec_current_a',
    'tec_hr_1_differential_voltage_v',
    'tec_hr_2_differential_voltage_v',
]
UNIFIED_DEFAULT_COLUMNS = ['bath_temp_c', 'tec_actual_power_w', 'bath_setpoint_c', 'tec_power_w']
CONNECTION_STATUS_WRAP_PX = 260
CONNECTION_STATUS_MAX_CHARS = 72
CONNECTION_STATUS_LABEL_CHARS = 44
COM_PORT_CHOICE_WIDTH_CHARS = 72
WINDOW_SCREEN_MARGIN_PX = 80
WINDOW_MIN_WIDTH_PX = 900
WINDOW_MIN_HEIGHT_PX = 560
WINDOW_SMALL_SCREEN_MARGIN_PX = 24
TEC_ADDRESS_SCAN_LIMIT = 16
FORM_PATH_WIDTH_CHARS = 72
FORM_FIELD_WIDTH_CHARS = 48
PREVIEW_PLOT_HEIGHT_IN = 3.0
RECIPE_LIST_WIDTH_CHARS = 72
RECIPE_PREVIEW_PLOT_HEIGHT_IN = 3.0
BUTTON_ROW_PAD_X = 8


class NoopTecAdapter:
    supports_legacy_voltage_mode = False

    def connect(self) -> bool:
        return True

    def set_power(self, power_w: float) -> None:
        return None

    def set_voltage_current(self, voltage_v: float, current_a: float) -> None:
        return None

    def read_actual_power(self):
        return None

    def read_differential_voltage(self, instance: int):
        return None

    def safe_output(self, power_w: float = 0.0) -> None:
        return None

    def close(self) -> None:
        return None


class NoopBathAdapter:
    supports_pump_control = True

    def connect(self) -> bool:
        return True

    def read_bath_temp(self):
        return None

    def read_setpoint(self):
        return None

    def set_setpoint(self, temp_c: float) -> bool:
        return True

    def start_process(self) -> bool:
        return True

    def stop_process(self) -> bool:
        return True

    def set_pump_state(self, on_off: bool) -> bool:
        return True

    def close(self) -> None:
        return None


class LiveLoggerGui:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title('Live Logger GUI (TEC + Unified)')

        self.config_path = StringVar(value='')
        self.serial_port = StringVar(value='')
        self.serial_autodetect = IntVar(value=1)
        self.serial_hint = StringVar(value='')
        self.address = StringVar(value='1')
        self.channel = StringVar(value='1')
        self.hz = StringVar(value='10.0')
        self.duration = StringVar(value='')
        self.output_directory = StringVar(value='live_logs')
        self.output_prefix = StringVar(value='power_live_log_com')
        self.huber_port = StringVar(value='')
        self.bath_standby_temp_c = StringVar(value='25.0')
        self.pump_safe_on = IntVar(value=1)
        self.run_mode = StringVar(value='TEC-only')
        self.run_mode_selection = StringVar(value='Auto')
        self.detected_mode = StringVar(value='TEC-only')
        self.huber_curve_c = StringVar(value='')
        self.voltage_curve_v = StringVar(value='0.5,1.0,1.5,1.0,0.5')
        self.current_curve_a = StringVar(value='0.2,0.2,0.25,0.2,0.2')
        self.step_duration_s = StringVar(value='60')
        self.show_requested_line = IntVar(value=1)
        self.show_live_line = IntVar(value=1)
        self.enable_second_plot = IntVar(value=0)
        self.manual_tec_voltage_v = StringVar(value='0.0')
        self.manual_tec_current_a = StringVar(value='0.0')
        self.manual_huber_temp_c = StringVar(value='25.0')
        self.manual_pump_on = IntVar(value=1)
        self.manual_command_status = StringVar(value='Manual commands: idle')
        self.recipe_step_name = StringVar(value='step_1')
        self.recipe_duration_s = StringVar(value='60')
        self.recipe_bath_temp_c = StringVar(value='')
        self.recipe_tec_voltage_v = StringVar(value='')
        self.recipe_tec_current_a = StringVar(value='')
        self.recipe_tec_power_w = StringVar(value='')

        self.last_output_csv: Path | None = None
        self.run_thread: threading.Thread | None = None
        self.live_data: dict[str, deque[float]] = {}
        self.sample_index = deque(maxlen=MAX_POINTS)
        self.selected_cols: list[str] = []
        self.second_plot_cols: list[str] = []
        self.loaded_schedule_points: list[tuple[float, float]] = []
        self.loaded_temp_schedule_points: list[tuple[float, float]] = []
        self.loaded_power_schedule = []
        self.recipe_points: list[dict[str, object]] = []
        self.animating = False
        self.stop_requested = False
        self.unified_engine: DualDeviceRunEngine | None = None
        self.tec_connection_text = StringVar(value='TEC: not checked')
        self.tec_connection_indicator_text = StringVar(value='●')
        self.huber_connection_text = StringVar(value='Huber: not checked')
        self.huber_connection_indicator_text = StringVar(value='●')
        self.available_ports_text = StringVar(value='Serial tools: click Scan COM Ports, choose a port from the list, then apply it.')
        self.selected_serial_port_choice = StringVar(value='')
        self.serial_port_choices: dict[str, str] = {}
        self.last_tec_connection_detail = 'TEC: not checked'
        self.last_huber_connection_detail = 'Huber: not checked'
        self.huber_detect_thread: threading.Thread | None = None
        self.sample_rate_text = StringVar(value='Measured acquisition rate: n/a')
        self.run_recipe_summary_text = StringVar(value='Recipe to run: no JSON loaded')
        self.run_progress_text = StringVar(value='Progress: idle')
        self.run_eta_text = StringVar(value='Done at: n/a')
        self.loaded_run_total_seconds = 0.0
        self._run_started_at_epoch: float | None = None
        self._current_run_duration_s: float | None = None
        self._progress_update_job = None
        self._last_sample_ts: float | None = None

        self._build_ui()
        self._load_last_used_config_if_present()

    def _build_ui(self) -> None:
        self.scroll_canvas = Canvas(self.root, highlightthickness=0)
        self.scrollbar = Scrollbar(self.root, orient=VERTICAL, command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side=RIGHT, fill='y')
        self.scroll_canvas.pack(side=LEFT, fill=BOTH, expand=True)

        self.content_frame = Frame(self.scroll_canvas)
        self.content_window = self.scroll_canvas.create_window((0, 0), window=self.content_frame, anchor='nw')
        self.content_frame.bind('<Configure>', self._update_scroll_region)
        self.scroll_canvas.bind('<Configure>', self._resize_scroll_window)
        self.root.bind_all('<MouseWheel>', self._on_mousewheel)
        self.root.bind_all('<Button-4>', self._on_mousewheel)
        self.root.bind_all('<Button-5>', self._on_mousewheel)

        self.notebook = Notebook(self.content_frame)
        self.notebook.pack(fill=BOTH, expand=True, padx=8, pady=8)
        self.run_tab = Frame(self.notebook)
        self.example_loader_tab = Frame(self.notebook)
        self.example_editor_tab = Frame(self.notebook)
        self.manual_tab = Frame(self.notebook)
        self.notebook.add(self.run_tab, text='Run Setup')
        self.notebook.add(self.example_loader_tab, text='Example Loader')
        self.notebook.add(self.example_editor_tab, text='Example Editor')
        self.notebook.add(self.manual_tab, text='Manual Commands')

        top = Frame(self.run_tab, padx=8, pady=8)
        top.pack(fill=BOTH, padx=4, pady=(4, 0))
        top.grid_columnconfigure(0, weight=3, uniform='run_setup_top')
        top.grid_columnconfigure(1, weight=2, uniform='run_setup_top')
        top.grid_rowconfigure(0, weight=1)

        def grid_labeled_entry(
            parent: Frame,
            label: str,
            var,
            row: int,
            width: int = FORM_FIELD_WIDTH_CHARS,
            column: int = 1,
            columnspan: int = 1,
            stretch: bool = False,
        ) -> Entry:
            Label(parent, text=label).grid(row=row, column=0, sticky='w')
            entry = Entry(parent, textvariable=var, width=width)
            entry.grid(row=row, column=column, columnspan=columnspan, sticky='we' if stretch else 'w')
            return entry

        def add_row(parent: Frame, label: str, var, row: int, width: int = 42):
            grid_labeled_entry(parent, label, var, row, width=width, stretch=True)

        def grid_button_row(parent: Frame, row: int, column: int, columnspan: int, buttons: list[tuple[str, object]]) -> Frame:
            button_frame = Frame(parent)
            button_frame.grid(row=row, column=column, columnspan=columnspan, sticky='w')
            for index, (text, command) in enumerate(buttons):
                padx = (0, BUTTON_ROW_PAD_X) if index < len(buttons) - 1 else 0
                Button(button_frame, text=text, command=command).pack(side=LEFT, padx=padx)
            return button_frame

        def add_status_label(parent: Frame, var, row: int, column: int, columnspan: int = 1):
            Label(
                parent,
                textvariable=var,
                justify=LEFT,
                anchor='w',
                width=CONNECTION_STATUS_LABEL_CHARS,
                wraplength=CONNECTION_STATUS_WRAP_PX,
            ).grid(row=row, column=column, columnspan=columnspan, sticky='we')

        conn_frame = Frame(top, padx=4, pady=4, relief='groove', bd=1)
        conn_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        runtime_frame = Frame(top, padx=4, pady=4, relief='groove', bd=1)
        runtime_frame.grid(row=0, column=1, sticky='nsew', padx=(4, 0))
        io_frame = Frame(self.example_loader_tab, padx=8, pady=8)
        io_frame.pack(fill=BOTH, expand=True)

        Label(conn_frame, text='Connection Detection', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w')
        Label(runtime_frame, text='Runtime Options', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w')
        Label(io_frame, text='Config & Output', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=5, sticky='w')

        tec_detect_frame = Frame(conn_frame, padx=4, pady=4)
        tec_detect_frame.grid(row=1, column=0, sticky='nsew', padx=(0, 4))
        huber_detect_frame = Frame(conn_frame, padx=4, pady=4)
        huber_detect_frame.grid(row=1, column=1, sticky='nsew', padx=(4, 0))
        conn_frame.grid_columnconfigure(0, weight=1)
        conn_frame.grid_columnconfigure(1, weight=1)
        tec_detect_frame.grid_columnconfigure(1, weight=1)
        huber_detect_frame.grid_columnconfigure(1, weight=1)

        Label(tec_detect_frame, text='TEC connection', font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        self.tec_connection_indicator_label = Label(tec_detect_frame, textvariable=self.tec_connection_indicator_text, fg='gray50', font=('TkDefaultFont', 12, 'bold'))
        self.tec_connection_indicator_label.grid(row=1, column=0, sticky='w')
        add_status_label(tec_detect_frame, self.tec_connection_text, row=1, column=1, columnspan=2)
        Label(tec_detect_frame, text='Port').grid(row=2, column=0, sticky='w')
        Entry(tec_detect_frame, textvariable=self.serial_port, width=24).grid(row=2, column=1, sticky='we')
        Checkbutton(tec_detect_frame, text='Autodetect if blank', variable=self.serial_autodetect).grid(row=2, column=2, sticky='w')
        Label(tec_detect_frame, text='Hint').grid(row=3, column=0, sticky='w')
        Entry(tec_detect_frame, textvariable=self.serial_hint, width=24).grid(row=3, column=1, sticky='we')
        Label(tec_detect_frame, text='Address').grid(row=4, column=0, sticky='w')
        Entry(tec_detect_frame, textvariable=self.address, width=8).grid(row=4, column=1, sticky='w')
        self.detect_tec_button = Button(tec_detect_frame, text='Detect TEC', command=self.detect_controller)
        self.detect_tec_button.grid(row=5, column=1, sticky='w')
        Button(tec_detect_frame, text='Details', command=self.show_tec_connection_details).grid(row=5, column=2, sticky='w', padx=(4, 0))

        Label(huber_detect_frame, text='Huber connection', font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        self.huber_connection_indicator_label = Label(huber_detect_frame, textvariable=self.huber_connection_indicator_text, fg='gray50', font=('TkDefaultFont', 12, 'bold'))
        self.huber_connection_indicator_label.grid(row=1, column=0, sticky='w')
        add_status_label(huber_detect_frame, self.huber_connection_text, row=1, column=1, columnspan=2)
        Label(huber_detect_frame, text='Port').grid(row=2, column=0, sticky='w')
        Entry(huber_detect_frame, textvariable=self.huber_port, width=24).grid(row=2, column=1, sticky='we')
        self.detect_huber_button = Button(huber_detect_frame, text='Detect Huber', command=self.detect_huber)
        self.detect_huber_button.grid(row=3, column=1, sticky='w')
        Button(huber_detect_frame, text='Details', command=self.show_huber_connection_details).grid(row=3, column=2, sticky='w', padx=(4, 0))
        serial_tools_frame = Frame(conn_frame)
        serial_tools_frame.grid(row=2, column=0, columnspan=2, sticky='we', pady=(4, 0))
        serial_tools_frame.grid_columnconfigure(1, weight=1)
        Button(serial_tools_frame, text='Scan COM Ports', command=self.scan_serial_ports).grid(row=0, column=0, sticky='w')
        self.serial_ports_combobox = Combobox(
            serial_tools_frame,
            textvariable=self.selected_serial_port_choice,
            state='readonly',
            width=COM_PORT_CHOICE_WIDTH_CHARS,
            values=(),
        )
        self.serial_ports_combobox.grid(row=0, column=1, sticky='we', padx=(6, 0))
        Button(serial_tools_frame, text='Use for TEC', command=lambda: self.apply_selected_serial_port('tec')).grid(row=0, column=2, sticky='w', padx=(6, 0))
        Button(serial_tools_frame, text='Use for Huber', command=lambda: self.apply_selected_serial_port('huber')).grid(row=0, column=3, sticky='w', padx=(4, 0))
        Label(serial_tools_frame, textvariable=self.available_ports_text, justify=LEFT, anchor='w').grid(row=1, column=0, columnspan=4, sticky='w', pady=(2, 0))

        Label(runtime_frame, textvariable=self.sample_rate_text).grid(row=1, column=0, columnspan=4, sticky='w')
        Label(runtime_frame, text='Run mode').grid(row=2, column=0, sticky='w')
        Radiobutton(runtime_frame, text='Auto', variable=self.run_mode_selection, value='Auto').grid(row=2, column=1, sticky='w')
        Radiobutton(runtime_frame, text='TEC-only', variable=self.run_mode_selection, value='TEC-only').grid(row=2, column=2, sticky='w')
        Radiobutton(runtime_frame, text='Unified', variable=self.run_mode_selection, value='Unified').grid(row=2, column=3, sticky='w')
        Radiobutton(runtime_frame, text='Huber-only', variable=self.run_mode_selection, value='Huber-only').grid(row=2, column=4, sticky='w')
        Label(runtime_frame, text='Detected from JSON').grid(row=3, column=0, sticky='w')
        Label(runtime_frame, textvariable=self.detected_mode, font=('TkDefaultFont', 9, 'bold')).grid(row=3, column=1, sticky='w')
        add_row(runtime_frame, 'Channel', self.channel, 4, width=16)
        add_row(runtime_frame, f'Hz (min {MIN_HZ:g})', self.hz, 5, width=16)
        add_row(runtime_frame, 'Duration Seconds (blank=run forever)', self.duration, 6, width=16)
        Label(runtime_frame, text='Bath Standby °C').grid(row=7, column=0, sticky='w')
        Entry(runtime_frame, textvariable=self.bath_standby_temp_c, width=16).grid(row=7, column=1, sticky='w')
        Checkbutton(runtime_frame, text='Pump ON in safe state', variable=self.pump_safe_on).grid(row=8, column=1, columnspan=2, sticky='w')
        Label(runtime_frame, text='(stop/error: keep bath pump running)').grid(row=9, column=1, columnspan=3, sticky='w')

        run_progress_frame = Frame(self.run_tab, padx=8, pady=4, relief='groove', bd=1)
        run_progress_frame.pack(fill=BOTH, padx=12, pady=(4, 0))
        run_progress_frame.grid_columnconfigure(0, weight=1)
        run_progress_frame.grid_columnconfigure(1, weight=0)
        Label(run_progress_frame, text='Recipe preview for next run', font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, sticky='w')
        Label(run_progress_frame, textvariable=self.run_recipe_summary_text, justify=LEFT, anchor='w').grid(row=1, column=0, sticky='we')
        Label(run_progress_frame, textvariable=self.run_progress_text, justify=LEFT, anchor='w').grid(row=2, column=0, sticky='we')
        Label(run_progress_frame, textvariable=self.run_eta_text, justify=LEFT, anchor='w').grid(row=3, column=0, sticky='we')
        self.run_preview_canvas = Canvas(run_progress_frame, width=320, height=78, bg='white', highlightthickness=1, highlightbackground='gray70')
        self.run_preview_canvas.grid(row=0, column=1, rowspan=4, sticky='e', padx=(8, 0))
        self._redraw_run_preview()

        grid_labeled_entry(io_frame, 'Config JSON', self.config_path, 1, width=FORM_PATH_WIDTH_CHARS, columnspan=4)
        grid_button_row(
            io_frame,
            row=2,
            column=1,
            columnspan=4,
            buttons=[
                ('Browse', self.browse_config),
                ('Load JSON', self.load_config),
                ('Save JSON', self.save_config),
                ('Build Unified Example JSON', self.save_unified_example_config),
            ],
        )
        grid_labeled_entry(io_frame, 'Output Directory', self.output_directory, 3, columnspan=4)
        grid_labeled_entry(io_frame, 'Output Prefix', self.output_prefix, 4, columnspan=4)
        grid_labeled_entry(io_frame, 'Huber Temp Curve °C (comma-separated)', self.huber_curve_c, 5, columnspan=4)
        grid_labeled_entry(io_frame, 'TEC Voltage Curve V (comma-separated)', self.voltage_curve_v, 6, columnspan=4)
        grid_labeled_entry(io_frame, 'TEC Current Curve A (comma-separated)', self.current_curve_a, 7, columnspan=4)
        grid_labeled_entry(io_frame, 'Step Duration Seconds', self.step_duration_s, 8, width=16)
        Label(io_frame, text='Build Unified Example JSON is a template generator: it uses only non-empty curve fields and does not start hardware.').grid(row=8, column=2, columnspan=3, sticky='w')

        runtime_frame.grid_columnconfigure(1, weight=1)
        io_frame.grid_columnconfigure(1, weight=0)
        io_frame.grid_columnconfigure(4, weight=1)
        io_frame.grid_rowconfigure(9, weight=1)

        buttons = Frame(self.run_tab, padx=8, pady=4)
        buttons.pack(fill=BOTH, padx=4)
        Button(buttons, text='Start Logging', command=self.start_logging).pack(side=LEFT, padx=(0, 6))
        Button(buttons, text='Force Stop', command=self.force_stop).pack(side=LEFT, padx=(0, 6))
        Button(buttons, text='Select Columns for Live Plot', command=self.apply_plot_selection).pack(side=LEFT)
        Button(buttons, text='Clear Plot', command=self.clear_plot).pack(side=LEFT, padx=(6, 0))
        Button(buttons, text='Use selection for Plot 2', command=self.apply_second_plot_selection).pack(side=LEFT, padx=(6, 0))
        Button(buttons, text='Zero TEC Output', command=self.zero_output).pack(side=LEFT, padx=(6, 0))

        manual_frame = Frame(self.manual_tab, padx=8, pady=8)
        manual_frame.pack(fill=BOTH, expand=True)
        Label(manual_frame, text='Manual Commands', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=8, sticky='w')
        Label(manual_frame, textvariable=self.manual_command_status, justify=LEFT, anchor='w').grid(row=1, column=0, columnspan=8, sticky='we')
        Label(manual_frame, text='TEC V / A').grid(row=2, column=0, sticky='w')
        Entry(manual_frame, textvariable=self.manual_tec_voltage_v, width=8).grid(row=2, column=1, sticky='w')
        Entry(manual_frame, textvariable=self.manual_tec_current_a, width=8).grid(row=2, column=2, sticky='w')
        Button(manual_frame, text='Set TEC V/I', command=self.manual_set_tec_voltage_current).grid(row=2, column=3, sticky='w')
        Button(manual_frame, text='Zero TEC', command=self.zero_output).grid(row=2, column=4, sticky='w')
        Label(manual_frame, text='TEC power is controlled by voltage/current; W is logged/previewed as V×I.').grid(row=2, column=5, columnspan=3, sticky='w')
        Label(manual_frame, text='Huber °C').grid(row=3, column=0, sticky='w')
        Entry(manual_frame, textvariable=self.manual_huber_temp_c, width=10).grid(row=3, column=1, sticky='w')
        Button(manual_frame, text='Set Huber Temp', command=self.manual_set_huber_temperature).grid(row=3, column=2, sticky='w')
        Button(manual_frame, text='Start Huber Process', command=self.manual_start_huber_process).grid(row=3, column=3, sticky='w')
        Button(manual_frame, text='Stop Huber Process', command=self.manual_stop_huber_process).grid(row=3, column=4, sticky='w')
        Button(manual_frame, text='Read Huber', command=self.manual_read_huber).grid(row=3, column=5, sticky='w')
        manual_frame.grid_columnconfigure(7, weight=1)

        mid = Frame(self.run_tab, padx=8, pady=4)
        mid.pack(fill=BOTH, expand=True)
        left_col = Frame(mid)
        left_col.pack(side=LEFT, fill='y', padx=(0, 8))
        Label(left_col, text='Columns to plot').pack(anchor='w')
        scroller = Scrollbar(left_col, orient=VERTICAL)
        self.columns_list = Listbox(left_col, selectmode='extended', yscrollcommand=scroller.set, height=6, width=24, exportselection=False)
        scroller.config(command=self.columns_list.yview)
        self.columns_list.pack(side=LEFT, fill='y')
        self.columns_list.bind('<Double-Button-1>', self._apply_double_clicked_column)
        scroller.pack(side=RIGHT, fill='y')

        right_col = Frame(mid)
        right_col.pack(side=LEFT, fill=BOTH, expand=True)
        Label(right_col, text='Live plots').pack(anchor='w')
        self.plot_frame = Frame(right_col)
        self.plot_frame.pack(fill=BOTH, expand=True)
        self.request_plot_frame = Frame(io_frame)
        self.request_plot_frame.grid(row=9, column=0, columnspan=5, sticky='nsew', pady=(8, 0))
        self.canvas = None
        self.figure = None
        self.axis = None
        self.request_axes = None
        self.request_canvas = None
        self.request_figure = None
        if Figure is not None:
            self.figure = Figure(figsize=(7.2, 2.4), dpi=100)
            self.axis = self.figure.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_frame)
            self.canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.axis.set_title('Live plot (select columns then start)')
            self.axis.set_xlabel('Timestamp (UTC)')
            self.axis.grid(True, which='major', linestyle='--', alpha=0.6)
            self.request_figure = Figure(figsize=(5.5, PREVIEW_PLOT_HEIGHT_IN), dpi=100)
            self.request_axes = self.request_figure.subplots(2, 1, sharex=True)
            self.request_canvas = FigureCanvasTkAgg(self.request_figure, master=self.request_plot_frame)
            self.request_canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.request_axes[0].set_title('Requested input from loaded JSON')
            self.request_axes[0].set_ylabel('TEC requested W')
            self.request_axes[1].set_xlabel('Seconds')
            self.request_axes[1].set_ylabel('Huber requested °C')
            self.request_axes[0].grid(True, which='major', linestyle='--', alpha=0.6)
            self.request_axes[1].grid(True, which='major', linestyle='--', alpha=0.6)
            self.canvas.draw_idle()
            self.request_canvas.draw_idle()
        Checkbutton(io_frame, text='Show requested input line', variable=self.show_requested_line, command=self._redraw_requested_input_plot).grid(row=10, column=0, columnspan=2, sticky='w')
        recipe_frame = Frame(self.example_editor_tab, padx=8, pady=8)
        recipe_frame.pack(fill=BOTH, expand=True)
        Label(recipe_frame, text='Recipe Builder (click preview points or edit table rows)', font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')

        recipe_fields_frame = Frame(recipe_frame, padx=4, pady=4, relief='groove', bd=1)
        recipe_fields_frame.grid(row=1, column=0, sticky='nw', padx=(0, 8))
        Label(recipe_fields_frame, text='Step fields', font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        grid_labeled_entry(recipe_fields_frame, 'Name', self.recipe_step_name, 1, width=16)
        grid_labeled_entry(recipe_fields_frame, 'Duration s', self.recipe_duration_s, 2, width=10)
        grid_labeled_entry(recipe_fields_frame, 'Bath °C', self.recipe_bath_temp_c, 3, width=10)
        grid_labeled_entry(recipe_fields_frame, 'TEC Voltage V', self.recipe_tec_voltage_v, 4, width=10)
        grid_labeled_entry(recipe_fields_frame, 'TEC Current A', self.recipe_tec_current_a, 5, width=10)
        grid_labeled_entry(recipe_fields_frame, 'TEC Preview W', self.recipe_tec_power_w, 6, width=10)

        grid_button_row(
            recipe_frame,
            row=2,
            column=0,
            columnspan=1,
            buttons=[
                ('Add/Update Step', self.recipe_add_or_update_step),
                ('Delete Step', self.recipe_delete_selected_step),
                ('Save Recipe JSON', self.save_recipe_config),
            ],
        )

        recipe_table_frame = Frame(recipe_frame)
        recipe_table_frame.grid(row=1, column=1, rowspan=2, sticky='nsew')
        recipe_table_frame.grid_columnconfigure(0, weight=1)
        recipe_table_frame.grid_rowconfigure(0, weight=1)
        self.recipe_list = Listbox(recipe_table_frame, height=7, width=RECIPE_LIST_WIDTH_CHARS, exportselection=False)
        self.recipe_list.grid(row=0, column=0, sticky='nsew')
        self.recipe_list.bind('<<ListboxSelect>>', self._recipe_selection_changed)
        self.recipe_plot_frame = Frame(recipe_frame)
        self.recipe_plot_frame.grid(row=3, column=0, columnspan=2, sticky='nsew', pady=(8, 0))
        self.recipe_figure = None
        self.recipe_axes = None
        self.recipe_canvas = None
        if Figure is not None:
            self.recipe_figure = Figure(figsize=(5.5, RECIPE_PREVIEW_PLOT_HEIGHT_IN), dpi=100)
            self.recipe_axes = self.recipe_figure.subplots(2, 1, sharex=True)
            self.recipe_canvas = FigureCanvasTkAgg(self.recipe_figure, master=self.recipe_plot_frame)
            self.recipe_canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.recipe_canvas.mpl_connect('button_press_event', self._recipe_plot_clicked)
            self._redraw_recipe_plot()
        recipe_frame.grid_columnconfigure(1, weight=1)
        recipe_frame.grid_rowconfigure(3, weight=1)
        Checkbutton(right_col, text='Show live line (default on)', variable=self.show_live_line, command=self._redraw_plot).pack(anchor='w')
        Checkbutton(right_col, text='Enable second live plot (defaults to diff voltage 1/2)', variable=self.enable_second_plot, command=self._redraw_plot).pack(anchor='w')
        self._fit_window_to_screen()

    def _update_scroll_region(self, _event=None) -> None:
        if hasattr(self, 'scroll_canvas'):
            self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox('all'))

    def _resize_scroll_window(self, event) -> None:
        if hasattr(self, 'content_window'):
            self.scroll_canvas.itemconfigure(self.content_window, width=max(1, event.width))

    def _on_mousewheel(self, event) -> None:
        if not hasattr(self, 'scroll_canvas'):
            return
        if getattr(event, 'num', None) == 4:
            delta = -1
        elif getattr(event, 'num', None) == 5:
            delta = 1
        else:
            delta = -int(getattr(event, 'delta', 0) / 120)
        if delta:
            self.scroll_canvas.yview_scroll(delta, 'units')

    def _format_seconds(self, seconds: float | None) -> str:
        if seconds is None:
            return 'n/a'
        seconds = max(0, int(round(seconds)))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f'{hours:d}:{minutes:02d}:{secs:02d}'
        return f'{minutes:d}:{secs:02d}'

    def _format_done_at(self, started_at: float | None, remaining_s: float | None) -> str:
        if started_at is None or remaining_s is None:
            return 'Done at: n/a'
        done_at = datetime.fromtimestamp(time.time() + max(0.0, remaining_s))
        return f"Done at: {done_at:%Y-%m-%d %H:%M:%S}"

    def _loaded_recipe_label(self) -> str:
        path = self.config_path.get().strip()
        name = Path(path).name if path else 'no JSON loaded'
        mode = self.detected_mode.get().strip() or self.run_mode.get().strip() or 'unknown mode'
        total = self.loaded_run_total_seconds or self._duration_seconds_or_none() or 0.0
        curves = []
        if self.loaded_schedule_points:
            curves.append('TEC')
        if self.loaded_temp_schedule_points:
            curves.append('Huber')
        curve_text = '+'.join(curves) if curves else 'no previewable setpoints'
        duration_text = self._format_seconds(total) if total else 'n/a'
        return f'Recipe to run: {name} | {mode} | {curve_text} | total {duration_text}'

    def _duration_seconds_or_none(self) -> float | None:
        try:
            text = self.duration.get().strip()
            if not text:
                return None
            value = float(text)
        except Exception:
            return None
        return value if value > 0 else None

    def _set_run_progress_idle(self, message: str = 'Progress: idle') -> None:
        self._run_started_at_epoch = None
        self._current_run_duration_s = None
        self.run_progress_text.set(message)
        self.run_eta_text.set('Done at: n/a')
        self._redraw_run_preview(progress_fraction=0.0)

    def _start_run_progress(self, total_seconds: float | None) -> None:
        self._run_started_at_epoch = time.time()
        self._current_run_duration_s = total_seconds if total_seconds and total_seconds > 0 else None
        self._update_run_progress_indicator()

    def _finish_run_progress(self, message: str) -> None:
        if self._progress_update_job is not None:
            try:
                self.root.after_cancel(self._progress_update_job)
            except Exception:
                pass
            self._progress_update_job = None
        elapsed = None if self._run_started_at_epoch is None else time.time() - self._run_started_at_epoch
        total = self._current_run_duration_s
        if total:
            self._redraw_run_preview(progress_fraction=1.0)
            self.run_progress_text.set(f'{message} | elapsed {self._format_seconds(elapsed)} of {self._format_seconds(total)}')
        else:
            self.run_progress_text.set(f'{message} | elapsed {self._format_seconds(elapsed)}')
        self.run_eta_text.set('Done at: n/a')
        self._run_started_at_epoch = None
        self._current_run_duration_s = None

    def _update_run_progress_indicator(self) -> None:
        if self._run_started_at_epoch is None:
            return
        elapsed = time.time() - self._run_started_at_epoch
        total = self._current_run_duration_s
        if total:
            remaining = max(0.0, total - elapsed)
            fraction = min(1.0, max(0.0, elapsed / total))
            self.run_progress_text.set(
                f'Progress: elapsed {self._format_seconds(elapsed)} / {self._format_seconds(total)} | remaining {self._format_seconds(remaining)}'
            )
            self.run_eta_text.set(self._format_done_at(self._run_started_at_epoch, remaining))
            self._redraw_run_preview(progress_fraction=fraction)
        else:
            self.run_progress_text.set(f'Progress: elapsed {self._format_seconds(elapsed)} | remaining n/a (open-ended run)')
            self.run_eta_text.set('Done at: n/a')
            self._redraw_run_preview(progress_fraction=0.0)
        self._progress_update_job = self.root.after(1000, self._update_run_progress_indicator)

    def _redraw_run_preview(self, progress_fraction: float | None = None) -> None:
        canvas = getattr(self, 'run_preview_canvas', None)
        if canvas is None:
            return
        canvas.delete('all')
        width = int(canvas.winfo_width() or 320)
        height = int(canvas.winfo_height() or 78)
        pad_x = 24
        top = 10
        mid = height // 2
        bottom = height - 16
        plot_w = max(1, width - (2 * pad_x))
        canvas.create_text(6, top + 4, text='TEC', anchor='w', fill='orange')
        canvas.create_text(6, bottom - 2, text='Bath', anchor='w', fill='blue')
        canvas.create_line(pad_x, mid, width - pad_x, mid, fill='gray85')
        max_t = self.loaded_run_total_seconds or 0.0
        all_values = [v for _, v in self.loaded_schedule_points] + [v for _, v in self.loaded_temp_schedule_points]
        if max_t <= 0 or not all_values:
            canvas.create_text(width // 2, mid, text='Load JSON to preview recipe', fill='gray45')
        else:
            def scale_x(t: float) -> float:
                return pad_x + (float(t) / max_t) * plot_w

            def draw_curve(points: list[tuple[float, float]], color: str, y_min: int, y_max: int) -> None:
                if not points:
                    return
                vals = [v for _, v in points]
                lo = min(vals)
                hi = max(vals)
                span = hi - lo if hi != lo else 1.0
                coords = []
                for t, value in points:
                    x = scale_x(t)
                    y = y_max - ((value - lo) / span) * (y_max - y_min)
                    coords.extend((x, y))
                if len(coords) >= 4:
                    canvas.create_line(*coords, fill=color, width=2)
                for x, y in zip(coords[0::2], coords[1::2]):
                    canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline=color)

            draw_curve(self.loaded_schedule_points, 'orange', top + 2, mid - 4)
            draw_curve(self.loaded_temp_schedule_points, 'blue', mid + 4, bottom)
        if progress_fraction is None:
            progress_fraction = 0.0 if self._run_started_at_epoch is None else None
            if progress_fraction is None and self._current_run_duration_s:
                progress_fraction = min(1.0, max(0.0, (time.time() - self._run_started_at_epoch) / self._current_run_duration_s))
        progress_fraction = 0.0 if progress_fraction is None else min(1.0, max(0.0, progress_fraction))
        x = pad_x + progress_fraction * plot_w
        canvas.create_line(x, top, x, bottom, fill='red', width=2)
        canvas.create_text(pad_x, height - 3, text='0', anchor='sw', fill='gray40')
        canvas.create_text(width - pad_x, height - 3, text=self._format_seconds(max_t) if max_t else 'n/a', anchor='se', fill='gray40')

    def _fit_window_to_screen(self) -> None:
        self.root.update_idletasks()
        geometry, min_width, min_height = self._window_geometry_for_screen(
            screen_width=self.root.winfo_screenwidth(),
            screen_height=self.root.winfo_screenheight(),
            requested_width=self.content_frame.winfo_reqwidth() + 24,
            requested_height=self.content_frame.winfo_reqheight() + 24,
        )
        self.root.minsize(min_width, min_height)
        self.root.geometry(geometry)

    @staticmethod
    def _window_geometry_for_screen(
        screen_width: int,
        screen_height: int,
        requested_width: int,
        requested_height: int,
    ) -> tuple[str, int, int]:
        usable_width = max(320, screen_width - WINDOW_SCREEN_MARGIN_PX)
        usable_height = max(240, screen_height - WINDOW_SCREEN_MARGIN_PX)
        if usable_width < WINDOW_MIN_WIDTH_PX or usable_height < WINDOW_MIN_HEIGHT_PX:
            usable_width = max(320, screen_width - WINDOW_SMALL_SCREEN_MARGIN_PX)
            usable_height = max(240, screen_height - WINDOW_SMALL_SCREEN_MARGIN_PX)

        preferred_width = max(requested_width, WINDOW_MIN_WIDTH_PX)
        preferred_height = max(requested_height, WINDOW_MIN_HEIGHT_PX)
        width = min(preferred_width, usable_width)
        height = min(preferred_height, usable_height)
        min_width = min(WINDOW_MIN_WIDTH_PX, width)
        min_height = min(WINDOW_MIN_HEIGHT_PX, height)
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        return f'{int(width)}x{int(height)}+{int(x)}+{int(y)}', int(min_width), int(min_height)

    @staticmethod
    def _parse_numeric_field(text: str, label: str) -> float:
        try:
            return float(str(text).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{label} must be a number') from exc

    def _run_manual_command(self, label: str, action) -> None:
        try:
            result = action()
            suffix = f': {result}' if result is not None else ''
            self.manual_command_status.set(f'Manual commands: {label} complete{suffix}')
        except Exception as exc:
            self.manual_command_status.set(f'Manual commands: {label} failed ({exc})')
            messagebox.showerror(f'{label} failed', str(exc))

    def manual_set_tec_voltage_current(self) -> None:
        def action():
            voltage_v = self._parse_numeric_field(self.manual_tec_voltage_v.get(), 'TEC voltage V')
            current_a = self._parse_numeric_field(self.manual_tec_current_a.get(), 'TEC current A')
            adapter = TecPowerAdapter(self._build_config())
            try:
                adapter.connect()
                adapter.set_voltage_current(voltage_v, current_a)
            finally:
                adapter.close()
            self._set_tec_connection_status('green', f'TEC: manual V/I set to {voltage_v:g} V, {current_a:g} A')

        self._run_manual_command('Set TEC V/I', action)

    def _with_huber_adapter(self, action):
        adapter = HuberWorkflowAdapter(port=self.huber_port.get().strip() or None)
        try:
            if not adapter.connect():
                raise RuntimeError('Huber connect() returned False')
            return action(adapter)
        finally:
            adapter.close()

    def manual_set_huber_temperature(self) -> None:
        def action():
            temp_c = self._parse_numeric_field(self.manual_huber_temp_c.get(), 'Huber temperature °C')
            ok = self._with_huber_adapter(lambda adapter: adapter.set_setpoint(temp_c))
            if not ok:
                raise RuntimeError('Huber setpoint command returned False')
            self._set_huber_connection_status('green', f'Huber: manual setpoint {temp_c:g} °C')

        self._run_manual_command('Set Huber temp', action)

    def manual_start_huber_process(self) -> None:
        def action():
            ok = self._with_huber_adapter(lambda adapter: adapter.start_process())
            if not ok:
                raise RuntimeError('Huber start-process command returned False')
            self._set_huber_connection_status('green', 'Huber: process started (thermoregulation ON)')

        self._run_manual_command('Start Huber process', action)

    def manual_stop_huber_process(self) -> None:
        def action():
            ok = self._with_huber_adapter(lambda adapter: adapter.stop_process())
            if not ok:
                raise RuntimeError('Huber stop-process command returned False')
            self._set_huber_connection_status('green', 'Huber: process stopped (thermoregulation OFF)')

        self._run_manual_command('Stop Huber process', action)

    def manual_read_huber(self) -> None:
        def action():
            bath_temp, setpoint = self._with_huber_adapter(lambda adapter: (adapter.read_bath_temp(), adapter.read_setpoint()))
            self._set_huber_connection_status('green', f'Huber: bath {bath_temp} °C, setpoint {setpoint} °C')
            return f'bath={bath_temp} °C, setpoint={setpoint} °C'

        self._run_manual_command('Read Huber', action)

    def _recipe_step_from_inputs(self) -> dict[str, object]:
        duration_s = self._parse_numeric_field(self.recipe_duration_s.get(), 'Recipe duration seconds')
        step: dict[str, object] = {
            'name': self.recipe_step_name.get().strip() or f'step_{len(self.recipe_points) + 1}',
            'duration_s': duration_s,
            'progression_mode': 'time',
        }
        if duration_s <= 0:
            raise ValueError('Recipe duration must be > 0')
        bath_text = self.recipe_bath_temp_c.get().strip()
        voltage_text = self.recipe_tec_voltage_v.get().strip()
        current_text = self.recipe_tec_current_a.get().strip()
        power_text = self.recipe_tec_power_w.get().strip()
        if bath_text:
            step['bath_setpoint_c'] = self._parse_numeric_field(bath_text, 'Recipe bath temperature °C')
        if voltage_text or current_text:
            if not voltage_text or not current_text:
                raise ValueError('Recipe TEC voltage and current must both be filled, or both blank')
            voltage_v = self._parse_numeric_field(voltage_text, 'Recipe TEC voltage V')
            current_a = self._parse_numeric_field(current_text, 'Recipe TEC current A')
            step['tec_voltage_v'] = voltage_v
            step['tec_current_a'] = current_a
            step['tec_power_w'] = self._parse_numeric_field(power_text, 'Recipe TEC power W') if power_text else voltage_v * current_a
        elif power_text:
            step['tec_power_w'] = self._parse_numeric_field(power_text, 'Recipe TEC power W')
        if 'bath_setpoint_c' not in step and 'tec_power_w' not in step:
            raise ValueError('Recipe step must include a bath setpoint or TEC setpoint')
        return step

    def recipe_add_or_update_step(self) -> None:
        try:
            step = self._recipe_step_from_inputs()
        except ValueError as exc:
            messagebox.showerror('Invalid recipe step', str(exc))
            return
        selection = list(self.recipe_list.curselection()) if hasattr(self, 'recipe_list') else []
        if selection:
            self.recipe_points[selection[0]] = step
        else:
            self.recipe_points.append(step)
            self.recipe_step_name.set(f'step_{len(self.recipe_points) + 1}')
        self._refresh_recipe_table()
        self._redraw_recipe_plot()

    def recipe_delete_selected_step(self) -> None:
        selection = list(self.recipe_list.curselection()) if hasattr(self, 'recipe_list') else []
        if not selection:
            return
        del self.recipe_points[selection[0]]
        self._refresh_recipe_table()
        self._redraw_recipe_plot()

    def _recipe_selection_changed(self, _event=None) -> None:
        selection = list(self.recipe_list.curselection()) if hasattr(self, 'recipe_list') else []
        if not selection:
            return
        step = self.recipe_points[selection[0]]
        self.recipe_step_name.set(str(step.get('name', '')))
        self.recipe_duration_s.set(str(step.get('duration_s', '')))
        self.recipe_bath_temp_c.set('' if step.get('bath_setpoint_c') is None else str(step.get('bath_setpoint_c')))
        self.recipe_tec_voltage_v.set('' if step.get('tec_voltage_v') is None else str(step.get('tec_voltage_v')))
        self.recipe_tec_current_a.set('' if step.get('tec_current_a') is None else str(step.get('tec_current_a')))
        self.recipe_tec_power_w.set('' if step.get('tec_power_w') is None else str(step.get('tec_power_w')))

    def _refresh_recipe_table(self) -> None:
        if not hasattr(self, 'recipe_list'):
            return
        self.recipe_list.delete(0, END)
        elapsed = 0.0
        for idx, step in enumerate(self.recipe_points, start=1):
            duration = float(step.get('duration_s', 0.0) or 0.0)
            bath = step.get('bath_setpoint_c', '')
            power = step.get('tec_power_w', '')
            voltage = step.get('tec_voltage_v', '')
            current = step.get('tec_current_a', '')
            self.recipe_list.insert(
                END,
                f'{idx:02d} t={elapsed:g}s dur={duration:g}s name={step.get("name", "")} bath={bath}C tec={power}W ({voltage}V/{current}A)',
            )
            elapsed += duration

    def _redraw_recipe_plot(self) -> None:
        if getattr(self, 'recipe_axes', None) is None or getattr(self, 'recipe_canvas', None) is None:
            return
        tec_axis, huber_axis = self.recipe_axes
        tec_axis.clear()
        huber_axis.clear()
        tec_axis.set_title('Recipe preview')
        tec_axis.set_ylabel('TEC W')
        huber_axis.set_ylabel('Bath °C')
        huber_axis.set_xlabel('Seconds')
        tec_points, bath_points = self._recipe_preview_points(self.recipe_points)
        if tec_points:
            tec_axis.plot([x for x, _ in tec_points], [y for _, y in tec_points], marker='o', color='tab:orange')
        else:
            tec_axis.text(0.5, 0.5, 'No TEC recipe points', transform=tec_axis.transAxes, ha='center', va='center')
        if bath_points:
            huber_axis.plot([x for x, _ in bath_points], [y for _, y in bath_points], marker='o', color='tab:blue')
        else:
            huber_axis.text(0.5, 0.5, 'No Huber recipe points', transform=huber_axis.transAxes, ha='center', va='center')
        tec_axis.grid(True, which='major', linestyle='--', alpha=0.6)
        huber_axis.grid(True, which='major', linestyle='--', alpha=0.6)
        self.recipe_figure.tight_layout()
        self.recipe_canvas.draw_idle()

    @staticmethod
    def _recipe_preview_points(steps: list[dict[str, object]]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        tec_points: list[tuple[float, float]] = []
        bath_points: list[tuple[float, float]] = []
        elapsed = 0.0
        for step in steps:
            duration = float(step.get('duration_s', 0.0) or 0.0)
            power = step.get('tec_power_w')
            bath = step.get('bath_setpoint_c')
            if power is not None:
                y = float(power)
                tec_points.extend([(elapsed, y), (elapsed + duration, y)])
            if bath is not None:
                y = float(bath)
                bath_points.extend([(elapsed, y), (elapsed + duration, y)])
            elapsed += duration
        return tec_points, bath_points

    def _recipe_plot_clicked(self, event) -> None:
        if event.xdata is None or event.ydata is None or getattr(self, 'recipe_axes', None) is None:
            return
        duration = max(float(event.xdata), 1.0)
        self.recipe_duration_s.set(f'{duration:g}')
        if event.inaxes == self.recipe_axes[0]:
            self.recipe_tec_power_w.set(f'{float(event.ydata):g}')
        elif event.inaxes == self.recipe_axes[1]:
            self.recipe_bath_temp_c.set(f'{float(event.ydata):g}')

    def _build_recipe_payload(self) -> dict[str, object]:
        if not self.recipe_points:
            raise ValueError('Add at least one recipe step before saving')
        return {
            'run_name': 'gui_recipe',
            'steps': list(self.recipe_points),
            'safety': {
                'tec_power_w_on_stop': 0.0,
                'bath_standby_setpoint_c': float(self.bath_standby_temp_c.get()),
                'pump_on_in_safe_state': bool(self.pump_safe_on.get()),
            },
        }

    def save_recipe_config(self) -> None:
        path_text = self.config_path.get().strip() or filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
        if not path_text:
            return
        try:
            payload = self._build_recipe_payload()
        except ValueError as exc:
            messagebox.showerror('Invalid recipe', str(exc))
            return
        self.config_path.set(path_text)
        with open(path_text, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2)
            handle.write('\n')
        self._load_requested_input_from_config(path_text)
        self._remember_last_config_path(path_text)

    def browse_config(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[('JSON files', '*.json'), ('All files', '*.*')])
        if selected:
            self.config_path.set(selected)

    def _build_config(self) -> LiveLoggerConfig:
        duration = float(self.duration.get()) if self.duration.get().strip() else None
        normalized_schedule = [
            step if isinstance(step, PowerScheduleStep) else PowerScheduleStep.from_dict(step)
            for step in self.loaded_power_schedule
        ]
        serial_port = self.serial_port.get().strip() or None
        # Match the standalone TEC GUI's practical behavior for TEC runs: if no
        # explicit port is filled in, let the common TEC logger resolve one.
        serial_autodetect = bool(self.serial_autodetect.get()) or serial_port is None
        return LiveLoggerConfig(
            transport='com',
            serial_port=serial_port,
            serial_port_autodetect=serial_autodetect,
            serial_port_hint=self.serial_hint.get().strip() or None,
            address=int(self.address.get()),
            channel=int(self.channel.get()),
            output_directory=self.output_directory.get().strip() or 'live_logs',
            output_prefix=self.output_prefix.get().strip() or 'power_live_log_com',
            parameters=default_live_parameters(channel=int(self.channel.get())),
            power_schedule=normalized_schedule,
            allow_named_voltage_current_fallback=True,
            duration_seconds=duration,
            acquisition_hz=float(self.hz.get()),
        )

    def load_config(self) -> None:
        path_text = self.config_path.get().strip()
        if not path_text:
            return
        try:
            content = self._read_json_config(path_text)
        except Exception as exc:
            messagebox.showerror('Load JSON failed', str(exc))
            return
        detected_mode = self._detect_mode_from_content(content)
        self.detected_mode.set(detected_mode)
        self.run_mode.set(detected_mode)
        try:
            if detected_mode in {"Unified", "Huber-only"}:
                rcfg = RunConfig.from_dict(content)
                self.duration.set(str(sum(step.duration_s for step in rcfg.steps)))
                self.bath_standby_temp_c.set(str(rcfg.safety.bath_standby_setpoint_c))
                self.pump_safe_on.set(1 if rcfg.safety.pump_on_in_safe_state else 0)
            else:
                cfg = LiveLoggerConfig.from_json_file(path_text)
                self.serial_port.set(cfg.serial_port or '')
                self.serial_autodetect.set(1 if cfg.serial_port_autodetect else 0)
                self.serial_hint.set(cfg.serial_port_hint or '')
                self.address.set(str(cfg.address))
                self.channel.set(str(cfg.channel))
                self.duration.set('' if cfg.duration_seconds is None else str(cfg.duration_seconds))
                self.hz.set(str(cfg.acquisition_hz))
                self.output_directory.set(cfg.output_directory)
                self.output_prefix.set(cfg.output_prefix)
        except Exception as exc:
            messagebox.showerror('Load JSON failed', str(exc))
            return
        self._load_requested_input_from_config(path_text)
        if hasattr(self, 'run_recipe_summary_text'):
            self.run_recipe_summary_text.set(self._loaded_recipe_label())
        self._redraw_run_preview()
        self._remember_last_config_path(path_text)

    def _detect_mode_from_content(self, content: dict) -> str:
        if looks_like_unified_run_config(content):
            try:
                steps = RunConfig.from_dict(content).steps
            except Exception:
                return "Unified"
            has_tec = any(step.tec_power_w is not None or step.tec_voltage_v is not None or step.tec_current_a is not None for step in steps)
            has_huber = any(step.bath_setpoint_c is not None for step in steps)
            if has_huber and not has_tec:
                return "Huber-only"
            if has_tec and not has_huber:
                return "TEC-only"
            return "Unified"
        return "TEC-only"

    @staticmethod
    def _read_json_config(path_text: str) -> dict:
        content = json.loads(Path(path_text).read_text(encoding='utf-8'))
        if not isinstance(content, dict):
            raise ValueError('Top-level JSON content must be an object')
        return content

    @staticmethod
    def _ole_to_unix_timestamp(ole_date: float) -> float:
        return (ole_date - OLE_AUTOMATION_UNIX_EPOCH_OFFSET_DAYS) * SECONDS_PER_DAY

    def _configure_live_plot_columns(self, columns: list[str], default_columns: list[str]) -> None:
        self.columns_list.delete(0, END)
        for column in columns:
            self.columns_list.insert(END, column)
        if not self.selected_cols:
            self.selected_cols = [column for column in default_columns if column in columns]
        if not self.selected_cols and columns:
            self.selected_cols = [columns[0]]
        for idx, column in enumerate(columns):
            if column in self.selected_cols:
                self.columns_list.selection_set(idx)
            self.live_data.setdefault(column, deque(maxlen=MAX_POINTS))

    def _validate_mode_compatibility(self, content: dict, requested_mode: str) -> str | None:
        if requested_mode in {"Unified", "Huber-only"}:
            has_shared_or_legacy_shape = (
                looks_like_unified_run_config(content)
                or (requested_mode == "Unified" and isinstance(content.get("power_schedule"), list))
                or (requested_mode == "Unified" and bool(legacy_tec_steps_to_power_schedule(content)))
            )
            if not has_shared_or_legacy_shape:
                return f"{requested_mode} mode requires shared steps with bath_setpoint_c entries."
            if requested_mode == "Huber-only":
                run_cfg = RunConfig.from_dict(content)
                has_huber = any(step.bath_setpoint_c is not None for step in run_cfg.steps)
                has_tec = any(step.tec_power_w is not None or step.tec_voltage_v is not None or step.tec_current_a is not None for step in run_cfg.steps)
                if not has_huber:
                    return "Huber-only mode requires at least one bath_setpoint_c step."
                if has_tec:
                    return "Huber-only mode cannot run steps with TEC power, voltage, or current requests. Choose Unified instead."
            return None
        if requested_mode == "TEC-only":
            has_tec_shape = (
                isinstance(content.get("power_schedule"), list)
                or bool(legacy_tec_steps_to_power_schedule(content))
                or "transport" in content
                or looks_like_unified_run_config(content)
            )
            if not has_tec_shape:
                return "TEC-only mode expects shared steps, live logger power_schedule entries, or older TEC calibration steps."
        return None

    def _load_requested_input_from_config(self, path_text: str) -> None:
        self.loaded_schedule_points = []
        self.loaded_temp_schedule_points = []
        self.loaded_power_schedule = []
        total_duration = 0.0
        try:
            content = self._read_json_config(path_text)
            schedule = content.get('power_schedule') or legacy_tec_steps_to_power_schedule(content)
            unified_steps = content.get('steps', []) if looks_like_unified_run_config(content) else []
            self.loaded_power_schedule = list(schedule)
            t = 0.0
            detected_mode = self._detect_mode_from_content(content)
            self.detected_mode.set(detected_mode)
            self.run_mode.set(detected_mode)
            if unified_steps:
                for step in unified_steps:
                    duration = float(step.get('duration_s', 0.0) or 0.0)
                    tec_power = self._tec_preview_power_from_step(step)
                    bath_temp_raw = step.get('bath_setpoint_c')
                    if tec_power is not None:
                        self.loaded_schedule_points.append((t, tec_power))
                    if bath_temp_raw is not None:
                        bath_temp = float(bath_temp_raw)
                        self.loaded_temp_schedule_points.append((t, bath_temp))
                    t += duration
                    if tec_power is not None:
                        self.loaded_schedule_points.append((t, tec_power))
                    if bath_temp_raw is not None:
                        self.loaded_temp_schedule_points.append((t, bath_temp))
            else:
                for step in schedule:
                    duration = float(step.get('duration_seconds', 0.0) or 0.0)
                    set_voltage = float(step.get('set_voltage', 0.0) or 0.0)
                    self.loaded_schedule_points.append((t, set_voltage))
                    t += duration
                    self.loaded_schedule_points.append((t, set_voltage))
            total_duration = t
        except Exception:
            self.loaded_schedule_points = []
            self.loaded_temp_schedule_points = []
            total_duration = 0.0
        self.loaded_run_total_seconds = total_duration
        if total_duration > 0.0:
            self.duration.set(f'{total_duration:g}')
        if hasattr(self, 'run_recipe_summary_text'):
            self.run_recipe_summary_text.set(self._loaded_recipe_label())
        self._redraw_requested_input_plot()
        self._redraw_run_preview()

    def _parse_curve_values(self, text: str, name: str, *, required: bool = True) -> list[float]:
        parts = [p.strip() for p in text.split(',') if p.strip()]
        if not parts:
            if required:
                raise ValueError(f'{name} is empty')
            return []
        return [float(p) for p in parts]

    @staticmethod
    def _tec_preview_power_from_step(step: dict) -> float | None:
        tec_power_raw = step.get('tec_power_w')
        voltage_raw = step.get('tec_voltage_v', step.get('set_voltage'))
        current_raw = step.get('tec_current_a', step.get('set_current'))
        if voltage_raw is not None and current_raw is not None:
            try:
                derived_power = float(voltage_raw) * float(current_raw)
            except (TypeError, ValueError):
                derived_power = None
            if derived_power is not None:
                try:
                    explicit_power = None if tec_power_raw is None else float(tec_power_raw or 0.0)
                except (TypeError, ValueError):
                    explicit_power = None
                if explicit_power is None or explicit_power == 0.0:
                    return derived_power
        if tec_power_raw is not None:
            return float(tec_power_raw)
        return None

    def _build_unified_example_payload(self) -> dict:
        temps = self._parse_curve_values(self.huber_curve_c.get(), 'Huber temperature curve', required=False)
        volts = self._parse_curve_values(self.voltage_curve_v.get(), 'TEC voltage curve', required=False)
        currents = self._parse_curve_values(self.current_curve_a.get(), 'TEC current curve', required=False)
        has_huber_curve = bool(temps)
        has_voltage_curve = bool(volts)
        has_current_curve = bool(currents)
        if has_voltage_curve != has_current_curve:
            raise ValueError('TEC voltage and TEC current curves must both be filled or both be blank')
        has_tec_curve = has_voltage_curve and has_current_curve
        if not has_huber_curve and not has_tec_curve:
            raise ValueError('Fill at least one curve: Huber temperature, or TEC voltage/current')
        if has_tec_curve and len(volts) != len(currents):
            raise ValueError('TEC voltage and TEC current curves must have the same number of points')
        if has_huber_curve and has_tec_curve and len(temps) != len(volts):
            raise ValueError('Huber and TEC curves must have the same number of points when both are filled')
        point_count = len(temps) if has_huber_curve else len(volts)
        step_duration = float(self.step_duration_s.get())
        if step_duration <= 0:
            raise ValueError('Step duration must be > 0')

        steps = []
        for idx in range(point_count):
            step = {
                'name': f'curve_step_{idx + 1}',
                'duration_s': step_duration,
                'progression_mode': 'time',
            }
            if has_huber_curve:
                step['bath_setpoint_c'] = temps[idx]
            if has_tec_curve:
                volt_v = volts[idx]
                current_a = currents[idx]
                step['tec_power_w'] = volt_v * current_a
                step['tec_voltage_v'] = volt_v
                step['tec_current_a'] = current_a
            steps.append(step)

        run_name_parts = []
        if has_tec_curve:
            run_name_parts.append('tec')
        if has_huber_curve:
            run_name_parts.append('huber')
        return {
            'run_name': f"gui_{'_'.join(run_name_parts)}_curve_template",
            'steps': steps,
            'safety': {
                'tec_power_w_on_stop': 0.0,
                'bath_standby_setpoint_c': float(self.bath_standby_temp_c.get()),
                'pump_on_in_safe_state': bool(self.pump_safe_on.get()),
            },
        }

    def save_unified_example_config(self) -> None:
        path_text = self.config_path.get().strip() or filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
        if not path_text:
            return
        self.config_path.set(path_text)
        try:
            payload = self._build_unified_example_payload()
        except ValueError as exc:
            messagebox.showerror('Invalid curve input', str(exc))
            return
        with open(path_text, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2)
            handle.write('\n')
        self._load_requested_input_from_config(path_text)
        self._remember_last_config_path(path_text)

    def save_config(self) -> None:
        path_text = self.config_path.get().strip() or filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
        if not path_text:
            return
        self.config_path.set(path_text)
        with open(path_text, 'w', encoding='utf-8') as handle:
            json.dump(asdict(self._build_config()), handle, indent=2)
            handle.write('\n')
        self._remember_last_config_path(path_text)

    def _remember_last_config_path(self, path_text: str) -> None:
        LAST_CONFIG_PATH.write_text(path_text + '\n', encoding='utf-8')

    def _load_last_used_config_if_present(self) -> None:
        if LAST_CONFIG_PATH.exists():
            p = LAST_CONFIG_PATH.read_text(encoding='utf-8').strip()
            if p and Path(p).exists():
                self.config_path.set(p)
                self.load_config()

    def apply_plot_selection(self) -> None:
        requested_cols = [self.columns_list.get(i) for i in self.columns_list.curselection()]
        if requested_cols:
            self.selected_cols = requested_cols
            for col in self.selected_cols:
                self.live_data.setdefault(col, deque(maxlen=MAX_POINTS))
        if not self.selected_cols:
            messagebox.showwarning('No columns', 'Select one or more columns.')
            return
        self._redraw_plot()

    def apply_second_plot_selection(self) -> None:
        requested_cols = [self.columns_list.get(i) for i in self.columns_list.curselection()]
        if not requested_cols:
            messagebox.showwarning('No columns', 'Select one or more columns for Plot 2.')
            return
        self.second_plot_cols = requested_cols
        self.enable_second_plot.set(1)
        for col in self.second_plot_cols:
            self.live_data.setdefault(col, deque(maxlen=MAX_POINTS))
        self._redraw_plot()

    def _apply_double_clicked_column(self, event) -> None:
        idx = self.columns_list.nearest(event.y)
        if idx < 0:
            return
        self.columns_list.selection_clear(0, END)
        self.columns_list.selection_set(idx)
        requested_cols = [self.columns_list.get(idx)]
        self.selected_cols = requested_cols
        for col in self.selected_cols + self.second_plot_cols:
            self.live_data.setdefault(col, deque(maxlen=MAX_POINTS))
        self._redraw_plot()

    def start_logging(self) -> None:
        if Figure is None:
            messagebox.showwarning('Missing matplotlib', 'Install matplotlib for required live plotting support.')
            return
        if self.run_thread and self.run_thread.is_alive():
            messagebox.showwarning('Busy', 'Logger is already running.')
            return

        self.stop_requested = False
        self._last_sample_ts = None
        try:
            hz = float(self.hz.get())
        except ValueError:
            messagebox.showerror('Invalid Hz', f'Acquisition rate must be a number greater than or equal to {MIN_HZ:g} Hz.')
            return
        if hz < MIN_HZ:
            messagebox.showerror('Invalid Hz', f'Acquisition rate must be greater than or equal to {MIN_HZ:g} Hz for TEC polling.')
            return
        path_text = self.config_path.get().strip()
        if self.run_mode_selection.get() in {'Unified', 'Huber-only'} and not path_text:
            messagebox.showerror('Shared JSON required', 'Select a shared JSON config file before starting Unified or Huber-only mode.')
            return
        if path_text:
            try:
                content = self._read_json_config(path_text)
            except Exception as exc:
                messagebox.showerror('Load JSON failed', str(exc))
                return
            selected_mode = self.run_mode_selection.get()
            effective_mode = selected_mode if selected_mode != 'Auto' else self._detect_mode_from_content(content)
            mode_error = self._validate_mode_compatibility(content, effective_mode)
            if mode_error:
                messagebox.showerror('Run mode mismatch', mode_error)
                return
            self.run_mode.set(effective_mode)
            if effective_mode in {"Unified", "Huber-only"}:
                self._start_unified_run(path_text, hz, display_mode=effective_mode)
                return
        cfg = self._build_config()
        self._set_controller_status('yellow', 'Controller status: connecting (starting logger)')
        self._set_tec_connection_status('yellow', 'TEC: connecting (starting logger)')
        self._set_huber_connection_status('gray', 'Huber: not used for TEC-only run')
        parameter_columns = [spec.label for spec in cfg.parameters]
        default_col = next((label for label in parameter_columns if 'act u' in label.lower()), parameter_columns[0])
        self._configure_live_plot_columns(parameter_columns, [default_col])
        if not self.second_plot_cols:
            self.second_plot_cols = [label for label in parameter_columns if label.startswith('1046.1:') or label.startswith('1046.2:')][:2]
        for col in self.second_plot_cols:
            self.live_data.setdefault(col, deque(maxlen=MAX_POINTS))

        self.animating = True
        self._schedule_plot_refresh()
        self._start_run_progress(cfg.duration_seconds or self.loaded_run_total_seconds or None)

        def on_started(path: Path) -> None:
            self.last_output_csv = path
            self.root.after(0, lambda: self._set_controller_status('green', f'Controller status: connected (logging to {path.name})'))
            self.root.after(0, lambda: self._set_tec_connection_status('green', f'TEC: connected (logging to {path.name})'))

        def on_row(row: dict[str, object]) -> None:
            t = row.get('OLE Automation Date')
            if isinstance(t, (float, int)):
                unix_ts = self._ole_to_unix_timestamp(float(t))
                self.sample_index.append(unix_ts)
                if self._last_sample_ts is not None and unix_ts > self._last_sample_ts:
                    measured = 1.0 / (unix_ts - self._last_sample_ts)
                    self.root.after(0, lambda m=measured: self.sample_rate_text.set(f'Measured acquisition rate: {m:.2f} Hz'))
                self._last_sample_ts = unix_ts
            else:
                self.sample_index.append(datetime.now(timezone.utc).timestamp())
            for col in self.selected_cols:
                try:
                    val = float(row.get(col, 'nan'))
                except Exception:
                    val = float('nan')
                self.live_data.setdefault(col, deque(maxlen=MAX_POINTS)).append(val)
            for col, raw_val in row.items():
                if col == 'OLE Automation Date' or col in self.selected_cols:
                    continue
                try:
                    val = float(raw_val)
                except Exception:
                    continue
                self.live_data.setdefault(col, deque(maxlen=MAX_POINTS)).append(val)

        def worker() -> None:
            failed = False
            try:
                LiveLogger(cfg).run(
                    hz=hz,
                    duration_seconds=cfg.duration_seconds,
                    started_callback=on_started,
                    row_callback=on_row,
                    stop_requested=lambda: self.stop_requested,
                )
            except Exception as exc:
                failed = True
                error_message = self._format_run_error(exc)
                self.root.after(0, lambda: self._finish_run_progress('Progress: failed'))
                self.root.after(0, lambda e=exc: self._set_controller_status('red', f'Controller status: not detected ({e})'))
                self.root.after(0, lambda e=exc: self._set_tec_connection_status('red', f'TEC: not connected ({e})'))
                self.root.after(0, lambda msg=error_message: messagebox.showerror('Run failed', msg))
            finally:
                self.animating = False
                if self.stop_requested:
                    self.root.after(0, lambda: self._finish_run_progress('Progress: stopped'))
                    self.root.after(0, lambda: self._set_controller_status('yellow', 'Controller status: stopped by user'))
                    self.root.after(0, lambda: self._set_tec_connection_status('yellow', 'TEC: stopped by user'))
                elif not failed:
                    self.root.after(0, lambda: self._finish_run_progress('Progress: complete'))

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _start_unified_run(self, path_text: str, hz: float, display_mode: str = 'Unified') -> None:
        self.run_mode.set(display_mode)
        self.stop_requested = False
        try:
            run_cfg = RunConfig.from_json_file(path_text)
            run_cfg.safety.bath_standby_setpoint_c = float(self.bath_standby_temp_c.get())
        except Exception as exc:
            messagebox.showerror('Unified config invalid', str(exc))
            return
        run_cfg.safety.pump_on_in_safe_state = bool(self.pump_safe_on.get())
        self._configure_live_plot_columns(UNIFIED_LIVE_COLUMNS, UNIFIED_DEFAULT_COLUMNS)
        self.animating = True
        self._schedule_plot_refresh()
        self._start_run_progress(sum(step.duration_s for step in run_cfg.steps))
        has_any_tec_request = any(
            step.tec_power_w is not None or step.tec_voltage_v is not None or step.tec_current_a is not None
            for step in run_cfg.steps
        )
        has_any_huber_request = any(step.bath_setpoint_c is not None for step in run_cfg.steps)
        tec_adapter = TecPowerAdapter(self._build_config()) if has_any_tec_request else NoopTecAdapter()
        bath_adapter = HuberWorkflowAdapter(port=self.huber_port.get().strip() or None) if has_any_huber_request else NoopBathAdapter()
        if has_any_tec_request:
            self._set_tec_connection_status('yellow', 'TEC: connecting (unified run)')
        else:
            self._set_tec_connection_status('gray', 'TEC: not requested by loaded JSON')
        if has_any_huber_request:
            self._set_huber_connection_status('yellow', 'Huber: connecting (unified run)')
        else:
            self._set_huber_connection_status('gray', 'Huber: not requested by loaded JSON')
        engine = DualDeviceRunEngine(tec_adapter, bath_adapter, output_directory=self.output_directory.get().strip() or 'live_logs', sample_hz=hz)
        self.unified_engine = engine

        def on_event(evt: dict[str, object]) -> None:
            if evt.get("event") == "state_transition" and evt.get("next_state") == "RUNNING_STEP":
                if has_any_tec_request:
                    self.root.after(0, lambda: self._set_tec_connection_status('green', 'TEC: connected (unified run)'))
                if has_any_huber_request:
                    self.root.after(0, lambda: self._set_huber_connection_status('green', 'Huber: connected (unified run)'))
            if evt.get("event") == "state_transition" and evt.get("next_state") == "ERROR":
                error = str(evt.get('error', 'unknown'))
                self.root.after(0, lambda err=error: self._set_controller_status('red', f'Controller status: error ({err})'))
                if has_any_tec_request:
                    self.root.after(0, lambda err=error: self._set_tec_connection_status('red', f'TEC: error ({err})'))
                if has_any_huber_request:
                    self.root.after(0, lambda err=error: self._set_huber_connection_status('red', f'Huber: error ({err})'))

        def on_row(row: dict[str, object]) -> None:
            t = row.get('OLE Automation Date')
            if isinstance(t, (float, int)):
                unix_ts = self._ole_to_unix_timestamp(float(t))
                self.sample_index.append(unix_ts)
                if self._last_sample_ts is not None and unix_ts > self._last_sample_ts:
                    measured = 1.0 / (unix_ts - self._last_sample_ts)
                    self.root.after(0, lambda m=measured: self.sample_rate_text.set(f'Measured acquisition rate: {m:.2f} Hz'))
                self._last_sample_ts = unix_ts
            else:
                self.sample_index.append(datetime.now(timezone.utc).timestamp())
            for k, v in row.items():
                try:
                    fv = float(v)
                except Exception:
                    continue
                self.live_data.setdefault(k, deque(maxlen=MAX_POINTS)).append(fv)

        def worker() -> None:
            try:
                self.root.after(0, lambda: self._set_controller_status('yellow', f'Controller status: connecting ({display_mode} run)'))
                paths = engine.run(run_cfg, legacy_power_policy=LegacyPowerPolicy.ALLOW_ZERO_POWER.value, event_callback=on_event, row_callback=on_row)
                if getattr(engine.state, 'value', str(engine.state)) == 'ERROR':
                    self.root.after(0, lambda: self._finish_run_progress('Progress: failed'))
                    self.root.after(0, lambda p=paths.csv_path.name: self._set_controller_status('red', f'Controller status: {display_mode} run ended in ERROR ({p})'))
                else:
                    self.root.after(0, lambda: self._finish_run_progress('Progress: complete'))
                    self.root.after(0, lambda p=paths.csv_path.name: self._set_controller_status('green', f'Controller status: {display_mode} run complete ({p})'))
                    if has_any_tec_request:
                        self.root.after(0, lambda: self._set_tec_connection_status('green', 'TEC: connected (unified run complete)'))
                    if has_any_huber_request:
                        self.root.after(0, lambda: self._set_huber_connection_status('green', 'Huber: connected (unified run complete)'))
            except Exception as exc:
                self.root.after(0, lambda: self._finish_run_progress('Progress: failed'))
                self.root.after(0, lambda e=exc: self._set_controller_status('red', f'Controller status: {display_mode} run failed ({e})'))
                if has_any_tec_request:
                    self.root.after(0, lambda e=exc: self._set_tec_connection_status('red', f'TEC: failed ({e})'))
                if has_any_huber_request:
                    self.root.after(0, lambda e=exc: self._set_huber_connection_status('red', f'Huber: failed ({e})'))
                self.root.after(0, lambda e=exc: messagebox.showerror(f'{display_mode} run failed', str(e)))
            finally:
                self.animating = False
                self.unified_engine = None
        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _schedule_plot_refresh(self) -> None:
        if not self.animating:
            return
        self._redraw_plot()
        self.root.after(500, self._schedule_plot_refresh)

    def _redraw_plot(self) -> None:
        if self.figure is None or self.canvas is None:
            return
        self.figure.clear()
        has_second = bool(self.enable_second_plot.get())
        primary_axis = self.figure.add_subplot(121 if has_second else 111)
        self._draw_series_on_axis(primary_axis, self.selected_cols, 'Live plot')
        if has_second:
            secondary_axis = self.figure.add_subplot(122)
            self._draw_series_on_axis(secondary_axis, self.second_plot_cols, 'Live plot 2')
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _draw_series_on_axis(self, axis, columns: list[str], title: str) -> None:
        axis.clear()
        x = list(self.sample_index)
        plotted_lines = 0
        for col in columns:
            y = list(self.live_data.get(col, []))
            if x and y:
                timestamps = [datetime.fromtimestamp(v, tz=timezone.utc) for v in x[-len(y):]]
                marker_style = dict(marker='o', markersize=3)
                if self.show_live_line.get():
                    axis.plot(timestamps, y, label=col, linewidth=1.0, **marker_style)
                else:
                    axis.plot(timestamps, y, label=col, linestyle='None', **marker_style)
                plotted_lines += 1
        if plotted_lines:
            axis.legend(loc='best')
        axis.set_title(title)
        axis.set_xlabel('Timestamp (UTC)')
        if mdates is not None:
            axis.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        axis.grid(True, which='major', linestyle='--', alpha=0.6)

    def _redraw_requested_input_plot(self) -> None:
        if self.request_axes is None or self.request_canvas is None:
            return
        tec_axis, huber_axis = self.request_axes
        tec_axis.clear()
        huber_axis.clear()
        tec_axis.set_title('Requested input from loaded JSON')
        huber_axis.set_xlabel('Seconds')
        tec_axis.set_ylabel('TEC requested W')
        huber_axis.set_ylabel('Huber requested °C')

        has_tec = bool(self.loaded_schedule_points)
        has_huber = bool(getattr(self, 'loaded_temp_schedule_points', None))

        if self.show_requested_line.get():
            if has_tec:
                x_vals = [x for x, _ in self.loaded_schedule_points]
                y_vals = [y for _, y in self.loaded_schedule_points]
                tec_axis.plot(x_vals, y_vals, color='tab:orange', linewidth=1.2, marker='o', markersize=2.5, label='TEC requested')
                tec_axis.legend(loc='best')
            else:
                tec_axis.text(0.5, 0.5, 'No TEC requests in loaded JSON', transform=tec_axis.transAxes, ha='center', va='center')

            if has_huber:
                tx = [x for x, _ in self.loaded_temp_schedule_points]
                ty = [y for _, y in self.loaded_temp_schedule_points]
                huber_axis.plot(tx, ty, color='tab:blue', linewidth=1.2, marker='o', markersize=2.5, label='Huber requested °C')
                huber_axis.legend(loc='best')
            else:
                huber_axis.text(0.5, 0.5, 'No Huber requests in loaded JSON', transform=huber_axis.transAxes, ha='center', va='center')
        else:
            tec_axis.text(0.5, 0.5, 'Requested input hidden (enabled by checkbox)', transform=tec_axis.transAxes, ha='center', va='center')
            huber_axis.text(0.5, 0.5, 'Requested input hidden (enabled by checkbox)', transform=huber_axis.transAxes, ha='center', va='center')

        tec_axis.grid(True, which='major', linestyle='--', alpha=0.6)
        huber_axis.grid(True, which='major', linestyle='--', alpha=0.6)
        self.request_figure.tight_layout()
        self.request_canvas.draw_idle()

    def _format_run_error(self, exc: Exception) -> str:
        raw_message = str(exc).strip() or exc.__class__.__name__
        details: list[str] = [raw_message]
        m = re.search(r"device\s+(\d+)\s+raised\s+(.+)", raw_message, flags=re.IGNORECASE)
        if m:
            device_id = m.group(1)
            device_error = m.group(2).strip()
            details.append('')
            details.append(f'Controller at address {device_id} rejected a command: {device_error}.')
            details.append('Most common causes:')
            details.append('- Address/channel mismatch (GUI Address/Channel not matching connected hardware).')
            details.append('- Requested setpoint outside controller limits (e.g. voltage/current/temperature).')
            details.append('- Unit mismatch in the loaded JSON schedule or parameter mapping.')
            details.append('')
            details.append('Quick checks:')
            details.append(f"- Confirm Address={self.address.get().strip() or '?'} and Channel={self.channel.get().strip() or '?'} are correct.")
            details.append('- Open the loaded JSON and verify every setpoint is within your controller limits.')
            if self.config_path.get().strip():
                details.append(f"- Loaded config: {self.config_path.get().strip()}")
        return '\n'.join(details)

    def force_stop(self) -> None:
        self.stop_requested = True
        if self.unified_engine is not None:
            self.unified_engine.request_stop()

    def clear_plot(self) -> None:
        self.sample_index.clear()
        self.live_data.clear()
        self._last_sample_ts = None
        self.sample_rate_text.set('Measured acquisition rate: n/a')
        self._redraw_plot()

    def zero_output(self) -> None:
        try:
            logger = LiveLogger(self._build_config())
            session_manager, endpoint = logger._open_session()
            channel_config = type(
                'LiveChannelConfig',
                (),
                {
                    'address': int(self.address.get()),
                    'channel': int(self.channel.get()),
                    'enable_output_value': 1,
                    'disable_output_value': 0,
                    'output_setpoint_parameters': {},
                    'allow_named_voltage_current_fallback': True,
                    'output_stage_input_selection': None,
                },
            )()
            with session_manager as session:
                controller = SafeChannelController(session, channel_config)
                controller.apply_step(
                    CalibrationStep(
                        name='gui_zero_output',
                        power=0.0,
                        dwell_seconds=1,
                        set_voltage=0.0,
                        set_current=0.0,
                        enable_output=False,
                    )
                )
            self._set_controller_status('green', f'Controller status: output forced to zero ({endpoint})')
            self._set_tec_connection_status('green', f'TEC: connected; output forced to zero ({endpoint})')
        except Exception as exc:
            self._set_controller_status('red', f'Controller status: zero-output failed ({exc})')
            self._set_tec_connection_status('red', f'TEC: zero-output failed ({exc})')
            messagebox.showerror('Zero output failed', str(exc))

    @staticmethod
    def _clip_status_text(text: str, max_chars: int = CONNECTION_STATUS_MAX_CHARS) -> str:
        normalized = ' '.join(str(text).split())
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 1].rstrip() + '…'

    @staticmethod
    def _serial_port_choice_rows(port_infos) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        used_labels: set[str] = set()
        for port in port_infos:
            device = str(getattr(port, 'device', '') or '').strip()
            if not device:
                continue
            description = str(getattr(port, 'description', '') or '').strip()
            hwid = str(getattr(port, 'hwid', '') or '').strip()
            vid = getattr(port, 'vid', None)
            pid = getattr(port, 'pid', None)
            serial_number = str(getattr(port, 'serial_number', '') or '').strip()
            vid_pid = f'VID:PID={vid:04X}:{pid:04X}' if vid is not None and pid is not None else ''
            explanation = ', '.join(part for part in (description, vid_pid, serial_number) if part)
            if not explanation and hwid:
                explanation = hwid
            label = f'{device} — {explanation}' if explanation else device
            if len(label) > COM_PORT_CHOICE_WIDTH_CHARS + 12:
                label = label[: COM_PORT_CHOICE_WIDTH_CHARS + 11].rstrip() + '…'
            unique_label = label
            duplicate = 2
            while unique_label in used_labels:
                unique_label = f'{label} ({duplicate})'
                duplicate += 1
            used_labels.add(unique_label)
            rows.append((unique_label, device))
        return rows

    @staticmethod
    def _format_serial_port_choices(port_infos) -> str:
        rows = [label for label, _device in LiveLoggerGui._serial_port_choice_rows(port_infos)]
        return '\n'.join(rows) if rows else 'No serial ports found.'

    @staticmethod
    def _summarize_serial_port_choices(port_infos) -> str:
        rows = LiveLoggerGui._serial_port_choice_rows(port_infos)
        if not rows:
            return 'COM scan: no serial ports found.'
        devices = ', '.join(device for _label, device in rows[:6])
        suffix = f'; +{len(rows) - 6} more' if len(rows) > 6 else ''
        return f'COM scan: found {len(rows)} port(s): {devices}{suffix}. Select one, then click Use for TEC or Use for Huber.'

    def _available_serial_port_infos(self):
        return list(list_ports.comports())

    def scan_serial_ports(self) -> None:
        try:
            port_infos = self._available_serial_port_infos()
            rows = self._serial_port_choice_rows(port_infos)
        except Exception as exc:
            self.available_ports_text.set('COM scan: failed; see Details.')
            messagebox.showerror('Scan COM Ports failed', str(exc))
            return
        self.serial_port_choices = {label: device for label, device in rows}
        values = [label for label, _device in rows]
        self.serial_ports_combobox.configure(values=values)
        if values:
            self.selected_serial_port_choice.set(values[0])
        else:
            self.selected_serial_port_choice.set('')
        self.available_ports_text.set(self._summarize_serial_port_choices(port_infos))

    def apply_selected_serial_port(self, target: str) -> None:
        label = self.selected_serial_port_choice.get().strip()
        port = self.serial_port_choices.get(label)
        if not port:
            messagebox.showinfo('No COM port selected', 'Click Scan COM Ports, then choose a port from the dropdown first.')
            return
        if target == 'tec':
            self.serial_port.set(port)
            self.serial_autodetect.set(0)
            self.available_ports_text.set(f'Selected {port} for TEC. Click Detect TEC to verify the connection.')
        elif target == 'huber':
            self.huber_port.set(port)
            self.available_ports_text.set(f'Selected {port} for Huber. Click Detect Huber to verify the connection.')
        else:
            raise ValueError(f'unknown serial port target: {target}')

    @staticmethod
    def _candidate_tec_addresses(address_text: str) -> list[int]:
        candidates: list[int] = []
        raw_text = str(address_text).strip()
        if raw_text:
            try:
                requested_address = int(raw_text)
            except ValueError:
                requested_address = None
            if requested_address is not None:
                candidates.append(requested_address)
        for address in list(range(1, TEC_ADDRESS_SCAN_LIMIT + 1)) + [0]:
            if address not in candidates:
                candidates.append(address)
        return candidates

    @staticmethod
    def _summarize_identify_errors(errors: list[tuple[int, str]]) -> str | None:
        if not errors:
            return None
        shown = ', '.join(f'{address}: {error}' for address, error in errors[:3])
        suffix = f'; +{len(errors) - 3} more' if len(errors) > 3 else ''
        return f'address scan failed ({shown}{suffix})'

    @staticmethod
    def _probe_tec_controller(logger: LiveLogger, address_text: str) -> tuple[str | None, object | None, str | None]:
        """Open the TEC serial session and scan common controller addresses.

        The standalone TEC-only GUI treats a successful MeCom serial open as a
        successful detection.  Keep that behavior here so a device is still
        recognized when address queries are blocked by unexpected addresses,
        firmware responses, or transient timeouts.
        """
        session_manager, endpoint = logger._open_session()
        detected_address = None
        identify_error = None
        errors: list[tuple[int, str]] = []
        with session_manager as session:
            for address in LiveLoggerGui._candidate_tec_addresses(address_text):
                try:
                    detected_address = session.identify(address=address)
                    identify_error = None
                    break
                except Exception as exc:
                    errors.append((address, str(exc)))
            else:
                identify_error = LiveLoggerGui._summarize_identify_errors(errors)
        return endpoint, detected_address, identify_error

    def detect_controller(self) -> None:
        try:
            self._set_controller_status('yellow', 'Controller status: connecting (detecting TEC)')
            self._set_tec_connection_status('yellow', 'TEC: detecting connection')
            address_text = self.address.get()
            try:
                int(str(address_text).strip())
            except ValueError:
                self.address.set('1')
                try:
                    logger = LiveLogger(self._build_config())
                finally:
                    self.address.set(address_text)
            else:
                logger = LiveLogger(self._build_config())
            endpoint, detected_address, identify_error = self._probe_tec_controller(logger, address_text)
            if endpoint:
                self.serial_port.set(str(endpoint))
                # After a successful port probe, keep using the explicit port so
                # future starts do not depend on fragile autodetection ordering.
                self.serial_autodetect.set(0)
            if detected_address is not None:
                self.address.set(str(detected_address))
                detail = f'{endpoint}, address {detected_address}'
                self._set_controller_status('green', f'Controller status: connected ({detail})')
                self._set_tec_connection_status('green', f'TEC: detected and connection verified ({detail})')
            else:
                warning = f'; address query skipped/failed ({identify_error})' if identify_error else ''
                self._set_controller_status('green', f'Controller status: connected ({endpoint}{warning})')
                self._set_tec_connection_status('green', f'TEC: port detected ({endpoint}); address not verified{warning}')
        except Exception as exc:
            self._set_controller_status('red', f'Controller status: not detected ({exc})')
            self._set_tec_connection_status('red', f'TEC: not detected or connected ({exc})')

    def detect_huber(self) -> None:
        if self.huber_detect_thread and self.huber_detect_thread.is_alive():
            return
        port = self.huber_port.get().strip() or None
        self._set_huber_connection_status('yellow', 'Huber: detecting connection')
        self._set_detect_button_state(self.detect_huber_button, False)

        def worker() -> None:
            adapter = None
            state = 'red'
            status_text = ''
            detected_port = None
            try:
                adapter = HuberWorkflowAdapter(port=port)
                if not adapter.connect():
                    connection = getattr(adapter, '_connection', None)
                    detail = getattr(connection, 'last_error_message', None) or getattr(connection, 'last_error_code', None) or 'connect() returned False'
                    raise RuntimeError(detail)
                connection = getattr(adapter, '_connection', None)
                detected_port = getattr(connection, 'port', None)
                hardware_client_available = bool(HUBER_HARDWARE_CLIENT_AVAILABLE)
                bath_temp = adapter.read_bath_temp()
                setpoint = adapter.read_setpoint()
                detail_parts = []
                if detected_port:
                    detail_parts.append(str(detected_port))
                if bath_temp is not None:
                    detail_parts.append(f'bath {bath_temp:g} °C')
                if setpoint is not None:
                    detail_parts.append(f'setpoint {setpoint:g} °C')
                details = ', '.join(detail_parts) if detail_parts else 'no explicit port'
                if hardware_client_available:
                    state = 'green'
                    status_text = f'Huber: detected and connection verified ({details})'
                else:
                    state = 'yellow'
                    status_text = f'Huber: hardware client unavailable; simulation response only ({details})'
            except Exception as exc:
                status_text = f'Huber: not detected or connected ({exc})'
            finally:
                if adapter is not None:
                    adapter.close()

            def apply_result() -> None:
                if detected_port:
                    self.huber_port.set(str(detected_port))
                self._set_huber_connection_status(state, status_text)
                self._set_detect_button_state(self.detect_huber_button, True)

            self.root.after(0, apply_result)

        self.huber_detect_thread = threading.Thread(target=worker, daemon=True)
        self.huber_detect_thread.start()

    @staticmethod
    def _connection_color(state: str) -> str:
        color_map = {
            'red': 'firebrick',
            'yellow': 'goldenrod',
            'green': 'forest green',
            'gray': 'gray50',
        }
        return color_map.get(state, 'black')

    def _set_controller_status(self, state: str, text: str) -> None:
        # The per-device TEC and Huber connection indicators are the visible
        # controller status displays.  Keep this compatibility hook for older
        # call sites without adding a third, redundant runtime indicator.
        return

    @staticmethod
    def _display_status_text(text: str) -> str:
        normalized = ' '.join(str(text).split())
        if len(normalized) <= CONNECTION_STATUS_MAX_CHARS:
            return normalized
        prefix = normalized.split(' (', 1)[0]
        if prefix and len(prefix) <= CONNECTION_STATUS_MAX_CHARS - 14:
            return f'{prefix} (see Details)'
        return LiveLoggerGui._clip_status_text(normalized)

    @staticmethod
    def _set_detect_button_state(button, enabled: bool) -> None:
        button.configure(state='normal' if enabled else 'disabled')

    def show_tec_connection_details(self) -> None:
        messagebox.showinfo('TEC connection details', self.last_tec_connection_detail)

    def show_huber_connection_details(self) -> None:
        messagebox.showinfo('Huber connection details', self.last_huber_connection_detail)

    def _set_tec_connection_status(self, state: str, text: str) -> None:
        self.last_tec_connection_detail = str(text)
        self.tec_connection_indicator_label.configure(fg=self._connection_color(state))
        self.tec_connection_text.set(self._display_status_text(text))

    def _set_huber_connection_status(self, state: str, text: str) -> None:
        self.last_huber_connection_detail = str(text)
        self.huber_connection_indicator_label.configure(fg=self._connection_color(state))
        self.huber_connection_text.set(self._display_status_text(text))


def main() -> int:
    root = Tk()
    LiveLoggerGui(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
