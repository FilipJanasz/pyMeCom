# pyMeCom

A Python interface for the MeCom protocol by Meerstetter, with workflow tooling for power scheduling and logging.

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

See `examples/unified_run_config.example.json` for a unified example.
