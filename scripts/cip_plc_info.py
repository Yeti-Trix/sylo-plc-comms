#!/usr/bin/env python3
"""Full PLC controller attributes via ciplogix (read-only CIP Identity + attrs).

Richer than plc_status.py (which is the pre-download keyswitch check). This is
the agent-facing "tell me about this controller" tool.

Usage:
  py -3.12 cip_plc_info.py --ip 10.1.200.45
"""

from __future__ import annotations

import argparse

from _cip_client import ensure_ciplogix, open_driver, plc_info_dict
from _download_allowlist import load_allowlist
from _json_out import emit


def main() -> None:
    parser = argparse.ArgumentParser(description="Full PLC controller info via ciplogix")
    parser.add_argument("--ip", required=True, help="Controller IPv4 address")
    args = parser.parse_args()

    try:
        ensure_ciplogix()
    except Exception as exc:
        from _json_out import emit_error
        emit_error(f"ciplogix setup failed: {exc}")

    plc = open_driver(args.ip, init_tags=False)
    try:
        info = plc_info_dict(plc)
        info["ip"] = args.ip
        info["reachable"] = True
        info["error"] = None
    except Exception as exc:
        plc.close()
        from _json_out import emit_error
        emit_error(f"get_plc_info failed: {exc}")
        return
    finally:
        try:
            plc.close()
        except Exception:
            pass

    allowlist = load_allowlist()
    info["in_allowlist"] = any(
        isinstance(e, dict) and e.get("ip") == args.ip and e.get("enabled", True)
        for e in allowlist.get("ips", [])
    )
    emit({"ok": True, **info})


if __name__ == "__main__":
    main()