from __future__ import annotations

import json
import re
import threading
from collections import deque
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Button, Checkbutton, Entry, Frame, IntVar, Label, Listbox, Scrollbar, StringVar, Tk, filedialog, messagebox

from workflows.automation.common.live_logger import CalibrationStep, LiveLogger, LiveLoggerConfig, PowerScheduleStep, SafeChannelController, default_live_parameters

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


class LiveLoggerGui:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title('Live Logger GUI (COM only)')

        self.config_path = StringVar(value='')
        self.serial_port = StringVar(value='')
        self.serial_autodetect = IntVar(value=1)
        self.serial_hint = StringVar(value='')
        self.address = StringVar(value='1')
        self.channel = StringVar(value='1')
        self.hz = StringVar(value='1.0')
        self.duration = StringVar(value='')
        self.output_directory = StringVar(value='live_logs')
        self.output_prefix = StringVar(value='power_live_log_com')
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
        self.loaded_power_schedule = []
        self.animating = False
        self.stop_requested = False
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

        self.status_indicator_label = Label(top, textvariable=self.status_indicator_text, fg='goldenrod', font=('TkDefaultFont', 12, 'bold'))
        self.status_indicator_label.grid(row=1, column=0, sticky='w', pady=(6, 0))
        Label(top, textvariable=self.status_text).grid(row=1, column=0, columnspan=2, sticky='w', padx=(18, 0), pady=(6, 0))
        Label(top, textvariable=self.sample_rate_text).grid(row=2, column=0, columnspan=2, sticky='w')
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
        self.request_plot_frame.grid(row=6, column=0, columnspan=5, sticky='nsew', pady=(8, 0))
        self.canvas = None
        self.figure = None
        self.axis = None
        self.request_axis = None
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
            self.request_figure = Figure(figsize=(5.5, 1.8), dpi=100)
            self.request_axis = self.request_figure.add_subplot(111)
            self.request_canvas = FigureCanvasTkAgg(self.request_figure, master=self.request_plot_frame)
            self.request_canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.request_axis.set_title('Requested input from loaded JSON')
            self.request_axis.set_xlabel('Seconds')
            self.request_axis.set_ylabel('Set voltage')
            self.request_axis.grid(True, which='major', linestyle='--', alpha=0.6)
            self.canvas.draw_idle()
            self.request_canvas.draw_idle()
        Checkbutton(io_frame, text='Show requested input line', variable=self.show_requested_line, command=self._redraw_requested_input_plot).grid(row=5, column=0, columnspan=2, sticky='w')
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
        )

    def load_config(self) -> None:
        path_text = self.config_path.get().strip()
        if not path_text:
            return
        cfg = LiveLoggerConfig.from_json_file(path_text)
        self.serial_port.set(cfg.serial_port or '')
        self.serial_autodetect.set(1 if cfg.serial_port_autodetect else 0)
        self.serial_hint.set(cfg.serial_port_hint or '')
        self.address.set(str(cfg.address))
        self.channel.set(str(cfg.channel))
        self.duration.set('' if cfg.duration_seconds is None else str(cfg.duration_seconds))
        self.output_directory.set(cfg.output_directory)
        self.output_prefix.set(cfg.output_prefix)
        self._load_requested_input_from_config(path_text)
        self._remember_last_config_path(path_text)

    def _load_requested_input_from_config(self, path_text: str) -> None:
        self.loaded_schedule_points = []
        self.loaded_power_schedule = []
        total_duration = 0.0
        try:
            content = json.loads(Path(path_text).read_text(encoding='utf-8'))
            schedule = content.get('power_schedule', [])
            self.loaded_power_schedule = list(schedule)
            t = 0.0
            for step in schedule:
                duration = float(step.get('duration_seconds', 0.0) or 0.0)
                set_voltage = float(step.get('set_voltage', 0.0) or 0.0)
                self.loaded_schedule_points.append((t, set_voltage))
                t += duration
                self.loaded_schedule_points.append((t, set_voltage))
            total_duration = t
        except Exception:
            self.loaded_schedule_points = []
            total_duration = 0.0
        if total_duration > 0.0:
            self.duration.set(f'{total_duration:g}')
        self._redraw_requested_input_plot()

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
        if self.request_axis is None or self.request_canvas is None:
            return
        self.request_axis.clear()
        if self.loaded_schedule_points:
            x_vals = [x for x, _ in self.loaded_schedule_points]
            y_vals = [y for _, y in self.loaded_schedule_points]
            if self.show_requested_line.get():
                self.request_axis.plot(x_vals, y_vals, color='tab:orange', linewidth=1.2, marker='o', markersize=2.5)
                self.request_axis.set_title('Requested input from loaded JSON')
            else:
                self.request_axis.set_title('Requested input hidden (enabled by checkbox)')
        else:
            self.request_axis.set_title('Requested input from loaded JSON (no power_schedule)')
        self.request_axis.set_xlabel('Seconds')
        self.request_axis.set_ylabel('Set voltage')
        self.request_axis.grid(True, which='major', linestyle='--', alpha=0.6)
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
