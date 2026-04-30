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
