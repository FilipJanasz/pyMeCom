# pyMeCom
A python interface for the MeCom protocol by Meerstetter.
This package was developed to control several TEC devices on a raspberry pi by connecting them via usb or via tcp.

## Requirements
1. this code is only tested in Python 3 running in a linux OS
1. `pySerial` in a version `>= 3.1` https://pypi.python.org/pypi/pyserial

## Installation
1. clone the repository
1. setup a virtualenv in python (you may skip this step)
1. install the package with either pip or setuptools, e.g. `pip install --user .`
1. `python mecom/mecom.py` to see some example output

## Usage
For a basic example look at `mecom/mecom.py`, the `__main__` part contains an example communication.

### TEC1161 calibration workflow

The repository now includes a long-running stepped calibration runner in `mecom/calibration.py`.
It is designed for unattended TEC1161 CH1 calibration runs where you want to:

1. force the output to a known zero state,
2. dwell for a configured time per step,
3. capture structured measurements,
4. move to the next power step,
5. log enough metadata to make the run reproducible later, and
6. drive the output back to zero on completion or failure.

#### What the script does

For each configured step, the runner:

1. applies the configured output settings for the selected channel,
2. waits for the configured dwell time,
3. reads measurement values,
4. appends the measurement record to both JSONL and CSV logs.

Before the stepped sequence starts, it first drives the configured output setpoints to zero.
After the last step finishes, it drives the output back to zero again and disables output.
On a normal Python exception, `SIGINT`, or `SIGTERM`, it also makes a best effort to force the channel back to zero.

#### How to run it

Use the example configuration file as a starting point:

```bash
python -m mecom.calibration --config examples/tec1161_calibration_config.example.json --verbose
```

The `--verbose` flag enables INFO/DEBUG logging to the console so you can monitor a long run.

#### Quick power-cycle test wrapper

If you want a shorter proof-of-execution run that steps through several power outputs and records whether each dwell actually elapsed, use:

```bash
python power_cycle_test_com.py --config examples/power_cycle_test.example.json --verbose
```

This wrapper uses the same logging pipeline and writes metadata, JSONL, and CSV files. Each record includes `step_started_at`, `requested_dwell_seconds`, and `actual_dwell_seconds` so you can verify that the board moved through the requested loop and waited the expected time before measurements were logged.



For TCP transport, use:

```bash
python power_cycle_test_tcp.py --config workflows/automation/tcp/tec1161_calibration_config.tcp.template.json --verbose
```


#### Production-ready template

For production-oriented runs, start from:

- `examples/tec1161_production_config.template.json`

The production template differs from the short power-cycle example by:

- using long dwell defaults (`1800` seconds),
- disabling named voltage/current fallback by default,
- requiring explicit writable output setpoint parameter IDs for power/voltage/current,
- keeping placeholder entries for HR input IDs so unresolved calibration channels are visible.

Recommended rollout:

1. Validate connectivity with a short run in a non-production environment.
2. Fill in confirmed writable output parameter IDs from your validated protocol table.
3. Fill in HR/temperature raw measurement IDs as needed.
4. Run a short staged smoke run with explicit log review.
5. Only then use the 30-minute dwell schedule for unattended production calibration.

#### Configuration file overview

The runner is configured entirely by JSON.
The example file is located at `examples/tec1161_calibration_config.example.json`.

Key top-level fields:

- `serial_port`: serial device path, for example `/dev/ttyUSB0`
- `address`: MeCom device address
- `channel`: MeCom parameter instance / channel; for your use case this should remain `1`
- `timeout`: serial read/write timeout
- `output_directory`: where metadata and logs are written
- `run_name`: optional run label used in output filenames
- `device_label`: label included in metadata and filenames
- `dwell_seconds_default`: default dwell if a step does not override it
- `settle_seconds`: short delay after forcing initial zero output
- `output_stage_input_selection`: optional output-source selection written before each step; leave unset unless you have confirmed your controller accepts the generic command
- `allow_named_voltage_current_fallback`: optional compatibility switch; defaults to `false` because some TEC1161 setups time out on the generic named `Set Voltage` / `Set Current` commands
- `steps`: the calibration table
- `measurement_parameters`: additional measurements, including raw TEC1161 parameters
- `low_resolution_temperature_parameters`: low-resolution temperature inputs to record
- `output_setpoint_parameters`: optional explicit raw/named output-control parameters if a confirmed power parameter is available
- `raw_parameter_placeholders`: documentation-only placeholders so unresolved IDs are visible in the run metadata

#### Step table

Each entry in `steps` may contain:

- `name`: human-readable step name
- `power`: logical target power value for that step
- `dwell_seconds`: dwell duration for that step
- `set_voltage`: optional voltage setpoint
- `set_current`: optional current setpoint
- `enable_output`: optional boolean; defaults to `true`
- `metadata`: arbitrary step metadata that will be copied into the log record

The script does not assume that the TEC1161 power command is already known.
If you configure `output_setpoint_parameters.power`, the runner writes that parameter directly.

If you instead configure `output_setpoint_parameters.voltage` and/or `output_setpoint_parameters.current`, the runner writes those explicit parameters.

By default it does **not** write `output_stage_input_selection`, and it also does **not** fall back to the generic named MeCom commands `Set Voltage` and `Set Current`, because some TEC1161 setups do not respond to those generic commands and will time out over serial. If your controller is known to support them, you can opt in explicitly by setting `output_stage_input_selection` to a concrete value and/or `allow_named_voltage_current_fallback: true`.

#### Does it store HR Input 1 and HR Input 2 differential voltage?

**Yes, it is designed to store them.**

More precisely:

- The measurement record always includes entries under `measurements` for anything listed in `measurement_parameters`.
- The example config already includes two intended keys:
  - `hr_input_1_adc_differential_voltage`
  - `hr_input_2_adc_differential_voltage`
- If you fill in the correct `parameter_id` and `parameter_format` for those TEC1161 signals, the runner will read and store their values at every step.
- If you leave them unconfigured, the record will still include those keys, but their value will be `null` and `measurement_errors` will note that they are still placeholders.

In other words: the storage path is already implemented, but the exact TEC1161 raw IDs still need to be confirmed before you will get real HR differential-voltage numbers.

#### Named vs raw parameters

The script supports two ways of reading parameters:

1. **Named parameters** already present in `mecom/commands.py`, for example:
   - `Actual Output Voltage`
   - `Actual Output Current`
   - `Actual Output Power`
   - `Object Temperature`
   - `Sink Temperature`
2. **Raw parameters** using `parameter_id` and `parameter_format` for signals that are not yet represented in `mecom/commands.py`.

This is especially important for TEC1161-specific ADC or differential-voltage signals.

Example raw measurement entry:

```json
{
  "key": "hr_input_1_adc_differential_voltage",
  "parameter_id": 1234,
  "parameter_format": "FLOAT32"
}
```

Replace `1234` with the confirmed MeCom parameter ID from the TEC1161 protocol table or validated device query.

#### What gets logged

Each run produces three files in `output_directory`:

1. `*_metadata.json`
2. `*_measurements.jsonl`
3. `*_measurements.csv`

The metadata file stores the run configuration and unresolved placeholders.

Each measurement record stores:

- `timestamp`
- `run_started_at`
- `device_label`
- `serial_port`
- `address`
- `channel`
- `step_index`
- `step_name`
- `step_metadata`
- `target.power`
- `target.set_voltage`
- `target.set_current`
- `target.output_enabled`
- `measurements.actual_output_voltage`
- `measurements.actual_output_current`
- `measurements.actual_output_power`
- configured extra measurements such as HR Input 1/2 differential voltage
- `low_resolution_temperatures.*`
- `status.device_status`
- `status.error_number`
- `measurement_errors.*`

The JSONL file preserves the nested structure.
The CSV file flattens nested objects into dotted keys so it can be opened directly in spreadsheets or analysis tools.

#### Safety behavior

The runner makes a best effort to leave the device in a safe state:

- zeroes the configured output setpoints before the first dwell,
- zeroes them again after the last step,
- disables output at the end of the run,
- attempts the same safe-state transition on unhandled exceptions,
- attempts the same safe-state transition on `SIGINT` and `SIGTERM`.

This is still a software-level safety mechanism.
You should validate the actual device behavior on your TEC1161 hardware before using it for unattended production calibration.

#### Recommended workflow for first use

1. Start from `examples/tec1161_calibration_config.example.json`.
2. Confirm the serial port and MeCom address.
3. Keep `channel` set to `1` for CH1.
4. Replace the HR Input 1/2 placeholder IDs with confirmed TEC1161 raw parameter IDs.
5. Add any additional low-resolution temperature channels that are relevant on your hardware.
6. Test with a very short dwell time and a minimal step table first.
7. Inspect the generated metadata/JSONL/CSV files.
8. Only then switch to the intended 30-minute dwell schedule.

#### Reviewing the protocol PDFs

The repository contains:

- `TEC Controller Communication Protocol 5136AT.pdf`
- `MeCom Protocol Specification 5117F.pdf`

Those documents should be the source of truth for confirming TEC1161-specific raw parameter IDs and data formats.
The current script already has the extension points needed for those raw measurements; what remains is filling in the confirmed IDs.


## Additional parameters to get/set
Only parameters present in `mecom/commands.py` can be used with the regular functions, this is a security feature in case someone uses a parameter like "flash firmware" by accident.
Use the *_raw functions if you need access to parameters not in `mecom/commands.py`.
Furthermore, feel free to add more parameters to `mecom/commands.py`.

## Contribution
This is by no means a polished software, contribution by submitting to this repository is appreciated.

## Citation
Cite as `Pomjaksilp, Suthep et al. (2024). pyMeCom 1.0. Zenodo. 10.5281/zenodo.11233757`

## Workflows workspace (COM/TCP automation)

To keep the current serial workflow stable while preparing a TCP variant, use:

- `workflows/automation/com` for COM/serial-specific templates and wrappers
- `workflows/automation/tcp` for TCP-specific templates and wrappers
- `workflows/automation/common` for transport-agnostic shared assets

This split is additive and does not change the existing root-level serial scripts.
