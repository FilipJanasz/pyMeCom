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
