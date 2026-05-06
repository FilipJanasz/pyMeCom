# pyMeCom

A Python interface for the MeCom protocol by Meerstetter, with workflow tooling for power scheduling and logging.


## GUI entry points

- **TEC-only live logger GUI:** run `python power_live_log_tec_gui.py` to use the standalone Meerstetter TEC logger workflow without Huber or unified-run controls. This is the recommended GUI while the unified workflow is being debugged. It accepts legacy live-logger JSON with `power_schedule` and older TEC calibration JSON with top-level `steps` that use fields such as `dwell_seconds`, `set_voltage`, `set_current`, `power`, and `enable_output`.
- **Unified TEC + Huber GUI:** run `python power_live_log_gui.py` for the combined bath/TEC scheduler and unified log workflow. Its TEC-only mode accepts the same legacy TEC formats as the standalone TEC GUI; true unified JSON is detected only when `steps[]` contains unified fields such as `bath_setpoint_c`, `tec_power_w`, `duration_s`, progression/stability fields, or a unified `safety` block.

## New integration direction: TEC + Huber unified calibration app

This repository is being extended to support a single calibration workflow that combines:

- TEC power control (existing `pyMeCom` capability), and
- Huber thermal bath control (temperature setpoint + pump control),
- with one GUI, one JSON schedule/config, and one unified log timeline.

### Objectives

1. Keep low-level device drivers separate (TEC vs Huber).
2. Integrate at the orchestration layer (scheduler/run engine + adapters).
3. Maintain safe shutdown behavior on stop/error.
4. Keep configuration and run execution JSON-driven.
5. Preserve current logging style used by TEC workflows.

## Planned implementation phases

### Phase 1 (MVP)

- JSON-configured run steps containing bath setpoint, TEC power setpoint, and dwell duration.
- GUI flow similar to current TEC-only tooling: load config, preview, start/stop, view status.
- Unified sampled log output (same style as current TEC logging outputs).
- Safe state behavior on completion/failure.

### Phase 2

- Stability-aware progression logic (e.g., wait until bath temperature is within a tolerance band for a hold time before advancing).
- Extended fault handling and operator controls.

## High-level architecture

- **Adapters**
  - `TecAdapter` (wrap existing MeCom interactions)
  - `HuberAdapter` (wrap external Huber client/repo)
  - `HuberWorkflowAdapter` (workflow-level capability-aware wrapper around `huberStuff/pyPbCmd/huber_adapter.py`)
- **RunEngine**
  - Owns schedule progression, timing, and coordinated setpoint application
- **Logger**
  - Writes one timeline containing TEC + bath readings and step context
- **GUI**
  - Handles operator workflow and status display, not hardware protocol details

## Notes

- Existing TEC calibration and live logging workflows remain available.
- Integration work should reuse existing scheduler/logger patterns where practical.

### Huber wrapper capability note

The workflow Huber wrapper (`workflows/automation/huber/`) uses capability checks for optional pump control. When pump control is unavailable in the connected client, pump requests are logged as unsupported instead of attempting protocol-level fallbacks.

## Unified run config schema (Stage 2)

A new JSON model is available under `workflows/automation/common/run_config.py`:

- `RunConfig`
- `UnifiedStep`
- `SafetyConfig`

### Unified step fields (MVP)

Each `steps[]` entry supports:

- `name` (string)
- `bath_setpoint_c` (number)
- `tec_power_w` (number)
- `duration_s` (seconds, number > 0)
- `progression_mode` (`"time"` default, or `"stability"`)

### Phase-2-ready optional stability fields

Available now to avoid schema churn:

- `stability_band_c`
- `stability_hold_s`
- `stability_timeout_s`

### Safety block

`RunConfig.safety` supports:

- `tec_power_w_on_stop` (default `0.0`)
- `bath_standby_setpoint_c` (default `25.0`)
- `pump_on_in_safe_state` (default `true`)

### Backward compatibility with TEC-only power schedule

The loader accepts legacy TEC `power_schedule` JSON and maps it to unified steps.

Explicit mapping behavior:

- `legacy.name` -> `UnifiedStep.name`
- `legacy.power` -> `UnifiedStep.tec_power_w`
- `legacy.duration_seconds` -> `UnifiedStep.duration_s`
- `UnifiedStep.bath_setpoint_c` defaults to `25.0`
- `UnifiedStep.progression_mode` defaults to `"time"`
- `legacy.set_voltage`, `legacy.set_current`, and `legacy.enable_output` are intentionally ignored by Stage 2 schema mapping because `UnifiedStep` is power-driven (`tec_power_w`)

This allows incremental migration while keeping existing TEC-only configs usable for schema parsing.

For the TEC-only live logger GUI, older TEC calibration `steps[]` entries are converted into `power_schedule[]` entries. The conversion preserves `name`, `power`, `set_voltage`, `set_current`, and `enable_output`, and maps `dwell_seconds` (or `duration_seconds`) to `duration_seconds` for preview and live logger execution.

See `examples/unified_run_config.example.json` for a unified example. In that file, each `steps[]` item is a coordinated TEC + Huber action: `bath_setpoint_c` is the Huber bath setpoint, `tec_power_w` is the TEC requested power, and `duration_s` is how long the run engine dwells before advancing. The second example step uses `progression_mode: "stability"` with stability fields as a Phase-2 template; the current MVP remains time-based unless stability progression is explicitly enabled in the run engine. The top-level `safety` block defines what the engine should do on stop/error: zero or safe TEC output, return the bath to standby, and apply the pump safe state.


## Stage 4 manual verification checklist (GUI integration)

Use this checklist to manually validate the single-operator GUI workflow while keeping TEC-only behavior intact.

### 1) Launch GUI on Windows-compatible Python

For the restored TEC-only workflow, launch:

```bash
python power_live_log_tec_gui.py
```

For the unified TEC + Huber workflow, launch:

```bash
python power_live_log_gui.py
```

Expected:
- The TEC-only GUI opens without Huber/unified controls and accepts legacy TEC live logger JSON files.
- The unified GUI opens without import/runtime errors.
- Live plotting area appears when `matplotlib` is installed.
- In the **Config & Output** section, the GUI shows editable fields for:
  - `Huber Temp Curve °C (comma-separated)`,
  - `TEC Voltage Curve V (comma-separated)`,
  - `TEC Current Curve A (comma-separated)`,
  - `Step Duration Seconds`,
  and a **Build Unified Example** button that writes a unified JSON with both curves.
- Requested-input preview uses separate subplots for TEC requested power and Huber requested temperature, gracefully handles JSONs that only include one request type, and unified runs will skip connecting to devices with no requested setpoints in the loaded JSON.

### 2) Verify TEC-only mode (legacy flow preserved)

1. Load a legacy TEC JSON containing `power_schedule` (for example `examples/power_live_log_com.example.json`) or an older TEC calibration JSON containing top-level TEC `steps` (for example `examples/tec1161_calibration_config.example.json`).
2. Confirm preview reflects TEC schedule intent.
3. Start run, observe live telemetry and status updates.
4. Stop run with **Force Stop**.

Expected:
- Run starts and logs as before.
- Controller status updates are user-visible (connecting/running/stopped/error).
- Output files are created in selected output directory.

### 3) Verify Unified mode end-to-end

1. Load unified JSON (for example `examples/unified_run_config.example.json`).
2. Confirm step preview shows bath + TEC setpoints and durations.
3. Set safety values before start:
   - bath standby temperature,
   - pump safe state.
4. Start unified run.
5. Observe run mode indicator (**Unified**), engine state, and any errors in GUI.
6. Stop run mid-step and repeat with a full completion run.

Expected:
- Explicit run mode indicator is visible (`TEC-only` vs `Unified`).
- Engine state transitions are visible in GUI status.
- On stop/error, safety actions are applied and visible in logs/status.
- Bath telemetry fields (temperature/setpoint/pump state when available) appear in status/plots.

### 4) Error handling checks

Run these negative tests and verify clear user-facing messages:

- Bad JSON (syntax error).
- Missing required step fields.
- Invalid COM/connection parameters.
- Unsupported bath pump command path.

Expected:
- Dialog/status clearly describes what failed and what operator should check next.
- Run does not silently fail.

### 5) Log validation

After each test run, inspect generated files:

- `run_timeline_*.csv`
- `run_timeline_*.metadata.json`

Expected:
- Unified timeline rows contain both TEC and bath columns when unified mode is active.
- Metadata records safety config, events, and final engine state.

### 6) Minimal smoke automation (recommended)

From repo root:

```bash
pytest -q tests/test_run_config.py tests/test_run_engine.py
```

If GUI smoke tests exist, run them too (headless where practical).

---

If any step fails, capture:
- config used,
- exact timestamp,
- GUI status text,
- metadata `events[]` excerpt.

This makes integration issues reproducible across Windows test benches.
