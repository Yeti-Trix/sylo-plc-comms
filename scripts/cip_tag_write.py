#!/usr/bin/env python3
"""Write one or many Logix tags to a PLC via ciplogix.

GATED by the operator-managed download allowlist: the target IP must be present
and enabled. This reuses the same allowlist as project downloads — it is the
operator's explicit "this PLC is okay to touch" list. The agent cannot write to
any IP not on it, even with operator permission, and never edits the allowlist.

Inputs: a JSON array of {"tag": "...", "value": <json>} objects via --stdin,
--writes-json, or a single --tag/--value pair.

Usage:
  echo '[{"tag":"MyDint","value":42}]' | py -3.12 cip_tag_write.py --ip 10.1.200.45 --stdin
  py -3.12 cip_tag_write.py --ip 10.1.200.45 --tag MyDint --value 42
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from _cip_client import ensure_ciplogix, open_driver
from _download_allowlist import load_allowlist
from _json_out import emit, emit_error


def _ip_allowed(ip: str) -> tuple[bool, str]:
    al = load_allowlist()
    for entry in al.get("ips", []):
        if isinstance(entry, dict) and entry.get("ip") == ip:
            if entry.get("enabled", True):
                return True, "ok"
            return False, f"IP {ip} is in the allowlist but disabled."
    return False, f"IP {ip} is not in the allowlist. The agent cannot write tags to it."


def _coerce_in(v: Any) -> Any:
    """Best-effort JSON -> pycomm3 value coercion. pycomm3 accepts native types
    directly; the main gotcha is that JSON bools arrive fine and ints/floats are
    native. Strings for STRING tags must be str. We leave values as-is except
    we keep bools as bool (JSON true/false) and pass lists through."""
    return v


def main() -> None:
    parser = argparse.ArgumentParser(description="Write Logix tags via ciplogix (allowlist-gated)")
    parser.add_argument("--ip", required=True, help="Controller IPv4 address")
    parser.add_argument("--tag", default="", help="Single tag name (paired with --value)")
    parser.add_argument("--value", default="", help="Single tag value (parsed as JSON if possible)")
    parser.add_argument("--writes-json", default="", help="JSON array of {tag,value} objects")
    parser.add_argument("--stdin", action="store_true", help="Read JSON array of {tag,value} from stdin")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and validate writes but do not send to the PLC",
    )
    args = parser.parse_args()

    allowed, reason = _ip_allowed(args.ip)
    if not allowed:
        emit_error(reason)

    writes: list[dict[str, Any]] = []
    if args.stdin:
        raw = sys.stdin.read().strip()
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError as exc:
            emit_error(f"stdin is not valid JSON: {exc}")
            return
        if not isinstance(parsed, list):
            emit_error("stdin JSON must be an array of {tag,value} objects.")
            return
        writes = parsed
    if args.writes_json:
        try:
            parsed = json.loads(args.writes_json)
        except json.JSONDecodeError as exc:
            emit_error(f"--writes-json is not valid JSON: {exc}")
            return
        if isinstance(parsed, list):
            writes.extend(parsed)
        elif isinstance(parsed, dict):
            writes.append(parsed)
    if args.tag:
        val: Any
        vraw = args.value
        try:
            val = json.loads(vraw) if vraw != "" else None
        except json.JSONDecodeError:
            val = vraw  # treat as plain string
        writes.append({"tag": args.tag, "value": val})

    # Normalize
    clean: list[tuple[str, Any]] = []
    for w in writes:
        if not isinstance(w, dict) or "tag" not in w:
            emit_error("Each write must be an object with a 'tag' field.")
            return
        name = str(w["tag"]).strip()
        if not name:
            emit_error("Empty tag name in write list.")
            return
        clean.append((name, _coerce_in(w.get("value"))))

    if not clean:
        emit_error("No writes supplied. Use --tag/--value, --writes-json, or --stdin.")

    if args.dry_run:
        emit({
            "ok": True,
            "ip": args.ip,
            "dry_run": True,
            "writes": [{"tag": n, "value": v} for n, v in clean],
        })
        return

    try:
        ensure_ciplogix()
    except Exception as exc:
        emit_error(f"ciplogix setup failed: {exc}")

    plc = open_driver(args.ip, init_tags=True)
    try:
        results: list[dict] = []
        # ciplogix supports plc.write((tag, value), (tag, value), ...) multi-write
        try:
            resp = plc.write(*[(n, v) for n, v in clean])
        except Exception as exc:
            for n, v in clean:
                results.append({"tag": n, "value": v, "ok": False, "error": str(exc)})
            emit({"ok": True, "ip": args.ip, "results": results, "all_failed": True})
            return

        resp_list = resp if isinstance(resp, list) else [resp]
        for (name, value), tag in zip(clean, resp_list):
            err = None
            try:
                err = getattr(tag, "error", None)
                if not err and getattr(tag, "status", None) not in (None, "", "Success"):
                    err = str(getattr(tag, "status"))
            except Exception:
                pass
            results.append({
                "tag": name,
                "value": value,
                "ok": not err,
                "error": err,
            })
        ok_count = sum(1 for r in results if r["ok"])
        emit({
            "ok": True,
            "ip": args.ip,
            "requested": len(clean),
            "succeeded": ok_count,
            "failed": len(clean) - ok_count,
            "results": results,
        })
    finally:
        try:
            plc.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()