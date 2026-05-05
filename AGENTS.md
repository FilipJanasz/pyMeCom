# AGENTS.md

## Scope
This file applies to the entire repository.

## Project goal
Build a Windows-friendly calibration application that orchestrates:
1. Meerstetter TEC power control (existing `pyMeCom` capabilities), and
2. Huber thermal bath temperature + pump control (external adapter/repo),
with one GUI, one schedule file, and one unified run log.

## Architecture guardrails
- Keep device drivers separate. Do **not** merge low-level transport code between TEC and Huber.
- Add orchestration at workflow level via adapters and a run engine/state machine.
- Preserve existing TEC safety behavior (best-effort safe output shutdown on stop/error/interrupt).
- Prefer configuration-driven execution using JSON files.

## Recommended module boundaries
- `workflows/automation/common/`:
  - run engine / scheduler
  - shared logging helpers
  - configuration models
- `workflows/automation/huber/`:
  - Huber adapter wrapper (calls external Huber client)
- `power_live_log_gui.py` (or successor GUI module):
  - GUI + user workflow, no hardware protocol logic

## JSON run-config expectations
A run config should support per-step:
- step name
- bath temperature setpoint (°C)
- TEC power setpoint (W)
- step duration (s)
- optional future progression mode (`time` / `stability`)

## Logging expectations
- Keep current TEC logging style and outputs (CSV + metadata sidecar/JSON where applicable).
- Log a single, unified timeline that includes both TEC and bath state per sample.

## Safety defaults
- On stop/error:
  - set TEC to safe output state (zero/off),
  - return bath to configured safe standby temperature,
  - apply configured pump safe state.
- Errors should be visible in logs and UI status.

## Implementation phases
1. MVP: time-based step runner with GUI load/start/stop and unified logging.
2. Phase 2: stability-aware progression rules (e.g., wait until bath temperature is stable before next step).

## Platform constraints
- Must run on Windows.
- Use same Python baseline as current repo workflows.

## Process guidance for agents
- Make minimal, incremental changes.
- Prefer reusing existing scheduler/logging primitives over rewriting from scratch.
- Update README documentation whenever user-facing behavior/config changes.
