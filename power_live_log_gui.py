from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Button, Checkbutton, Entry, Frame, IntVar, Label, Listbox, Scrollbar, StringVar, Tk, filedialog, messagebox

from workflows.automation.common.live_logger import LiveLogger, LiveLoggerConfig, default_live_parameters

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

        self.last_output_csv: Path | None = None
        self.run_thread: threading.Thread | None = None
        self.live_data: dict[str, deque[float]] = {}
        self.sample_index = deque(maxlen=MAX_POINTS)
        self.selected_cols: list[str] = []
        self.loaded_schedule_points: list[tuple[float, float]] = []
        self.animating = False
        self.stop_requested = False
        self.status_text = StringVar(value='Controller status: unknown')

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
        add_row('Hz', self.hz, 5)
        add_row('Duration Seconds (blank=run forever)', self.duration, 6)
        Button(conn_frame, text='Detect TEC', command=self.detect_controller).grid(row=7, column=1, sticky='w')
        Label(io_frame, text='Output Directory').grid(row=3, column=0, sticky='w')
        Entry(io_frame, textvariable=self.output_directory, width=42).grid(row=3, column=1, columnspan=4, sticky='we')
        Label(io_frame, text='Output Prefix').grid(row=4, column=0, sticky='w')
        Entry(io_frame, textvariable=self.output_prefix, width=42).grid(row=4, column=1, columnspan=4, sticky='we')

        Label(top, textvariable=self.status_text).grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 0))
        conn_frame.grid_columnconfigure(1, weight=1)
        io_frame.grid_columnconfigure(1, weight=1)

        buttons = Frame(self.root, padx=8, pady=4)
        buttons.pack(fill=BOTH)
        Button(buttons, text='Start Logging', command=self.start_logging).pack(side=LEFT, padx=(0, 6))
        Button(buttons, text='Force Stop', command=self.force_stop).pack(side=LEFT, padx=(0, 6))
        Button(buttons, text='Select Columns for Live Plot', command=self.apply_plot_selection).pack(side=LEFT)

        mid = Frame(self.root, padx=8, pady=4)
        mid.pack(fill=BOTH, expand=True)
        Label(mid, text='Columns to plot').pack(anchor='w')
        scroller = Scrollbar(mid, orient=VERTICAL)
        self.columns_list = Listbox(mid, selectmode='extended', yscrollcommand=scroller.set, height=6)
        scroller.config(command=self.columns_list.yview)
        self.columns_list.pack(side=LEFT, fill=BOTH, expand=True)
        scroller.pack(side=RIGHT, fill='y')

        self.plot_frame = Frame(self.root)
        self.plot_frame.pack(fill=BOTH, expand=True)
        self.canvas = None
        self.figure = None
        self.axis = None
        self.request_axis = None
        if Figure is not None:
            self.figure = Figure(figsize=(8, 6), dpi=100)
            self.axis = self.figure.add_subplot(211)
            self.request_axis = self.figure.add_subplot(212)
            self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_frame)
            self.canvas.get_tk_widget().pack(fill=BOTH, expand=True)
            self.axis.set_title('Live plot (select columns then start)')
            self.axis.set_xlabel('Timestamp (UTC)')
            self.axis.grid(True, which='major', linestyle='--', alpha=0.6)
            self.request_axis.set_title('Requested input from loaded JSON')
            self.request_axis.set_xlabel('Seconds')
            self.request_axis.set_ylabel('Set voltage')
            self.request_axis.grid(True, which='major', linestyle='--', alpha=0.6)
            self.canvas.draw_idle()

    def browse_config(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[('JSON files', '*.json'), ('All files', '*.*')])
        if selected:
            self.config_path.set(selected)

    def _build_config(self) -> LiveLoggerConfig:
        duration = float(self.duration.get()) if self.duration.get().strip() else None
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
        total_duration = 0.0
        try:
            content = json.loads(Path(path_text).read_text(encoding='utf-8'))
            schedule = content.get('power_schedule', [])
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
        self.selected_cols = [self.columns_list.get(i) for i in self.columns_list.curselection()]
        if not self.selected_cols:
            messagebox.showwarning('No columns', 'Select one or more columns.')
            return
        self.live_data = {name: deque(maxlen=MAX_POINTS) for name in self.selected_cols}
        self.sample_index = deque(maxlen=MAX_POINTS)
        self._redraw_plot()

    def start_logging(self) -> None:
        if Figure is None:
            messagebox.showwarning('Missing matplotlib', 'Install matplotlib for required live plotting support.')
            return
        if self.run_thread and self.run_thread.is_alive():
            messagebox.showwarning('Busy', 'Logger is already running.')
            return

        self.stop_requested = False
        cfg = self._build_config()
        self.columns_list.delete(0, END)
        for spec in cfg.parameters:
            self.columns_list.insert(END, spec.label)

        if not self.selected_cols:
            self.selected_cols = [cfg.parameters[0].label]
            self.live_data = {self.selected_cols[0]: deque(maxlen=MAX_POINTS)}
        self.sample_index = deque(maxlen=MAX_POINTS)
        for col in self.selected_cols:
            self.live_data[col] = deque(maxlen=MAX_POINTS)

        self.animating = True
        self._schedule_plot_refresh()

        def on_started(path: Path) -> None:
            self.last_output_csv = path

        def on_row(row: dict[str, object]) -> None:
            t = row.get('OLE Automation Date')
            if isinstance(t, (float, int)):
                unix_ts = (float(t) - 25569.0) * 86400.0
                self.sample_index.append(unix_ts)
            else:
                self.sample_index.append(datetime.now(timezone.utc).timestamp())
            for col in self.selected_cols:
                try:
                    val = float(row.get(col, 'nan'))
                except Exception:
                    val = float('nan')
                self.live_data.setdefault(col, deque(maxlen=MAX_POINTS)).append(val)

        def worker() -> None:
            try:
                LiveLogger(cfg).run(
                    hz=float(self.hz.get()),
                    duration_seconds=cfg.duration_seconds,
                    started_callback=on_started,
                    row_callback=on_row,
                    stop_requested=lambda: self.stop_requested,
                )
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror('Run failed', str(exc)))
            finally:
                self.animating = False

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    def _schedule_plot_refresh(self) -> None:
        if not self.animating:
            return
        self._redraw_plot()
        self.root.after(500, self._schedule_plot_refresh)

    def _redraw_plot(self) -> None:
        if self.axis is None or self.canvas is None:
            return
        self.axis.clear()
        if self.selected_cols:
            x = list(self.sample_index)
            plotted_lines = 0
            for col in self.selected_cols:
                y = list(self.live_data.get(col, []))
                if x and y:
                    self.axis.plot([datetime.fromtimestamp(v, tz=timezone.utc) for v in x[-len(y):]], y, label=col)
                    plotted_lines += 1
            if plotted_lines:
                self.axis.legend(loc='best')
        self.axis.set_title('Live plot')
        self.axis.set_xlabel('Timestamp (UTC)')
        if mdates is not None:
            self.axis.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.axis.grid(True, which='major', linestyle='--', alpha=0.6)
        self.canvas.draw_idle()

    def _redraw_requested_input_plot(self) -> None:
        if self.request_axis is None or self.canvas is None:
            return
        self.request_axis.clear()
        if self.loaded_schedule_points:
            x_vals = [x for x, _ in self.loaded_schedule_points]
            y_vals = [y for _, y in self.loaded_schedule_points]
            self.request_axis.plot(x_vals, y_vals, color='tab:orange', linewidth=1.5)
            self.request_axis.set_title('Requested input from loaded JSON')
        else:
            self.request_axis.set_title('Requested input from loaded JSON (no power_schedule)')
        self.request_axis.set_xlabel('Seconds')
        self.request_axis.set_ylabel('Set voltage')
        self.request_axis.grid(True, which='major', linestyle='--', alpha=0.6)
        self.canvas.draw_idle()

    def force_stop(self) -> None:
        self.stop_requested = True

    def detect_controller(self) -> None:
        try:
            logger = LiveLogger(self._build_config())
            _, endpoint = logger._open_session()
            self.status_text.set(f'Controller status: connected ({endpoint})')
        except Exception as exc:
            self.status_text.set(f'Controller status: not detected ({exc})')


def main() -> int:
    root = Tk()
    LiveLoggerGui(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
