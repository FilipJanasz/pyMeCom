# Huber workflow adapter

This package provides a workflow-level adapter that wraps the existing Huber connection implementation in `huberStuff/pyPbCmd/huber_adapter.py`.

## Scope

- No protocol internals are reimplemented here.
- The wrapper is intended for orchestration use from higher-level run engines.

## Capabilities

`HuberWorkflowAdapter` exposes:

- `connect()`
- `read_bath_temp()`
- `read_setpoint()`
- `set_setpoint(temp_c)`
- `set_pump_state(on_off)`
- `safe_standby(standby_temp_c, pump_state)`
- `close()`

### Pump-control support

Pump control is capability-based:

- If the underlying thermostat object provides `set_pump_state`, the wrapper calls it.
- If not, `set_pump_state(...)` returns `False` and emits a structured warning (`huber_adapter_pump_control_unsupported`).
- `supports_pump_control` is updated after `connect()` and on pump operations.

## Logging

The adapter emits structured log events for connection, reads, writes, safe standby, unsupported capabilities, and close.
