# ciplogix (vendored)

Lightweight Allen-Bradley PLC communication over Ethernet/IP — a hardened fork of
**pycomm3** used by LogicForge for **controller status / keyswitch reads** in the
Download settings UI and the pre-download state check in `sdk_download_to_plc.py`.

- **Source:** https://github.com/Yeti-Trix/ciplogix
- **Wheel:** `ciplogix-1.1.0-py3-none-any.whl`
- **License:** MIT (see upstream repo)
- **Author:** Spencer Current (Yeti-Trix), built on pycomm3 by Ian Ottoway

## Why it's here

The Logix Designer SDK is heavy and requires opening a full `.acd` project just to
ask a controller "are you there and what mode are you in." ciplogix answers that in
one CIP Identity request (`get_plc_info()` → `info["keyswitch"]`), which is what
the Download settings status column and the download pre-check use.

The SDK is still the engine for the actual **download** (project push to
controller). ciplogix is only used for **read-only status/mode**.

## Install (handled by scripts)

`plc_status.py` and `sdk_download_to_plc.py` pip-install this wheel into the
SDK Python (3.12) on first run if `ciplogix` isn't importable. Its dependency
`pycomm3` is pulled from PyPI automatically.

## Keyswitch values

`get_plc_info()["keyswitch"]` returns one of (Rockwell KB #28917):

| Value           | Key position | Mode   |
|-----------------|--------------|--------|
| `REMOTE RUN`    | REM          | Run    |
| `REMOTE PROG`   | REM          | Program|
| `RUN`           | RUN (hard)   | Run    |
| `PROG`          | PROG (hard)  | Program|
| `UNKNOWN`       | —            | —      |