# Huber workflow adapter

This package provides the Huber workflow adapter used by the automation run engine. The low-level Huber serial clients live outside this automation package in the top-level `huber/` package.

## Scope

- Low-level Huber serial code remains separate from TEC code.
- `huber/legacy_pp.py` is the default old-device Huber client. It uses the legacy Huber PP/text protocol: 9600 baud serial with CRLF-terminated ASCII commands such as `TI?`, `SP?`, `SP@...`, and `CA@...`.
- `huber/pb.py` exposes the PB `{M...}`/`{S...}` route for devices configured for PB communication.
- `adapter.py` is the workflow wrapper intended for orchestration use from higher-level run engines; it imports the selected standalone Huber client rather than owning protocol code. Pass `protocol="pp"` or `protocol="pb"` to choose the route.

## Capabilities

`HuberWorkflowAdapter` exposes:

- `connect()`
- `read_bath_temp()`
- `read_setpoint()`
- `set_setpoint(temp_c)`
- `start_process()` / `stop_process()` (thermoregulation on/off using the selected Huber protocol route)
- `set_pump_state(on_off)`
- `safe_standby(standby_temp_c, pump_state)`
- `close()`

### Pump-control support

Pump control is capability-based:

- If the underlying thermostat object provides `set_pump_state`, the wrapper calls it.
- If not, `set_pump_state(...)` returns `False` and emits a structured warning (`huber_adapter_pump_control_unsupported`). Older Huber controllers can still operate the pump automatically when thermoregulation is enabled by `start_process()`.
- `supports_pump_control` is updated after `connect()` and on pump operations.

## Logging

The adapter emits structured log events for connection, reads, writes, thermoregulation start/stop, safe standby, unsupported capabilities, and close.
