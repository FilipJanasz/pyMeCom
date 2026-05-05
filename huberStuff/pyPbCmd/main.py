# -*- coding: utf-8 -*-
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Label, RichLog, Checkbox, Button
from textual.reactive import reactive
from textual.screen import ModalScreen
import asyncio
from datetime import datetime
from typing import Optional
import csv
import os
from pathlib import Path
import serial

try:
    from huber_thermostat import (
        HuberThermostatI,
        HuberThermostatTools,
        TemperatureVar,
        HUBER_DEFAULT_BAUDRATE,
        HUBER_DEFAULT_TIMEOUT,
    )
    HUBER_AVAILABLE = True
except ImportError:
    HUBER_AVAILABLE = False
    print("Warning: huber_thermostat not available, using simulation mode")

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not available, plotting disabled")


class ThermostatConnection:
    def __init__(self, port: str = None, debug: bool = False):
        self.port = port
        self.debug = debug
        self.serial_conn = None
        self.thermostat = None
        self._mock_temp = 20.0
        self._mock_setpoint = 25.0
        
    def connect(self) -> bool:
        if not HUBER_AVAILABLE:
            return True
            
        try:
            if not self.port:
                self.port = HuberThermostatTools.auto_detect_huber_port(debug=self.debug)
            if not self.port:
                return False
                
            self.serial_conn = serial.Serial(
                self.port,
                baudrate=HUBER_DEFAULT_BAUDRATE,
                timeout=HUBER_DEFAULT_TIMEOUT
            )
            self.thermostat = HuberThermostatI(self.serial_conn, debug=self.debug)
            return self.thermostat.ping()
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    def read_temperature(self) -> Optional[float]:
        if not HUBER_AVAILABLE or not self.thermostat:
            self._mock_temp += (self._mock_setpoint - self._mock_temp) * 0.05
            return round(self._mock_temp, 2)
        try:
            return self.thermostat.read_bath_temperature()
        except Exception:
            return None
    
    def read_setpoint(self) -> Optional[float]:
        if not HUBER_AVAILABLE or not self.thermostat:
            return self._mock_setpoint
        try:
            return self.thermostat.read_setpoint()
        except Exception:
            return None
    
    def set_setpoint(self, value: float) -> bool:
        if not HUBER_AVAILABLE or not self.thermostat:
            self._mock_setpoint = value
            return True
        try:
            return self.thermostat.set_setpoint(value)
        except Exception:
            return False
    
    def set_thermoregulation(self, state: bool) -> bool:
        if not HUBER_AVAILABLE or not self.thermostat:
            return True
        try:
            return self.thermostat.set_thermoregulation(state)
        except Exception:
            return False
    
    def close(self):
        if self.serial_conn:
            self.serial_conn.close()


class TemperaturePanel(Static):
    temperature = reactive("–.– °C")
    countdown = reactive(5)
    update_interval = reactive(5)
    
    def compose(self) -> ComposeResult:
        yield Label(id="temp_value")
        yield Label(id="temp_countdown")
    
    def on_mount(self) -> None:
        self.border_title = "Temperature"
        self.update_display()
        self.set_interval(1, self.tick)
        self.run_worker(self.update_temperature_loop(), exclusive=False)
    
    def tick(self) -> None:
        if self.countdown > 0:
            self.countdown -= 1
        if self.countdown == 0:
            self.countdown = self.update_interval
        self.update_display()
    
    def update_display(self) -> None:
        self.query_one("#temp_value", Label).update(f"[bold cyan]{self.temperature}[/]")
        self.query_one("#temp_countdown", Label).update(f"[dim]{self.countdown}[/]")
    
    async def update_temperature_loop(self) -> None:
        while True:
            await asyncio.sleep(self.update_interval)
            try:
                temp = await asyncio.to_thread(self.app.thermostat.read_temperature)
                if temp is not None:
                    self.temperature = f"{temp:.2f} °C"
                self.countdown = self.update_interval
            except Exception as e:
                print(f"Temperature update error: {e}")
    
    def watch_update_interval(self, new_value: int) -> None:
        self.countdown = new_value
    
    async def on_click(self, event) -> None:
        await self.app.push_screen(TemperatureIntervalModal(self))


class SetpointPanel(Static):
    setpoint = reactive("–.– °C")
    countdown = reactive(5)
    update_interval = reactive(5)
    
    def compose(self) -> ComposeResult:
        yield Label(id="sp_value")
        yield Label(id="sp_countdown")
    
    def on_mount(self) -> None:
        self.border_title = "Setpoint"
        self.update_display()
        self.set_interval(1, self.tick)
        self.run_worker(self.update_setpoint_loop(), exclusive=False)
    
    def tick(self) -> None:
        if self.countdown > 0:
            self.countdown -= 1
        if self.countdown == 0:
            self.countdown = self.update_interval
        self.update_display()
    
    def update_display(self) -> None:
        self.query_one("#sp_value", Label).update(f"[bold yellow]{self.setpoint}[/]")
        self.query_one("#sp_countdown", Label).update(f"[dim]{self.countdown}[/]")
    
    async def update_setpoint_loop(self) -> None:
        while True:
            await asyncio.sleep(self.update_interval)
            try:
                sp = await asyncio.to_thread(self.app.thermostat.read_setpoint)
                if sp is not None:
                    self.setpoint = f"{sp:.2f} °C"
                self.countdown = self.update_interval
            except Exception as e:
                print(f"Setpoint update error: {e}")
    
    def watch_update_interval(self, new_value: int) -> None:
        self.countdown = new_value
    
    async def on_click(self, event) -> None:
        await self.app.push_screen(SetpointModal(self))


class LoggerPanel(Static):
    is_logging = reactive(False)
    countdown = reactive(0)
    points_count = reactive(0)
    
    def compose(self) -> ComposeResult:
        yield Label(id="logger_status")
        yield Label(id="logger_graph")
        yield Label(id="logger_countdown")
    
    def on_mount(self) -> None:
        self.border_title = "Logger"
        self.update_display()
        self.set_interval(1, self.tick)
    
    def tick(self) -> None:
        if self.is_logging and self.countdown > 0:
            self.countdown -= 1
        self.update_display()
    
    def update_display(self) -> None:
        status = "[green]●[/] ON" if self.is_logging else "[red]●[/] OFF"
        self.query_one("#logger_status", Label).update(status)
        
        if self.points_count > 0:
            graph = "▁▂▃▅▆▇█" * (min(self.points_count, 10) // 2)
        else:
            graph = "─────"
        self.query_one("#logger_graph", Label).update(f"[dim]{graph[:10]}[/]")
        
        countdown_text = f"[dim]{self.countdown}s[/]" if self.is_logging else "[dim]─[/]"
        self.query_one("#logger_countdown", Label).update(countdown_text)
    
    async def on_click(self, event) -> None:
        await self.app.push_screen(LoggerConfigModal(self))


class TemperatureIntervalModal(ModalScreen):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
    
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Temperature Update Interval", classes="dialog_title")
            yield Label("Update interval (seconds):", classes="dialog_label")
            yield Input(
                value=str(self.panel.update_interval),
                placeholder="e.g. 5",
                id="interval_input"
            )
            with Horizontal(classes="button_row"):
                yield Button("Save", variant="primary", id="save_btn")
                yield Button("Cancel", variant="default", id="cancel_btn")
    
    def on_mount(self) -> None:
        self.query_one("#interval_input", Input).focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_btn":
            try:
                new_val = int(self.query_one("#interval_input", Input).value)
                if new_val > 0:
                    self.panel.update_interval = new_val
                    self.panel.countdown = new_val
            except ValueError:
                pass
            self.app.pop_screen()
        elif event.button.id == "cancel_btn":
            self.app.pop_screen()
    
    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()


class SetpointModal(ModalScreen):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
    
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Setpoint Configuration", classes="dialog_title")
            yield Label("New setpoint value (°C):", classes="dialog_label")
            yield Input(placeholder="e.g. 25.5", id="setpoint_input")
            yield Label("Update interval (seconds):", classes="dialog_label")
            yield Input(
                value=str(self.panel.update_interval),
                placeholder="e.g. 5",
                id="interval_input"
            )
            with Horizontal(classes="button_row"):
                yield Button("Save", variant="primary", id="save_btn")
                yield Button("Cancel", variant="default", id="cancel_btn")
    
    def on_mount(self) -> None:
        self.query_one("#setpoint_input", Input).focus()
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_btn":
            await self.apply_settings()
        elif event.button.id == "cancel_btn":
            self.app.pop_screen()
    
    async def apply_settings(self) -> None:
        sp_value = self.query_one("#setpoint_input", Input).value
        int_value = self.query_one("#interval_input", Input).value
        
        if sp_value:
            try:
                new_sp = float(sp_value)
                success = await asyncio.to_thread(self.app.thermostat.set_setpoint, new_sp)
                if success:
                    self.panel.setpoint = f"{new_sp:.2f} °C"
            except ValueError:
                pass
        
        if int_value:
            try:
                new_int = int(int_value)
                if new_int > 0:
                    self.panel.update_interval = new_int
                    self.panel.countdown = new_int
            except ValueError:
                pass
        
        self.app.pop_screen()
    
    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()


class LoggerConfigModal(ModalScreen):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
    
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog_large"):
            yield Static("Data Logger Configuration", classes="dialog_title")
            
            yield Label("Status:", classes="dialog_label")
            yield Checkbox("Enable logging", id="enable_logging", value=self.panel.is_logging)
            
            yield Label("Filename:", classes="dialog_label")
            yield Input(
                value=self.app.logger_config.get("filename", "temperature_log.csv"),
                placeholder="e.g. temperature_log.csv",
                id="filename_input"
            )
            
            yield Label("Logging interval (seconds):", classes="dialog_label")
            yield Input(
                value=str(self.app.logger_config.get("interval", 10)),
                placeholder="e.g. 10",
                id="log_interval_input"
            )
            
            yield Label("Retry attempts:", classes="dialog_label")
            yield Input(
                value=str(self.app.logger_config.get("retries", 3)),
                placeholder="e.g. 3",
                id="retries_input"
            )
            yield Label("[dim]Note: Data acquisition is not guaranteed on first attempt[/]", classes="dialog_note")
            
            yield Label("Retry delay (seconds):", classes="dialog_label")
            yield Input(
                value=str(self.app.logger_config.get("retry_delay", 1)),
                placeholder="e.g. 1",
                id="retry_delay_input"
            )
            
            yield Checkbox("Log setpoint", id="log_setpoint", value=self.app.logger_config.get("log_setpoint", False))
            
            yield Label("", classes="dialog_spacer")
            with Horizontal(classes="button_row"):
                yield Button("Apply", variant="primary", id="apply_btn")
                yield Button("Cancel", variant="default", id="cancel_btn")
    
    def on_mount(self) -> None:
        self.query_one("#filename_input", Input).focus()
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply_btn":
            await self.apply_settings()
        elif event.button.id == "cancel_btn":
            self.app.pop_screen()
    
    async def apply_settings(self) -> None:
        config = {}
        config["enabled"] = self.query_one("#enable_logging", Checkbox).value
        config["filename"] = self.query_one("#filename_input", Input).value
        config["log_setpoint"] = self.query_one("#log_setpoint", Checkbox).value
        
        try:
            config["interval"] = int(self.query_one("#log_interval_input", Input).value)
        except ValueError:
            config["interval"] = 10
        
        try:
            config["retries"] = int(self.query_one("#retries_input", Input).value)
        except ValueError:
            config["retries"] = 3
        
        try:
            config["retry_delay"] = float(self.query_one("#retry_delay_input", Input).value)
        except ValueError:
            config["retry_delay"] = 1.0
        
        self.app.logger_config.update(config)
        
        if config["enabled"] and not self.panel.is_logging:
            await self.app.start_logging()
        elif not config["enabled"] and self.panel.is_logging:
            await self.app.stop_logging()
        
        self.app.pop_screen()
    
    def on_key(self, event) -> None:
        if event.key == "escape":
            self.app.pop_screen()


class ConsoleApp(App):
    # Textual configuration for Windows compatibility
    ENABLE_COMMAND_PALETTE = False
    def __init__(self):
        super().__init__()
        self.thermostat = ThermostatConnection()
        self.command_history = []
        self.history_index = -1
        self.logger_config = {
            "enabled": False,
            "filename": "temperature_log.csv",
            "interval": 10,
            "retries": 3,
            "retry_delay": 1.0,
            "log_setpoint": False
        }
        self.logger_task = None
        print("[__init__] ConsoleApp initialized", file=sys.stderr, flush=True)

    CSS = """
    Screen {
        layout: horizontal;
    }
    
    #main_container {
        width: 1fr;
        layout: vertical;
    }
    
    #input_row {
        height: 3;
        layout: horizontal;
    }
    
    #main_input {
        width: 1fr;
        border: round #444444;
        padding: 0 1;
    }
    
    #temp_panel, #setpoint_panel, #logger_panel {
        width: 16;
        height: 3;
        border: round white;
        padding: 0 1;
        margin-left: 1;
        content-align: center middle;
    }
    
    #temp_panel:hover {
        border: round cyan;
    }
    
    #setpoint_panel:hover {
        border: round yellow;
    }
    
    #logger_panel:hover {
        border: round green;
    }
    
    #temp_value, #sp_value, #temp_countdown, #sp_countdown,
    #logger_status, #logger_graph, #logger_countdown {
        width: 100%;
        text-align: center;
        height: 1;
    }
    
    #suggestions {
        height: auto;
        padding: 0 1;
        color: #888888;
    }
    
    #output {
        height: 1fr;
        border: round #444444;
        margin-top: 1;
    }
    
    #dialog {
        width: 50;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    
    #dialog_large {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    
    .dialog_title {
        text-align: center;
        color: yellow;
        margin-bottom: 1;
    }
    
    .dialog_label {
        margin-top: 1;
        color: cyan;
    }
    
    .dialog_note {
        margin-top: 0;
        margin-bottom: 1;
    }
    
    .dialog_spacer {
        height: 1;
    }
    
    .button_row {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    
    .button_row Button {
        margin: 0 1;
    }
    
    ModalScreen {
        align: center middle;
    }
    """
    
    COMMANDS = {
        "get": ["temp", "setpoint", "status"],
        "set": ["setpoint", "on", "off"],
        "plot": [],
        "ping": [],
        "help": [],
        "clear": [],
        "exit": []
    }
    
    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="main_container"):
                with Horizontal(id="input_row"):
                    yield Input(placeholder="Enter command...", id="main_input")
                    yield TemperaturePanel(id="temp_panel")
                    yield SetpointPanel(id="setpoint_panel")
                    yield LoggerPanel(id="logger_panel")
                yield Label("", id="suggestions")
                yield RichLog(id="output", highlight=True, markup=True)
    
    def on_mount(self) -> None:
        self.query_one("#main_input", Input).focus()
        connected = self.thermostat.connect()
        if connected:
            self.write_output("[green]✓[/] Connected to thermostat")
        else:
            self.write_output("[yellow]⚠[/] Running in simulation mode")
    
    def write_output(self, text: str) -> None:
        output = self.query_one("#output", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S")
        output.write(f"[dim]{timestamp}[/] {text}")
    
    async def start_logging(self) -> None:
        logger_panel = self.query_one("#logger_panel", LoggerPanel)
        logger_panel.is_logging = True
        logger_panel.countdown = self.logger_config["interval"]
        logger_panel.points_count = 0
        
        self.write_output(f"[green]✓[/] Logging started: {self.logger_config['filename']}")
        
        filepath = Path(self.logger_config["filename"])
        if not filepath.exists():
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                headers = ["Timestamp", "Temperature"]
                if self.logger_config["log_setpoint"]:
                    headers.append("Setpoint")
                writer.writerow(headers)
        
        self.logger_task = asyncio.create_task(self.logging_loop())
    
    async def stop_logging(self) -> None:
        logger_panel = self.query_one("#logger_panel", LoggerPanel)
        logger_panel.is_logging = False
        
        if self.logger_task:
            self.logger_task.cancel()
            try:
                await self.logger_task
            except asyncio.CancelledError:
                pass
        
        self.write_output("[yellow]⚠[/] Logging stopped")
    
    async def logging_loop(self) -> None:
        logger_panel = self.query_one("#logger_panel", LoggerPanel)
        
        while True:
            try:
                await asyncio.sleep(self.logger_config["interval"])
                
                temp = None
                setpoint = None
                
                for attempt in range(self.logger_config["retries"]):
                    temp = await asyncio.to_thread(self.thermostat.read_temperature)
                    if temp is not None:
                        break
                    if attempt < self.logger_config["retries"] - 1:
                        await asyncio.sleep(self.logger_config["retry_delay"])
                
                if self.logger_config["log_setpoint"]:
                    for attempt in range(self.logger_config["retries"]):
                        setpoint = await asyncio.to_thread(self.thermostat.read_setpoint)
                        if setpoint is not None:
                            break
                        if attempt < self.logger_config["retries"] - 1:
                            await asyncio.sleep(self.logger_config["retry_delay"])
                
                if temp is not None:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with open(self.logger_config["filename"], 'a', newline='') as f:
                        writer = csv.writer(f)
                        row = [timestamp, f"{temp:.2f}"]
                        if self.logger_config["log_setpoint"] and setpoint is not None:
                            row.append(f"{setpoint:.2f}")
                        writer.writerow(row)
                    
                    logger_panel.points_count += 1
                    logger_panel.countdown = self.logger_config["interval"]
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.write_output(f"[red]Logging error: {e}[/]")
    
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "main_input":
            return
            
        text = event.value
        if not text:
            self.query_one("#suggestions", Label).update("")
            return
        
        parts = text.split()
        suggestions = []
        
        if len(parts) == 1:
            suggestions = [cmd for cmd in self.COMMANDS if cmd.startswith(parts[0])]
        elif len(parts) >= 2 and parts[0] in self.COMMANDS:
            suggestions = [p for p in self.COMMANDS[parts[0]] if p.startswith(parts[-1])]
        
        if suggestions:
            self.query_one("#suggestions", Label).update(
                f"[dim]→ {' | '.join(suggestions)}[/]"
            )
        else:
            self.query_one("#suggestions", Label).update("")
    
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "main_input":
            return
            
        command = event.value.strip()
        if command:
            self.command_history.append(command)
            self.history_index = len(self.command_history)
            await self.execute_command(command)
        
        event.input.value = ""
        self.query_one("#suggestions", Label).update("")
    
    def on_key(self, event) -> None:
        input_field = self.query_one("#main_input", Input)
        if not input_field.has_focus:
            return
        
        if event.key == "up":
            if self.command_history and self.history_index > 0:
                self.history_index -= 1
                input_field.value = self.command_history[self.history_index]
                input_field.cursor_position = len(input_field.value)
                event.prevent_default()
        elif event.key == "down":
            if self.history_index < len(self.command_history) - 1:
                self.history_index += 1
                input_field.value = self.command_history[self.history_index]
                input_field.cursor_position = len(input_field.value)
                event.prevent_default()
            elif self.history_index == len(self.command_history) - 1:
                self.history_index = len(self.command_history)
                input_field.value = ""
                event.prevent_default()
    
    async def execute_command(self, command: str) -> None:
        parts = command.split()
        if not parts:
            return
        
        cmd = parts[0].lower()
        self.write_output(f"[cyan]$[/] {command}")
        
        if cmd == "exit":
            if self.query_one("#logger_panel", LoggerPanel).is_logging:
                await self.stop_logging()
            self.exit()
        
        elif cmd == "clear":
            self.query_one("#output", RichLog).clear()
        
        elif cmd == "help":
            self.write_output("Available commands:")
            self.write_output("  get temp             - Read current temperature")
            self.write_output("  get setpoint         - Read target setpoint")
            self.write_output("  set setpoint <value> - Set target temperature")
            self.write_output("  set on               - Enable thermoregulation")
            self.write_output("  set off              - Disable thermoregulation")
            self.write_output("  plot [filename]      - Generate graph from log file")
            self.write_output("  ping                 - Test connection")
            self.write_output("  clear                - Clear output")
            self.write_output("  exit                 - Exit application")
        
        elif cmd == "ping":
            result = await asyncio.to_thread(self.thermostat.read_temperature)
            if result is not None:
                self.write_output("[green]✓[/] Device responding")
            else:
                self.write_output("[red]✗[/] No response")
        
        elif cmd == "plot":
            filename = parts[1] if len(parts) > 1 else self.logger_config["filename"]
            await self.generate_plot(filename)
        
        elif cmd == "get" and len(parts) >= 2:
            subcmd = parts[1].lower()
            if subcmd == "temp":
                temp = await asyncio.to_thread(self.thermostat.read_temperature)
                if temp is not None:
                    self.write_output(f"Temperature: [cyan]{temp:.2f} °C[/]")
                else:
                    self.write_output("[red]Failed to read temperature[/]")
            
            elif subcmd == "setpoint":
                sp = await asyncio.to_thread(self.thermostat.read_setpoint)
                if sp is not None:
                    self.write_output(f"Setpoint: [yellow]{sp:.2f} °C[/]")
                else:
                    self.write_output("[red]Failed to read setpoint[/]")
        
        elif cmd == "set" and len(parts) >= 2:
            subcmd = parts[1].lower()
            if subcmd == "setpoint" and len(parts) >= 3:
                try:
                    value = float(parts[2])
                    success = await asyncio.to_thread(
                        self.thermostat.set_setpoint, value
                    )
                    if success:
                        self.write_output(f"[green]✓[/] Setpoint set to {value:.2f} °C")
                        sp_panel = self.query_one("#setpoint_panel", SetpointPanel)
                        sp_panel.setpoint = f"{value:.2f} °C"
                    else:
                        self.write_output("[red]Failed to set setpoint[/]")
                except ValueError:
                    self.write_output("[red]Invalid temperature value[/]")
            
            elif subcmd == "on":
                success = await asyncio.to_thread(
                    self.thermostat.set_thermoregulation, True
                )
                if success:
                    self.write_output("[green]✓[/] Thermoregulation enabled")
                else:
                    self.write_output("[red]Failed to enable[/]")
            
            elif subcmd == "off":
                success = await asyncio.to_thread(
                    self.thermostat.set_thermoregulation, False
                )
                if success:
                    self.write_output("[green]✓[/] Thermoregulation disabled")
                else:
                    self.write_output("[red]Failed to disable[/]")
        
        else:
            self.write_output(f"[red]Unknown command: {command}[/]")
            self.write_output("Type 'help' for available commands")
    
    async def generate_plot(self, filename: str) -> None:
        if not MATPLOTLIB_AVAILABLE:
            self.write_output("[red]matplotlib not available - cannot generate plot[/]")
            self.write_output("[yellow]Install with: pip install matplotlib[/]")
            return
        
        try:
            filepath = Path(filename)
            if not filepath.exists():
                self.write_output(f"[red]File not found: {filename}[/]")
                return
            
            timestamps = []
            temperatures = []
            setpoints = []
            
            with open(filepath, 'r') as f:
                reader = csv.reader(f)
                headers = next(reader)
                has_setpoint = len(headers) > 2
                
                for row in reader:
                    if len(row) >= 2:
                        try:
                            timestamps.append(datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
                            temperatures.append(float(row[1]))
                            if has_setpoint and len(row) >= 3:
                                setpoints.append(float(row[2]))
                        except (ValueError, IndexError):
                            continue
            
            if not temperatures:
                self.write_output("[yellow]No data to plot[/]")
                return
            
            plt.figure(figsize=(12, 6))
            plt.plot(timestamps, temperatures, 'b-', label='Temperature', linewidth=2)
            
            if setpoints and len(setpoints) == len(temperatures):
                plt.plot(timestamps, setpoints, 'r--', label='Setpoint', linewidth=2)
            
            plt.xlabel('Time')
            plt.ylabel('Temperature (°C)')
            plt.title(f'Temperature Log - {filename}')
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            output_filename = filepath.stem + "_plot.png"
            plt.savefig(output_filename, dpi=150, bbox_inches='tight')
            plt.close()
            
            self.write_output(f"[green]✓[/] Plot saved: {output_filename}")
            self.write_output(f"Points: {len(temperatures)}")
            self.write_output(f"Min: {min(temperatures):.2f} °C | Max: {max(temperatures):.2f} °C | Avg: {sum(temperatures)/len(temperatures):.2f} °C")
            
        except Exception as e:
            self.write_output(f"[red]Plot error: {e}[/]")
    
    def on_unmount(self) -> None:
        try:
            logger_panel = self.query_one("#logger_panel", LoggerPanel)
            if logger_panel.is_logging:
                asyncio.create_task(self.stop_logging())
        except Exception:
            pass
        finally:
            self.thermostat.close()


if __name__ == "__main__":
    import sys
    import os
    import traceback

    # Отладочный вывод в stderr чтобы избежать перехвата Textual
    print("=" * 50, file=sys.stderr, flush=True)
    print("Starting ConsoleApp...", file=sys.stderr, flush=True)
    print(f"Python: {sys.version}", file=sys.stderr, flush=True)
    print(f"Platform: {sys.platform}", file=sys.stderr, flush=True)
    print(f"CWD: {os.getcwd()}", file=sys.stderr, flush=True)
    print("=" * 50, file=sys.stderr, flush=True)

    try:
        app = ConsoleApp()
        app.run()

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user", file=sys.stderr, flush=True)
        sys.exit(0)

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", file=sys.stderr, flush=True)
        print("\n[TRACEBACK]", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)