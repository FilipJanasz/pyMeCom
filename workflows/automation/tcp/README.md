# TCP workflow scaffold

This folder is for TCP-specific configs and wrappers.
The repository already includes a TCP transport class (`MeComTcp`) in `mecom/mecom.py`.

## TCP calibration runner

Use `tcp_calibration_runner.py` to run a stepped calibration loop over TCP while
keeping the existing COM/serial calibration path unchanged.

```bash
python workflows/automation/tcp/tcp_calibration_runner.py \
  --config workflows/automation/tcp/tec1161_calibration_config.tcp.template.json \
  --verbose
```

Notes:

1. Fill in `host`, `port`, `address`, `channel`, and your `steps` in the TCP config.
2. Shared output artifacts (metadata, JSONL, CSV) match the existing calibration layout.
3. Reuse transport-agnostic assets under `workflows/automation/common` as needed.

Top-level convenience script:

```bash
python power_cycle_test_tcp.py --config workflows/automation/tcp/tec1161_calibration_config.tcp.template.json --verbose
```
