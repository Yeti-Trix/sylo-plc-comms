#!/usr/bin/env python3
"""Read one or many Logix tags from a PLC via ciplogix (read-only).

Accepts a JSON list of tag names on stdin (--tags-json also accepted). Uses
ciplogix multi-service read when more than one tag is given. Returns per-tag
value + error. Bit/array element syntax follows pycomm3 conventions:
  MyTag, MyTag.0, MyArray[3], MyStruct.Member, Program:MainProgram.MyTag

Usage:
  py -3.12 cip_tag_read.py --ip 10.1.200.45 --tags "MyDint,MyBool.0"
  echo '["MyDint","MyReal"]' | py -3.12 cip_tag_read.py --ip 10.1.200.45 --stdin
"""

from __future__ import annotations

import argparse
import json
import sys

from _cip_client import ensure_ciplogix, open_driver
from _json_out import emit, emit_error


def _coerce_value(v):
    """Make ciplogix tag values JSON-serializable (bytes, structs, datetimes)."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return list(v)
    if isinstance(v, (list, tuple)):
        return [_coerce_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _coerce_value(val) for k, val in v.items()}
    # pycomm3 struct Tag objects / datetime / enum -> string-ish
    return str(v)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read Logix tags via ciplogix")
    parser.add_argument("--ip", required=True, help="Controller IPv4 address")
    parser.add_argument("--tags", default="", help="Comma-separated tag names")
    parser.add_argument("--tags-json", default="", help="JSON array of tag names")
    parser.add_argument("--stdin", action="store_true", help="Read JSON array of tags from stdin")
    args = parser.parse_args()

    # Resolve tag list
    names: list[str] = []
    if args.stdin:
        raw = sys.stdin.read().strip()
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError as exc:
            emit_error(f"stdin is not valid JSON: {exc}")
            return
        if not isinstance(parsed, list):
            emit_error("stdin JSON must be an array of tag name strings.")
            return
        names = [str(x).strip() for x in parsed if str(x).strip()]
    if args.tags_json:
        try:
            parsed = json.loads(args.tags_json)
        except json.JSONDecodeError as exc:
            emit_error(f"--tags-json is not valid JSON: {exc}")
            return
        names.extend(str(x).strip() for x in parsed if str(x).strip())
    if args.tags:
        names.extend(x.strip() for x in args.tags.split(",") if x.strip())

    names = [n for n in names if n]
    if not names:
        emit_error("No tag names supplied. Use --tags, --tags-json, or --stdin.")

    try:
        ensure_ciplogix()
    except Exception as exc:
        emit_error(f"ciplogix setup failed: {exc}")

    plc = open_driver(args.ip, init_tags=True)
    try:
        results: list[dict] = []
        try:
            resp = plc.read(*names)
        except Exception as exc:
            # All-failed path — still emit one error row per tag so the caller
            # can see which tags were attempted.
            for n in names:
                results.append({"tag": n, "ok": False, "value": None, "error": str(exc)})
            emit({"ok": True, "ip": args.ip, "results": results, "all_failed": True})
            return

        # plc.read returns a single Tag when one name, or a list of Tags when many.
        resp_list = resp if isinstance(resp, list) else [resp]
        for name, tag in zip(names, resp_list):
            err = None
            try:
                err = getattr(tag, "error", None)
                if not err and getattr(tag, "status", None) not in (None, "", "Success"):
                    err = str(getattr(tag, "status"))
            except Exception:
                pass
            results.append({
                "tag": name,
                "ok": not err,
                "value": _coerce_value(getattr(tag, "value", None)),
                "error": err,
                "type": getattr(tag, "tag_type", None) or getattr(tag, "data_type_name", None),
            })
        ok_count = sum(1 for r in results if r["ok"])
        emit({
            "ok": True,
            "ip": args.ip,
            "requested": len(names),
            "succeeded": ok_count,
            "failed": len(names) - ok_count,
            "results": results,
        })
    finally:
        try:
            plc.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()