from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, VERTICAL, Button, Checkbutton, Entry, Frame, IntVar, Label, Listbox, Scrollbar, StringVar, Tk, filedialog, messagebox

from workflows.automation.common.live_logger import LiveLogger, LiveLoggerConfig, default_live_parameters

try:
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
except Exception:  # matplotlib is optional
    plt = None
    FuncAnimation = None

LAST_CONFIG_PATH = Path('.last_live_logger_gui_config')


class LiveLoggerGui:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title('Live Logger GUI')

        self.config_path = StringVar(value='')
        self.transport = StringVar(value='com')
        self.serial_port = StringVar(value='')
        self.serial_autodetect = IntVar(value=1)
        self.serial_hint = StringVar(value='')
        self.tcp_host = StringVar(value='')
        self.tcp_port = StringVar(value='50000')
        self.address = StringVar(value='1')
        self.channel = StringVar(value='1')
        self.hz = StringVar(value='1.0')
        self.duration = StringVar(value='')
        self.output_directory = StringVar(value='live_logs')
        self.output_prefix = StringVar(value='power_live_log_com')
        self.verbose = IntVar(value=0)

        self.last_output_csv: Path | None = None
        self.run_thread: threading.Thread | None = None
        self._build_ui()
        self._load_last_used_config_if_present()

    def _build_ui(self) -> None:
        top = Frame(self.root)
        top.pack(fill=BOTH, expand=True)

        def add_row(label: str, var, row: int):
            Label(top, text=label).grid(row=row, column=0, sticky='w')
            Entry(top, textvariable=var, width=42).grid(row=row, column=1, sticky='we')

        add_row('Config JSON', self.config_path, 0)
        Button(top, text='Browse', command=self.browse_config).grid(row=0, column=2)
        Button(top, text='Load JSON', command=self.load_config).grid(row=0, column=3)
        Button(top, text='Save JSON', command=self.save_config).grid(row=0, column=4)

        add_row('Transport (com/tcp)', self.transport, 1)
        add_row('Serial Port', self.serial_port, 2)
        Checkbutton(top, text='Serial autodetect', variable=self.serial_autodetect).grid(row=2, column=2, sticky='w')
        add_row('Serial Hint', self.serial_hint, 3)
        add_row('TCP Host', self.tcp_host, 4)
        add_row('TCP Port', self.tcp_port, 5)
        add_row('Address', self.address, 6)
        add_row('Channel', self.channel, 7)
        add_row('Hz', self.hz, 8)
        add_row('Duration Seconds (blank=run forever)', self.duration, 9)
        add_row('Output Directory', self.output_directory, 10)
        add_row('Output Prefix', self.output_prefix, 11)
        Checkbutton(top, text='Verbose logging', variable=self.verbose).grid(row=11, column=2, sticky='w')

        button_row = Frame(self.root)
        button_row.pack(fill=BOTH)
        Button(button_row, text='Start Logging', command=self.start_logging).pack(side=LEFT)
        Button(button_row, text='Plot Last CSV', command=self.plot_last_csv).pack(side=LEFT)

        plot_frame = Frame(self.root)
        plot_frame.pack(fill=BOTH, expand=True)
        Label(plot_frame, text='CSV columns available for plotting').pack(anchor='w')

        scroller = Scrollbar(plot_frame, orient=VERTICAL)
        self.columns_list = Listbox(plot_frame, selectmode='extended', yscrollcommand=scroller.set, height=8)
        scroller.config(command=self.columns_list.yview)
        self.columns_list.pack(side=LEFT, fill=BOTH, expand=True)
        scroller.pack(side=RIGHT, fill='y')

    def browse_config(self) -> None:
        selected = filedialog.askopenfilename(filetypes=[('JSON files', '*.json'), ('All files', '*.*')])
        if selected:
            self.config_path.set(selected)

    def _build_config(self) -> LiveLoggerConfig:
        duration = float(self.duration.get()) if self.duration.get().strip() else None
        cfg = LiveLoggerConfig(
            transport=self.transport.get().strip() or 'com',
            serial_port=self.serial_port.get().strip() or None,
            serial_port_autodetect=bool(self.serial_autodetect.get()),
            serial_port_hint=self.serial_hint.get().strip() or None,
            tcp_host=self.tcp_host.get().strip() or None,
            tcp_port=int(self.tcp_port.get()),
            address=int(self.address.get()),
            channel=int(self.channel.get()),
            output_directory=self.output_directory.get().strip() or 'live_logs',
            output_prefix=self.output_prefix.get().strip() or 'power_live_log_com',
            parameters=default_live_parameters(channel=int(self.channel.get())),
            duration_seconds=duration,
        )
        return cfg

    def load_config(self) -> None:
        path_text = self.config_path.get().strip()
        if not path_text:
            messagebox.showerror('Error', 'Select config JSON first.')
            return
        cfg = LiveLoggerConfig.from_json_file(path_text)
        self.transport.set(cfg.transport)
        self.serial_port.set(cfg.serial_port or '')
        self.serial_autodetect.set(1 if cfg.serial_port_autodetect else 0)
        self.serial_hint.set(cfg.serial_port_hint or '')
        self.tcp_host.set(cfg.tcp_host or '')
        self.tcp_port.set(str(cfg.tcp_port))
        self.address.set(str(cfg.address))
        self.channel.set(str(cfg.channel))
        self.duration.set('' if cfg.duration_seconds is None else str(cfg.duration_seconds))
        self.output_directory.set(cfg.output_directory)
        self.output_prefix.set(cfg.output_prefix)
        self._remember_last_config_path(path_text)
        messagebox.showinfo('Loaded', f'Loaded {path_text}')

    def save_config(self) -> None:
        path_text = self.config_path.get().strip()
        if not path_text:
            path_text = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
            if not path_text:
                return
            self.config_path.set(path_text)
        cfg = self._build_config()
        payload = asdict(cfg)
        with open(path_text, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2)
            handle.write('\n')
        self._remember_last_config_path(path_text)
        messagebox.showinfo('Saved', f'Saved {path_text}')

    def _remember_last_config_path(self, path_text: str) -> None:
        LAST_CONFIG_PATH.write_text(path_text + '\n', encoding='utf-8')

    def _load_last_used_config_if_present(self) -> None:
        if not LAST_CONFIG_PATH.exists():
            return
        path_text = LAST_CONFIG_PATH.read_text(encoding='utf-8').strip()
        if path_text and Path(path_text).exists():
            self.config_path.set(path_text)
            try:
                self.load_config()
            except Exception:
                pass

    def start_logging(self) -> None:
        if self.run_thread and self.run_thread.is_alive():
            messagebox.showwarning('Busy', 'Logger is already running.')
            return

        def run_logger():
            try:
                cfg = self._build_config()
                logger = LiveLogger(cfg)
                output = logger.run(hz=float(self.hz.get()), duration_seconds=cfg.duration_seconds)
                self.last_output_csv = output
                self.root.after(0, lambda: self._populate_columns(output))
                self.root.after(0, lambda: messagebox.showinfo('Done', f'Logging complete:\n{output}'))
            except Exception as exc:
                self.root.after(0, lambda: messagebox.showerror('Run failed', str(exc)))

        self.run_thread = threading.Thread(target=run_logger, daemon=True)
        self.run_thread.start()
        messagebox.showinfo('Started', 'Live logging started in background thread.')

    def _populate_columns(self, csv_path: Path) -> None:
        import csv

        with open(csv_path, 'r', encoding='utf-8', newline='') as handle:
            reader = csv.reader(handle)
            header = next(reader)
        self.columns_list.delete(0, END)
        for name in header:
            if name not in ('Time', 'Milliseconds', 'OLE Automation Date'):
                self.columns_list.insert(END, name)

    def plot_last_csv(self) -> None:
        if plt is None or FuncAnimation is None:
            messagebox.showwarning('Matplotlib missing', 'matplotlib is not installed, plotting is unavailable.')
            return
        if not self.last_output_csv or not self.last_output_csv.exists():
            messagebox.showwarning('No data', 'Run logger first to create a CSV, then plot.')
            return

        selected = [self.columns_list.get(i) for i in self.columns_list.curselection()]
        if not selected:
            messagebox.showwarning('No columns', 'Select one or more columns to plot.')
            return

        fig, ax = plt.subplots()

        def animate(_frame):
            import csv

            xs = []
            ys = {c: [] for c in selected}
            with open(self.last_output_csv, 'r', encoding='utf-8', newline='') as handle:
                reader = csv.DictReader(handle)
                for i, row in enumerate(reader):
                    xs.append(i)
                    for col in selected:
                        try:
                            ys[col].append(float(row[col]))
                        except Exception:
                            ys[col].append(float('nan'))
            ax.clear()
            for col in selected:
                ax.plot(xs, ys[col], label=col)
            ax.set_title(str(self.last_output_csv))
            ax.set_xlabel('Sample Index')
            ax.legend(loc='best')

        FuncAnimation(fig, animate, interval=1000)
        plt.show()


def main() -> int:
    root = Tk()
    app = LiveLoggerGui(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
