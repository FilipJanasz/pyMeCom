# COM (serial) workflow snapshot

This folder preserves serial-port based files and templates.
It does not modify the existing root-level COM flow.

Current serial runtime path in code:

- `MeComSerial` transport in `mecom/mecom.py`
- calibration runner opening serial in `mecom/calibration.py`

Use this folder to keep COM-specific configs and wrappers stable while TCP work progresses separately.
