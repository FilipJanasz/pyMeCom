from __future__ import annotations

import json
import re
import threading
from collections import deque
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Button, Checkbutton, Entry, Frame, IntVar, Label, Listbox, Radiobutton, Scrollbar, StringVar, Tk, filedialog, messagebox

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
        self.huber_curve_c = StringVar(value='25,30,35,30,25')
        self.voltage_curve_v = StringVar(value='0.5,1.0,1.5,1.0,0.5')
        self.current_curve_a = StringVar(value='0.2,0.2,0.25,0.2,0.2')
        self.step_duration_s = StringVar(value='60')
        self.show_requested_line = IntVar(value=1)
        self.show_live_line = IntVar(value=1)
        self.enable_second_plot = IntVar(value=0)

        self.last_output_csv: Path | None = None
        self.run_thread: threading.Thread | None = None
        self.live_data: dict[str, deque[float]] = {}
        self.sample_index = deque(maxlen=MAX_POINTS)
        self.selected_cols: list[str] = []
        self.second_plot_cols: list[str] = []
        self.loaded_schedule_points: list[tuple[float, float]] = []
        self.loaded_temp_schedule_points: list[tuple[float, float]] = []
        self.loaded_power_schedule = []
        self.animating = False
        self.stop_requested = False
        self.unified_engine: DualDeviceRunEngine | None = None
        self.status_text = StringVar(value='Controller status: unknown')
        self.status_indicator_text = StringVar(value='●')
        self.sample_rate_text = StringVar(value='Measured acquisition rate: n/a')
        self._last_sample_ts: float | None = None

        self._build_ui()
        self._load_last_used_config_if_present()

    def _build_ui(self) -> None:
        top = Frame(self.root, padx=8, pady=8)
        top.pack(fill=BOTH)
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)

        def add_row(label: str, var, row: int):
            Label(conn_frame, text=label).grid(row=row, column=0, sticky='w')
            Entry(conn_frame, textvariable=var, width=42).grid(row=row, column=1, sticky='we')

        conn_frame = Frame(top, padx=4, pady=4, relief='groove', bd=1)
        conn_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 4))
        io_frame = Frame(top, padx=4, pady=4, relief='groove', bd=1)
        io_frame.grid(row=0, column=1, sticky='nsew', padx=(4, 0))

        Label(conn_frame, text='Connection & Runtime', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w')
        Label(io_frame, text='Config & Output', font=('TkDefaultFont', 10, 'bold')).grid(row=0, column=0, columnspan=5, sticky='w')

        Label(io_frame, text='Config JSON').grid(row=1, column=0, sticky='w')
        Entry(io_frame, textvariable=self.config_path, width=44).grid(row=1, column=1, columnspan=4, sticky='we')
        Button(io_frame, text='Browse', command=self.browse_config).grid(row=2, column=1, sticky='w')
        Button(io_frame, text='Load JSON', command=self.load_config).grid(row=2, column=2, sticky='w')
        Button(io_frame, text='Save JSON', command=self.save_config).grid(row=2, column=3, sticky='w')
        Button(io_frame, text='Build Unified Example JSON', command=self.save_unified_example_config).grid(row=2, column=4, sticky='w')

        add_row('Serial Port', self.serial_port, 1)
        Checkbutton(conn_frame, text='Serial autodetect', variable=self.serial_autodetect).grid(row=1, column=2, sticky='w')
        add_row('Serial Hint', self.serial_hint, 2)
        add_row('Address', self.address, 3)
        add_row('Channel', self.channel, 4)
        add_row(f'Hz (min {MIN_HZ:g})', self.hz, 5)
        add_row('Duration Seconds (blank=run forever)', self.duration, 6)
        Button(conn_frame, text='Detect TEC', command=self.detect_controller).grid(row=7, column=1, sticky='w')
        Label(io_frame, text='Output Directory').grid(row=3, column=0, sticky='w')
        Entry(io_frame, textvariable=self.output_directory, width=42).grid(row=3, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='Output Prefix').grid(row=4, column=0, sticky='w')
        Entry(io_frame, textvariable=self.output_prefix, width=42).grid(row=4, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='Huber Port (Unified)').grid(row=5, column=0, sticky='w')
        Entry(io_frame, textvariable=self.huber_port, width=42).grid(row=5, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='Bath Standby °C').grid(row=6, column=0, sticky='w')
        Entry(io_frame, textvariable=self.bath_standby_temp_c, width=16).grid(row=6, column=1, sticky='w')
        Checkbutton(io_frame, text='Pump ON in safe state', variable=self.pump_safe_on).grid(row=6, column=2, sticky='w')
        Label(io_frame, text='(stop/error: keep bath pump running)').grid(row=6, column=3, columnspan=2, sticky='w')
        Label(io_frame, text='Huber Temp Curve °C (comma-separated)').grid(row=7, column=0, sticky='w')
        Entry(io_frame, textvariable=self.huber_curve_c, width=42).grid(row=7, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='TEC Voltage Curve V (comma-separated)').grid(row=8, column=0, sticky='w')
        Entry(io_frame, textvariable=self.voltage_curve_v, width=42).grid(row=8, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='TEC Current Curve A (comma-separated)').grid(row=9, column=0, sticky='w')
        Entry(io_frame, textvariable=self.current_curve_a, width=42).grid(row=9, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='Step Duration Seconds').grid(row=10, column=0, sticky='w')
        Entry(io_frame, textvariable=self.step_duration_s, width=16).grid(row=10, column=1, sticky='w')
        Label(io_frame, text='Build Unified Example JSON saves a starter shared JSON from the Huber temp and TEC V/I curves; it does not start hardware.').grid(row=10, column=2, columnspan=3, sticky='w')

        self.status_indicator_label = Label(top, textvariable=self.status_indicator_text, fg='goldenrod', font=('TkDefaultFont', 12, 'bold'))
        self.status_indicator_label.grid(row=1, column=0, sticky='w', pady=(6, 0))
        Label(top, textvariable=self.status_text).grid(row=1, column=0, columnspan=2, sticky='w', padx=(18, 0), pady=(6, 0))
        Label(top, textvariable=self.sample_rate_text).grid(row=2, column=0, columnspan=2, sticky='w')
        Label(top, text='Run mode:').grid(row=3, column=0, sticky='w')
        Radiobutton(top, text='Auto', variable=self.run_mode_selection, value='Auto').grid(row=3, column=0, sticky='w', padx=(70, 0))
        Radiobutton(top, text='TEC-only', variable=self.run_mode_selection, value='TEC-only').grid(row=3, column=0, sticky='w', padx=(130, 0))
        Radiobutton(top, text='Unified', variable=self.run_mode_selection, value='Unified').grid(row=3, column=0, sticky='w', padx=(220, 0))
        Label(top, text='Detected from JSON:').grid(row=3, column=1, sticky='e', padx=(0, 110))
        Label(top, textvariable=self.detected_mode, font=('TkDefaultFont', 9, 'bold')).grid(row=3, column=1, sticky='e')
        conn_frame.grid_columnconfigure(1, weight=1)
        io_frame.grid_columnconfigure(1, weight=1)

        buttons = Frame(self.root, padx=8, pady=4)
        buttons.pack(fill=BOTH)
        Button(buttons, text='Start Logging', command=self.start_logging).pack(side=LEFT, padx=(0, 6))
        Button(buttons, text='Force Stop', command=self.force_stop).pack(side=LEFT, padx=(0, 6))
        Button(buttons, text='Select Columns for Live Plot', command=self.apply_plot_selection).pack(side=LEFT)
        Button(buttons, text='Clear Plot', command=self.clear_plot).pack(side=LEFT, padx=(6, 0))
        Button(buttons, text='Use selection for Plot 2', command=self.apply_second_plot_selection).pack(side=LEFT, padx=(6, 0))
        Button(buttons, text='Zero TEC Output', command=self.zero_output).pack(side=LEFT, padx=(6, 0))

        mid = Frame(self.root, padx=8, pady=4)
        mid.pack(fill=BOTH, expand=True)
        left_col = Frame(mid)
        left_col.pack(side=LEFT, fill='y', padx=(0, 8))
        Label(left_col, text='Columns to plot').pack(anchor='w')
        scroller = Scrollbar(left_col, orient=VERTICAL)
        self.columns_list = Listbox(left_col, selectmode='extended', yscrollcommand=scroller.set, height=8, width=24, exportselection=False)
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
        self.request_plot_frame.grid(row=11, column=0, columnspan=5, sticky='nsew', pady=(8, 0))
        self.canvas = None
        self.figure = None
        self.axis = None
        self.request_axes = None
        self.request_canvas = None
        self.request_figure = None
        if Figure is not None:
            self.figure = Figure(figsize=(9, 5), dpi=100)
            self.axis = self.figure.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_frame)
            self.canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.axis.set_title('Live plot (select columns then start)')
            self.axis.set_xlabel('Timestamp (UTC)')
            self.axis.grid(True, which='major', linestyle='--', alpha=0.6)
            self.request_figure = Figure(figsize=(5.5, 2.8), dpi=100)
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
        Checkbutton(io_frame, text='Show requested input line', variable=self.show_requested_line, command=self._redraw_requested_input_plot).grid(row=12, column=0, columnspan=2, sticky='w')
        Checkbutton(right_col, text='Show live line (default on)', variable=self.show_live_line, command=self._redraw_plot).pack(anchor='w')
        Checkbutton(right_col, text='Enable second live plot (defaults to diff voltage 1/2)', variable=self.enable_second_plot, command=self._redraw_plot).pack(anchor='w')

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
        return LiveLoggerConfig(
            transport='com',
            serial_port=self.serial_port.get().strip() or None,
            serial_port_autodetect=bool(self.serial_autodetect.get()),
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
        content = json.loads(Path(path_text).read_text(encoding='utf-8'))
        detected_mode = self._detect_mode_from_content(content)
        self.detected_mode.set(detected_mode)
        self.run_mode.set(detected_mode)
        if detected_mode == "Unified":
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
        self._load_requested_input_from_config(path_text)
        self._remember_last_config_path(path_text)

    def _detect_mode_from_content(self, content: dict) -> str:
        if looks_like_unified_run_config(content):
            return "Unified"
        return "TEC-only"

    def _validate_mode_compatibility(self, content: dict, requested_mode: str) -> str | None:
        if requested_mode == "Unified":
            has_shared_or_legacy_shape = (
                looks_like_unified_run_config(content)
                or isinstance(content.get("power_schedule"), list)
                or bool(legacy_tec_steps_to_power_schedule(content))
            )
            if not has_shared_or_legacy_shape:
                return "Unified mode requires shared steps or legacy TEC power_schedule entries."
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
            content = json.loads(Path(path_text).read_text(encoding='utf-8'))
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
                    tec_power_raw = step.get('tec_power_w')
                    bath_temp_raw = step.get('bath_setpoint_c')
                    if tec_power_raw is not None:
                        tec_power = float(tec_power_raw)
                        self.loaded_schedule_points.append((t, tec_power))
                    if bath_temp_raw is not None:
                        bath_temp = float(bath_temp_raw)
                        self.loaded_temp_schedule_points.append((t, bath_temp))
                    t += duration
                    if tec_power_raw is not None:
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
        if total_duration > 0.0:
            self.duration.set(f'{total_duration:g}')
        self._redraw_requested_input_plot()

    def _parse_curve_values(self, text: str, name: str) -> list[float]:
        parts = [p.strip() for p in text.split(',') if p.strip()]
        if not parts:
            raise ValueError(f'{name} is empty')
        return [float(p) for p in parts]

    def save_unified_example_config(self) -> None:
        path_text = self.config_path.get().strip() or filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
        if not path_text:
            return
        self.config_path.set(path_text)
        try:
            temps = self._parse_curve_values(self.huber_curve_c.get(), 'Huber temperature curve')
            volts = self._parse_curve_values(self.voltage_curve_v.get(), 'TEC voltage curve')
            currents = self._parse_curve_values(self.current_curve_a.get(), 'TEC current curve')
            if len(temps) != len(volts) or len(temps) != len(currents):
                raise ValueError('Huber temperature, TEC voltage, and TEC current curves must have the same number of points')
            step_duration = float(self.step_duration_s.get())
            if step_duration <= 0:
                raise ValueError('Step duration must be > 0')
        except ValueError as exc:
            messagebox.showerror('Invalid curve input', str(exc))
            return
        steps = []
        for idx, (temp_c, volt_v, current_a) in enumerate(zip(temps, volts, currents), start=1):
            steps.append(
                {
                    'name': f'curve_step_{idx}',
                    'bath_setpoint_c': temp_c,
                    'tec_power_w': 0.0,
                    'duration_s': step_duration,
                    'progression_mode': 'time',
                    'tec_voltage_v': volt_v,
                    'tec_current_a': current_a,
                }
            )
        payload = {
            'run_name': 'gui_unified_curve_example',
            'steps': steps,
            'safety': {
                'tec_power_w_on_stop': 0.0,
                'bath_standby_setpoint_c': float(self.bath_standby_temp_c.get()),
                'pump_on_in_safe_state': bool(self.pump_safe_on.get()),
            },
        }
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
        if self.run_mode_selection.get() == 'Unified' and not path_text:
            messagebox.showerror('Unified mode requires JSON', 'Select a unified JSON config file before starting Unified mode.')
            return
        if path_text:
            try:
                content = json.loads(Path(path_text).read_text(encoding='utf-8'))
            except Exception:
                content = {}
            selected_mode = self.run_mode_selection.get()
            effective_mode = selected_mode if selected_mode != 'Auto' else self._detect_mode_from_content(content)
            mode_error = self._validate_mode_compatibility(content, effective_mode)
            if mode_error:
                messagebox.showerror('Run mode mismatch', mode_error)
                return
            self.run_mode.set(effective_mode)
            if effective_mode == "Unified":
                self._start_unified_run(path_text, hz)
                return
        cfg = self._build_config()
        self._set_controller_status('yellow', 'Controller status: connecting (starting logger)')
        self.columns_list.delete(0, END)
        for spec in cfg.parameters:
            self.columns_list.insert(END, spec.label)

        if not self.selected_cols:
            default_col = next((spec.label for spec in cfg.parameters if 'act u' in spec.label.lower()), cfg.parameters[0].label)
            self.selected_cols = [default_col]
        if not self.second_plot_cols:
            default_second = [spec.label for spec in cfg.parameters if spec.label.startswith('1046.1:') or spec.label.startswith('1046.2:')]
            self.second_plot_cols = default_second[:2]
        for idx, spec in enumerate(cfg.parameters):
            if spec.label in self.selected_cols:
                self.columns_list.selection_set(idx)
        for col in self.selected_cols + self.second_plot_cols:
            self.live_data.setdefault(col, deque(maxlen=MAX_POINTS))

        self.animating = True
        self._schedule_plot_refresh()

        def on_started(path: Path) -> None:
            self.last_output_csv = path
            self.root.after(0, lambda: self._set_controller_status('green', f'Controller status: connected (logging to {path.name})'))

        def on_row(row: dict[str, object]) -> None:
            t = row.get('OLE Automation Date')
            if isinstance(t, (float, int)):
                unix_ts = (float(t) - 25569.0) * 86400.0
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
            try:
                LiveLogger(cfg).run(
                    hz=hz,
                    duration_seconds=cfg.duration_seconds,
                    started_callback=on_started,
                    row_callback=on_row,
                    stop_requested=lambda: self.stop_requested,
                )
            except Exception as exc:
                error_message = self._format_run_error(exc)
                self.root.after(0, lambda: self._set_controller_status('red', f'Controller status: not detected ({exc})'))
                self.root.after(0, lambda msg=error_message: messagebox.showerror('Run failed', msg))
            finally:
                self.animating = False
                if self.stop_requested:
                    self.root.after(0, lambda: self._set_controller_status('yellow', 'Controller status: stopped by user'))

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _start_unified_run(self, path_text: str, hz: float) -> None:
        self.run_mode.set('Unified')
        self.stop_requested = False
        self.animating = True
        self._schedule_plot_refresh()
        run_cfg = RunConfig.from_json_file(path_text)
        run_cfg.safety.bath_standby_setpoint_c = float(self.bath_standby_temp_c.get())
        run_cfg.safety.pump_on_in_safe_state = bool(self.pump_safe_on.get())
        has_any_tec_request = any(
            step.tec_power_w is not None or step.tec_voltage_v is not None or step.tec_current_a is not None
            for step in run_cfg.steps
        )
        has_any_huber_request = any(step.bath_setpoint_c is not None for step in run_cfg.steps)
        tec_adapter = TecPowerAdapter(self._build_config()) if has_any_tec_request else NoopTecAdapter()
        bath_adapter = HuberWorkflowAdapter(port=self.huber_port.get().strip() or None) if has_any_huber_request else NoopBathAdapter()
        engine = DualDeviceRunEngine(tec_adapter, bath_adapter, output_directory=self.output_directory.get().strip() or 'live_logs', sample_hz=hz)
        self.unified_engine = engine

        def on_event(evt: dict[str, object]) -> None:
            state = str(evt.get("next_state") or evt.get("state") or "")
            self.root.after(0, lambda s=state: self.status_text.set(f'Engine state: {s}'))
            if evt.get("event") == "state_transition" and evt.get("next_state") == "ERROR":
                self.root.after(0, lambda: self._set_controller_status('red', f'Controller status: error ({evt.get("error", "unknown")})'))

        def on_row(row: dict[str, object]) -> None:
            t = row.get('OLE Automation Date')
            if isinstance(t, (float, int)):
                unix_ts = (float(t) - 25569.0) * 86400.0
                self.sample_index.append(unix_ts)
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
                self._set_controller_status('yellow', 'Controller status: connecting (unified run)')
                paths = engine.run(run_cfg, legacy_power_policy=LegacyPowerPolicy.ALLOW_ZERO_POWER.value, event_callback=on_event, row_callback=on_row)
                self.root.after(0, lambda p=paths.csv_path.name: self._set_controller_status('green', f'Controller status: unified run complete ({p})'))
            except Exception as exc:
                self.root.after(0, lambda: self._set_controller_status('red', f'Controller status: unified run failed ({exc})'))
                self.root.after(0, lambda: messagebox.showerror('Unified run failed', str(exc)))
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
        except Exception as exc:
            self._set_controller_status('red', f'Controller status: zero-output failed ({exc})')
            messagebox.showerror('Zero output failed', str(exc))

    def detect_controller(self) -> None:
        try:
            self._set_controller_status('yellow', 'Controller status: connecting (detecting TEC)')
            logger = LiveLogger(self._build_config())
            _, endpoint = logger._open_session()
            self._set_controller_status('green', f'Controller status: connected ({endpoint})')
        except Exception as exc:
            self._set_controller_status('red', f'Controller status: not detected ({exc})')

    def _set_controller_status(self, state: str, text: str) -> None:
        color_map = {
            'red': 'firebrick',
            'yellow': 'goldenrod',
            'green': 'forest green',
        }
        self.status_indicator_label.configure(fg=color_map.get(state, 'black'))
        self.status_text.set(text)


def main() -> int:
    root = Tk()
    LiveLoggerGui(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
