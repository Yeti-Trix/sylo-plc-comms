#!/usr/bin/env python3
"""List controller (and program) tags from a Logix PLC via ciplogix.

Read-only. init_tags=True pulls the full tag list including UDT/struct layout;
this is the same call ciplogix makes on connect when init_tags=True, just
exposed explicitly. Optionally filter by substring and/or include program tags.

Usage:
  py -3.12 cip_tag_list.py --ip 10.1.200.45
  py -3.12 cip_tag_list.py --ip 10.1.200.45 --filter IA00 --include-programs
"""

from __future__ import annotations

import argparse

from _cip_client import ensure_ciplogix, normalize_tag_entry, open_driver
from _json_out import emit, emit_error


def main() -> None:
    parser = argparse.ArgumentParser(description="List Logix controller tags via ciplogix")
    parser.add_argument("--ip", required=True, help="Controller IPv4 address")
    parser.add_argument("--filter", default="", help="Optional case-insensitive tag-name substring filter")
    parser.add_argument(
        "--include-programs",
        action="store_true",
        help="Also list program-scoped tags (one extra round trip per program)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap number of tags returned (0 = no cap). Apply after filtering.",
    )
    args = parser.parse_args()

    try:
        ensure_ciplogix()
    except Exception as exc:
        emit_error(f"ciplogix setup failed: {exc}")

    plc = open_driver(args.ip, init_tags=True)
    try:
        flt = (args.filter or "").strip().lower()
        try:
            raw_tags = plc.get_tag_list()
        except Exception as exc:
            emit_error(f"get_tag_list failed: {exc}")
            return

        tags = [normalize_tag_entry(t) for t in raw_tags]

        program_tags: list[dict] = []
        if args.include_programs:
            try:
                programs = plc.get_programs()  # type: ignore[attr-defined]
            except Exception:
                programs = []
            for prog in programs:
                prog_name = prog if isinstance(prog, str) else getattr(prog, "name", str(prog))
                try:
                    p_raw = plc.get_tag_list(program=prog_name)
                except Exception:
                    p_raw = []
                for t in p_raw:
                    t["program"] = prog_name
                    program_tags.append(normalize_tag_entry(t))

        all_tags = tags + program_tags
        if flt:
            all_tags = [
                t for t in all_tags
                if flt in (str(t.get("tag_name") or "").lower())
                or flt in (str(t.get("program") or "").lower())
            ]
        total = len(all_tags)
        if args.limit and args.limit > 0:
            all_tags = all_tags[: args.limit]

        emit({
            "ok": True,
            "ip": args.ip,
            "controller_tag_count": len(tags),
            "program_tag_count": len(program_tags),
            "total_matching": total,
            "returned": len(all_tags),
            "truncated": total > len(all_tags),
            "tags": all_tags,
        })
    finally:
        try:
            plc.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()