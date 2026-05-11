# Common assets for COM/TCP workflows

This folder is intentionally transport-agnostic.
Use it for files shared by both transport workflows, such as:

- Measurement schema docs
- Post-processing notebooks/scripts
- Common step tables (transport-independent)
- Shared metadata conventions

The active transport-specific runtime files are in:

- `workflows/automation/com`
- `workflows/automation/tcp`

## Run engine (Stage 3 MVP)

`run_engine.py` provides a workflow-level dual-device state machine for TEC + bath orchestration.

- States: `IDLE`, `CONNECTING`, `RUNNING_STEP`, `STOPPING`, `COMPLETED`, `ERROR`
- Time-based per-step progression (`duration_s`)
- Unified timeline CSV + metadata sidecar JSON named `calibRun_YYYYMMDD_HHMMSS_<recipeFileName>.*` when a recipe path is available
- CSV header and every sampled row are flushed and fsynced immediately for recoverable partial logs
- Deterministic safety cleanup on stop/error:
  1. TEC safe output (default 0 W)
  2. Bath standby setpoint (default 20 °C)
  3. Huber process/pump shutdown using the configured pump safe state (default pump off; unsupported pump control is logged)

### Legacy power_schedule zero-power interpretation policy

When run input originates from legacy `power_schedule`, the engine detects ambiguous steps where:
- `tec_power_w == 0.0`, and
- legacy `set_voltage`/`set_current` indicated non-zero output intent.

Policy options:
- `strict` (default): fail before run starts
- `allow_zero_power`: continue, warning recorded
- `legacy_voltage_mode`: optional compatibility path through TEC adapter

Chosen policy and warnings are recorded in metadata under `legacy_interpretation`.
