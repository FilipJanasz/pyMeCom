# TCP workflow scaffold

This folder is for TCP-specific configs and wrappers.
The repository already includes a TCP transport class (`MeComTcp`) in `mecom/mecom.py`.

Recommended next step:

1. add a dedicated TCP calibration runner/wrapper here,
2. keep COM runner untouched in existing paths,
3. reuse shared files from `variants/common`.
