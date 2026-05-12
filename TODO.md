# TODO: Calibration Workflow Refactor Plan

This file preserves the repository review plan for future implementation. The current codebase already has the MVP pieces for unified TEC + Huber orchestration, so this plan favors incremental refactors rather than a rewrite.

## Current baseline

- Keep the existing separation between Meerstetter TEC code, Huber protocol clients, and workflow-level orchestration.
- Preserve JSON-driven runs, unified CSV/metadata logging, and best-effort safety cleanup on stop/error.
- Keep the two GUI entry points available while refactoring shared logic out of the larger unified GUI.

## Phase A: Low-risk shared cleanup

1. Move duplicated time/log timestamp helpers into one shared module, such as `workflows/automation/common/timebase.py` or `logging_io.py`.
2. Move no-op TEC and bath adapters out of `power_live_log_gui.py` into a common adapters module.
3. Add explicit TEC and bath adapter protocols/interfaces so `DualDeviceRunEngine` no longer relies primarily on `Any` plus `hasattr` checks.
4. Add tests proving the real adapters, fake test adapters, and no-op adapters satisfy the run-engine contract.
5. Make accepted-but-not-yet-implemented stability progression visible by emitting a warning/metadata entry when `progression_mode: "stability"` still runs through the time-based MVP path.

## Phase B: Unified GUI decomposition

1. Extract recipe-building and recipe-validation logic from `power_live_log_gui.py` into pure helper modules.
2. Extract run-mode detection and compatibility validation into a workflow/common module.
3. Extract serial-port choice formatting and scan-summary helpers into a small connection utility module.
4. Keep `power_live_log_gui.py` focused on Tk widget construction, event binding, and calling the extracted services.
5. Preserve existing GUI behavior while moving tests toward the extracted pure functions.

## Phase C: Runtime semantics and Phase 2 progression

1. Return an explicit run result object from `DualDeviceRunEngine.run()` or add a `raise_on_error` option so callers do not accidentally ignore `EngineState.ERROR`.
2. Add a progression-controller abstraction for per-step dwell logic.
3. Implement bath-stability progression using `stability_band_c`, `stability_hold_s`, and `stability_timeout_s`.
4. Keep safety cleanup deterministic for normal completion, user stop, and error paths.

## Phase D: Packaging and distribution

1. Modernize packaging with `pyproject.toml` if the workflow is intended to be installed instead of run from a source checkout.
2. Include `mecom`, `huber`, and `workflows` packages in distribution metadata.
3. Add optional GUI/development extras as needed.
4. Consider console entry points for Windows operators, such as `pymecom-tec-gui` and `pymecom-unified-gui`.

## Notes

- Do not merge low-level TEC and Huber transport code.
- Treat `tec_power_w` consistently as requested/preview/logging power unless a future supported direct power-control path is added.
- Continue updating README documentation whenever user-facing behavior or JSON config behavior changes.
