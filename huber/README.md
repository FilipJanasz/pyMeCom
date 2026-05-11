# Huber clients

This package contains standalone Huber device clients that are independent from the `workflows/automation/` orchestration layer. The workflow adapter can select either route with its `protocol` option, and the GUI exposes the same PP/PB choice in the Huber connection pane.

## Legacy PP/text client

`huber/legacy_pp.py` is the default client for the old Huber device used by this project. It uses the legacy Huber PP/text serial protocol over 9600-baud serial with CRLF-terminated ASCII commands:

- `TI?` / `TE?` for bath/process temperature reads
- `SP?` / `SP@...` for setpoint read/write
- `CA@+00001` / `CA@+00000` for thermoregulation on/off

Standalone examples:

```bash
python -m huber.legacy_pp --port COM4 --read
python -m huber.legacy_pp --port COM4 --setpoint 22.5 --start
python -m huber.legacy_pp --port COM4 --stop
```

## PB client

`huber/pb.py` exposes the PB `{M...}` / `{S...}` route for devices configured for Huber PB communication. It uses the same 9600-baud serial default, reads/writes 14-byte PB frames, and maps the common variables used by the automation workflow:

- `0x00` setpoint
- `0x01` bath/internal temperature
- `0x07` process temperature
- `0x14` thermoregulation active
- `0x16` circulation/pump active

Standalone examples:

```bash
python -m huber.pb --port COM4 --read
python -m huber.pb --port COM4 --setpoint 22.5 --start
python -m huber.pb --port COM4 --pump-on
```

If `--port` is omitted, either client scans available serial ports with its own protocol-specific ping/read.
