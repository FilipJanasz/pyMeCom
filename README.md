# pyMeCom

A Python interface for the MeCom protocol by Meerstetter, with workflow tooling for power scheduling and logging.


## GUI entry points

- **TEC-only live logger GUI:** run `python power_live_log_tec_gui.py` to use the standalone Meerstetter TEC logger workflow without Huber controls. It accepts legacy live-logger JSON with `power_schedule`, older TEC calibration JSON with top-level `steps`, and shared step-based JSON; Huber-only fields are ignored by this GUI.
- **Unified TEC + Huber GUI:** run `python power_live_log_gui.py` for the combined bath/TEC scheduler and unified log workflow. TEC-only, Huber-only, and Unified run modes accept the same shared step-based JSON. Huber-only mode runs shared JSON steps that contain `bath_setpoint_c` and no TEC requests, so the TEC adapter is not connected. If a loaded step does not request a device (`bath_setpoint_c` for Huber, or `tec_power_w`/`tec_voltage_v`/`tec_current_a` for TEC), that device is not connected or commanded for that run.


### Unified GUI connection and runtime panes

The unified GUI keeps device setup in one top-left **Connection Detection** pane and keeps non-port run settings in a separate **Runtime Options** pane. The connection pane has side-by-side TEC and Huber sections with their own port fields, detect buttons, colored indicators, and status text. Those per-device indicators are the controller status display; the Runtime Options pane no longer repeats controller status with a third indicator. TEC-specific connection settings such as port, serial hint, autodetect, and address live with TEC detection; the Huber port lives with Huber detection. Runtime-only settings such as run mode, channel, acquisition rate, duration, bath standby temperature, and pump safe state are no longer mixed into the connection controls. The run-mode selector has **Huber-only** next to Auto/TEC-only/Unified for bath-only recipes. **Run Setup** also shows a compact recipe preview for the loaded JSON, a moving red progress marker during runs, elapsed/remaining time, and the estimated wall-clock finish time.

Manual commands now live on their own **Manual Commands** tab. They provide basic operator commands without changing JSON schedules: set TEC voltage/current, zero TEC output, set Huber setpoint, start/stop Huber thermoregulation, and read Huber bath/setpoint values. TEC power is no longer offered as a direct manual hardware command because the TEC workflow uses the working voltage/current path; `tec_power_w` is retained as a requested-power preview/logging value derived from V×I where possible. Pump controls are no longer exposed in the manual tab because not every Huber client supports a separate pump command. These controls still call the workflow adapters rather than mixing hardware protocol logic into the GUI.

JSON loading/template generation and recipe editing are split into separate tabs for compactness: **Example Loader** contains the config path, output settings, template-curve fields, and loaded JSON preview; **Example Editor** contains the recipe builder. The **Recipe Builder** supports GUI-created shared JSON files and now keeps the step-entry fields in a compact left panel with the editable recipe table beside it, leaving more vertical room for the preview plot. Operators can use **Add Step** to append the fields as a new row at the end of the recipe, use **Edit Selected** to modify the currently selected row, enter duration, Huber temperature, TEC voltage/current, and/or TEC preview power, insert a new step immediately above or below the selected reference step, and use **Move Up** / **Move Down** to swap the selected step with its neighbor. Step-editing buttons are grouped separately from file load/save buttons. To edit an existing file, use **Browse JSON to Edit** for an explicit file picker, or use **Use Current Example from Example Loader** to load the JSON currently selected in the **Example Loader** config path. The editor shows a running **Recipe total duration** counter while steps are added, updated, deleted, or loaded. The preview plot shows step curves for TEC requested power and Huber bath temperature; clicking in a preview subplot copies a point into the editable fields. **Save Recipe JSON** writes the same `steps[]` + `safety` schema used by loaded unified configs, using the editable **Save Recipe JSON As** path field so operators can accept the suggested `<source>_edited.json` name or type a different filename before saving.

Use the single **Scan COM Ports** button when automatic detection does not choose the expected device. The scan result now populates a fixed-width dropdown with one COM device per option and short device explanations; choose a port and click **Use for TEC** or **Use for Huber** before clicking **Detect TEC** or **Detect Huber**. The connection pane only shows short status text, and each device has a **Details** button for full detection errors or diagnostic text, so long COM/HWID strings and TEC exceptions no longer force the GUI wider. TEC detection now matches the standalone TEC-only GUI by treating a successful MeCom serial open as a detected TEC, then attempts the controller address query only as extra verification; if the address query fails, the port is still kept in the port field and TEC serial autodetect is disabled for subsequent starts to avoid fragile autodetect ordering. Huber detection now uses standalone clients in the top-level `huber/` package. Operators can choose `pp` for the old legacy PP/text route or `pb` for the PB `{M...}`/`{S...}` route; `pp` remains the default for the known old Huber device. Huber detection runs in a background thread so serial scanning does not block the Tk event loop or make the GUI unresponsive.

Huber connection scan fix plan:
1. Keep Huber low-level clients separate from TEC code and call them through `huber/legacy_pp.py`, `huber/pb.py`, and `workflows/automation/huber/adapter.py`.
2. The copied `huberStuff/pyPbCmd` debug project has been removed; the unified automation path uses the selectable clients in `huber/`.
3. Use protocol-specific detection: PP scans with `TI?\r\n`; PB scans with a PB bath-temperature read frame (`{M01********\r\n`).
4. If scanning still finds no bath, expose each failed candidate and response in the GUI/logs in a later diagnostic pass without changing the Huber protocol implementation.

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

- JSON-configured run steps containing bath and/or TEC setpoints plus dwell duration.
- GUI flow similar to current TEC-only tooling: load config, preview, start/stop, view status.
- Unified sampled log output (same style as current TEC logging outputs).
- Crash-resilient log growth across TEC-only, Huber-only, and Unified modes: CSV headers and every sampled row are flushed to disk immediately so partial data remains available if a run stops, errors, or the GUI/process fails.
- Safe state behavior on completion/failure.

### Phase 2

- Stability-aware progression logic (e.g., wait until bath temperature is within a tolerance band for a hold time before advancing).
- Extended fault handling and operator controls.

## High-level architecture

- **Adapters**
  - `TecAdapter` (wrap existing MeCom interactions)
  - `HuberLegacyPPClient` (standalone old-device Huber serial client in `huber/legacy_pp.py`)
  - `HuberPBClient` (standalone PB route in `huber/pb.py`)
  - `HuberWorkflowAdapter` (workflow-level capability-aware wrapper around the selected Huber client)
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

The active Huber runtime can use either `huber/legacy_pp.py` (`pp`, the default for the known old device) or `huber/pb.py` (`pb`, PB `{M...}`/`{S...}` framing). Both can run directly with `python -m huber.legacy_pp` or `python -m huber.pb`. The workflow wrapper (`workflows/automation/huber/adapter.py`) uses capability checks for optional pump control. When pump control is unavailable in the connected client, pump requests are logged as unsupported instead of attempting protocol-level fallbacks; older Hubers may still run the pump automatically when thermoregulation is enabled.

## Unified run config schema (Stage 2)

A new JSON model is available under `workflows/automation/common/run_config.py`:

- `RunConfig`
- `UnifiedStep`
- `SafetyConfig`

### Run recipe file format

JSON is kept as the run-recipe format because each step can carry optional, nested, and typed fields (bath setpoint, TEC V/I/W requests, future stability settings, and safety defaults) without relying on column-position conventions. CSV remains best for tabular measurement logs and imported/exported simple point lists, but JSON is less ambiguous for the executable schedule and its safety metadata.

### Shared/unified step fields (MVP)

Each `steps[]` entry supports:

- `name` (string; defaults to `step_N` when omitted)
- `duration_s` (seconds, number > 0)
- `bath_setpoint_c` (optional number; requests a Huber bath setpoint)
- `tec_power_w` (optional number; requests a TEC power setpoint)
- `tec_voltage_v` and `tec_current_a` (optional numbers; request the TEC voltage/current path used by the GUI curve builder)
- `progression_mode` (`"time"` default, or `"stability"`)

A step may be TEC-only, Huber-only, or TEC+Huber. The run engine and GUIs ignore devices that are not requested by the loaded JSON, so the same shared file can be used in TEC-only and TEC+Huber workflows.

### Phase-2-ready optional stability fields

Available now to avoid schema churn:

- `stability_band_c`
- `stability_hold_s`
- `stability_timeout_s`

### Safety block

`RunConfig.safety` supports:

- `tec_power_w_on_stop` (default `0.0`)
- `bath_standby_setpoint_c` (default `20.0`)
- `pump_on_in_safe_state` (default `false`)

### Backward compatibility with TEC-only power schedule

The loader accepts legacy TEC `power_schedule` JSON and maps it to unified steps.

Explicit mapping behavior:

- `legacy.name` -> `UnifiedStep.name`
- `legacy.power` -> `UnifiedStep.tec_power_w`
- `legacy.duration_seconds` -> `UnifiedStep.duration_s`
- `UnifiedStep.bath_setpoint_c` remains unset for TEC-only legacy inputs, so Huber is ignored
- `UnifiedStep.progression_mode` defaults to `"time"`
- `legacy.set_voltage` and `legacy.set_current` map to `UnifiedStep.tec_voltage_v` and `UnifiedStep.tec_current_a`

This allows incremental migration while keeping existing TEC-only configs usable for schema parsing.

For the TEC-only live logger GUI, older TEC calibration `steps[]` entries and shared/unified `steps[]` entries are converted into TEC `power_schedule[]` entries when they contain TEC fields. The conversion preserves `name`, `power`/`tec_power_w`, `set_voltage`/`tec_voltage_v`, `set_current`/`tec_current_a`, and `enable_output`; Huber-only steps are skipped by the TEC scheduler.

All GUI run modes use incremental CSV storage: the logger writes the header when the run file opens, then flushes each sampled row as soon as it is collected. This means the visible CSV grows during the run, and completed samples should remain available after a stop/error or process failure. Existing TEC-only configs may still contain `csv_flush_every_rows` for compatibility, but the live logger now uses per-row durable flushing for consistency with Unified and Huber-only runs.

See `examples/unified_run_config.example.json` for a shared TEC + Huber example. In that file, each `steps[]` item is a coordinated action: `bath_setpoint_c` is the Huber bath setpoint, `tec_voltage_v` and `tec_current_a` are the TEC hardware setpoints, `tec_power_w` is a requested-power preview/logging value, and `duration_s` is how long the run engine dwells before advancing. The run engine starts Huber thermoregulation after applying each bath setpoint, matching the selected Huber protocol path (`pp` uses `CA@...`; `pb` writes PB variable `0x14`). The second example step uses `progression_mode: "stability"` with stability fields as a Phase-2 template; the current MVP remains time-based unless stability progression is explicitly enabled in the run engine. The top-level `safety` block defines what the engine should do on stop/error: zero or safe TEC output, return the bath to standby, and apply the pump safe state when the Huber client reports pump support.

The GUI **Build Unified Example JSON** button is a template generator, not a hardware action. It writes a starter shared JSON file from only the non-empty editable curve fields in the **JSON Example Editor** tab: Huber-only, TEC-only, and TEC+Huber templates are all valid. A blank `Huber Temp Curve °C` now means “build a TEC-only shared JSON” instead of injecting a default bath curve. TEC templates require both `TEC Voltage Curve V` and `TEC Current Curve A`; when both Huber and TEC curves are filled, their point counts must match. For TEC V/I points, the generated step preserves `tec_voltage_v` and `tec_current_a` and fills `tec_power_w` as voltage × current so the requested-input preview reflects the requested curve instead of a fake zero-power line. For more interactive editing, use the **Recipe Builder** table and plot to add mixed or bath-only steps before saving. After saving, the JSON can be reviewed, edited, loaded, and run in TEC-only, Huber-only, or Unified mode.


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
- In the **Example Loader** tab, the GUI shows editable template fields for:
  - `Huber Temp Curve °C (comma-separated)`,
  - `TEC Voltage Curve V (comma-separated)`,
  - `TEC Current Curve A (comma-separated)`,
  - `Step Duration Seconds`,
  and a **Build Unified Example JSON** button that writes a shared starter JSON from the non-empty curve groups without starting hardware.
- Requested-input preview uses separate subplots for TEC requested power and Huber requested temperature, derives TEC power from voltage × current when old JSONs contain `tec_power_w: 0.0` with nonzero V/I fields, gracefully handles JSONs that only include one request type, and unified runs will skip connecting to devices with no requested setpoints in the loaded JSON.

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

- `calibRun_YYYYMMDD_HHMMSS_<recipeFileName>.csv`
- `calibRun_YYYYMMDD_HHMMSS_<recipeFileName>.metadata.json`

Expected:
- Unified timeline rows contain both TEC and bath columns when unified mode is active, including TEC HR input differential-voltage samples as `tec_hr_1_differential_voltage_v` and `tec_hr_2_differential_voltage_v` when the TEC adapter is connected. These use the same TEC programming-manual channels already used by the TEC-only logger examples: Differential Voltage parameter `1046` with instances `1` (HR_1) and `2` (HR_2).
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
