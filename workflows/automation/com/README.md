# COM (serial) workflow snapshot

This folder preserves serial-port based files and templates.
It does not modify the existing root-level COM flow.

Current serial runtime path in code:

- `MeComSerial` transport in `mecom/mecom.py`
- calibration runner opening serial in `mecom/calibration.py`

Use this folder to keep COM-specific configs and wrappers stable while TCP work progresses separately.

## Live COM logging (Windows)

Use the new continuous logger with a COM config that selects only the channels you need.
The logger lives under the shared automation tree (`workflows/automation/common/live_logger.py`), supports
`transport: "com"` and `transport: "tcp"` by config choice, can auto-detect the first connected COM port,
and can execute a power schedule while logging.

```powershell
python power_live_log_com.py --config examples/power_live_log_com.example.json --hz 1 --verbose
```

Optional bounded capture:

```powershell
python power_live_log_com.py --config examples/power_live_log_com.example.json --hz 1 --duration-seconds 600
```

Quick direct COM smoke test wrapper (no JSON file required):

```powershell
python power_live_log_test_com.py --serial-port COM3 --hz 1 --duration-seconds 120 --verbose
```

## Troubleshooting `timeout while communication via serial`

If logs repeatedly show `Read failed ... timeout while communication via serial`, the script can open a COM
port but the controller is not returning valid MeCom responses.

Check the following in order:

1. **Pin the correct COM port (disable auto-detect).**
   - Auto-detect picks the first available serial device, which can be the wrong adapter.
   - Set `"serial_port": "COMx"` in your JSON config to the exact port shown in Device Manager.
   - If you want to keep auto-detect, set `"serial_port_hint"` (for example `"Silicon Labs"` or `"USB Serial"`),
     so auto-detect prefers ports whose device/description/manufacturer/HWID text matches that hint.
2. **Validate serial framing against your controller setup.**
   - Confirm baud rate, parity, stop bits, and timeout values in config match your controller configuration.
   - A wrong baud/parity commonly produces open-port + read-timeout behavior.
3. **Ensure no competing process owns the port.**
   - Close terminal apps, vendor tools, or other Python sessions using the same COM device.
4. **Try the direct smoke wrapper with explicit port.**
   - Run `python power_live_log_test_com.py --serial-port COMx --hz 1 --duration-seconds 30 --verbose`.
   - If this fails the same way, the issue is almost certainly COM wiring/port settings/device state.
5. **Address optional write warnings separately.**
   - `No writable output setpoint parameter is configured...` is a config warning for power-control writes.
   - It does **not** cause telemetry reads to fail; fix it by configuring `output_setpoint_parameters`
     and only enabling `allow_named_voltage_current_fallback` when your device supports those commands.
