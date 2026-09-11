#!/usr/bin/env python3
"""Write one or many OPC UA nodes by node-id spec or tag path.

GATED by the operator-managed download allowlist: the endpoint host IP must be
present and enabled. Reuses the same allowlist as CIP project downloads / tag
writes. The agent cannot write to a PLC not on the list, even with permission.

Inputs: a JSON array of objects on stdin / --writes-json, each:
  {"node": "ns=2;s=MyTag", "value": 42, "variant_type": "Int32"}
  {"node": "MyTag", "value": true}            # bare name -> Tags ns; type inferred
variant_type is optional; when omitted asyncua infers from the Python value
(works for bool/int/float/str scalars). For arrays pass a list value and the
node's existing array type is used.

Usage:
  echo '[{"node":"SafetyOneShot","value":7,"variant_type":"Int32"}]' | \
    py -3.12 opcua_write.py --ip 10.1.200.45 --stdin
  py -3.12 opcua_write.py --ip 10.1.200.45 --node SafetyOneShot --value 7 --variant-type Int32
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any
from urllib.parse import urlparse

from _download_allowlist import load_allowlist
from _json_out import emit, emit_error
from _opcua_client import connect, default_endpoint, ensure_asyncua, jsonable, parse_node_id, tags_namespace_index


def _host_ip(endpoint: str) -> str:
    try:
        return urlparse(endpoint).hostname or ""
    except Exception:
        return ""


def _ip_allowed(ip: str) -> tuple[bool, str]:
    if not ip:
        return False, "Could not determine host IP from endpoint for allowlist check."
    al = load_allowlist()
    for entry in al.get("ips", []):
        if isinstance(entry, dict) and entry.get("ip") == ip:
            if entry.get("enabled", True):
                return True, "ok"
            return False, f"IP {ip} is in the allowlist but disabled."
    return False, f"IP {ip} is not in the allowlist. The agent cannot write OPC UA tags to it."


def _variant(value: Any, variant_type: str | None):
    """Build an asyncua ua.Variant if variant_type is given, else return raw value."""
    from asyncua import ua

    if not variant_type:
        return value
    vt = getattr(ua.VariantType, variant_type, None)
    if vt is None:
        raise ValueError(f"Unknown VariantType: {variant_type}")
    return ua.Variant(value, vt)


async def write_one(client, spec: str, value: Any, variant_type: str | None, default_ns: int) -> dict:
    try:
        node = client.get_node(parse_node_id(spec, default_ns))
    except Exception as exc:
        return {"node": spec, "ok": False, "error": f"bad node id: {exc}"}
    try:
        var = _variant(value, variant_type)
    except Exception as exc:
        return {"node": spec, "ok": False, "error": str(exc)}
    try:
        await node.write_value(var)
    except Exception as exc:
        return {"node": spec, "ok": False, "error": str(exc)}
    # Read-back for confirmation
    readback = None
    try:
        readback = jsonable(await node.read_value())
    except Exception:
        pass
    return {"node": spec, "ok": True, "error": None, "written": jsonable(value), "readback": readback}


async def run(endpoint: str, writes: list[dict], default_ns: int) -> dict:
    client = await connect(endpoint)
    try:
        results = []
        for w in writes:
            spec = str(w.get("node", "")).strip()
            value = w.get("value")
            vt = w.get("variant_type")
            results.append(await write_one(client, spec, value, vt, default_ns))
        ok = sum(1 for r in results if r["ok"])
        return {
            "ok": True,
            "endpoint": endpoint,
            "namespace": default_ns,
            "requested": len(writes),
            "succeeded": ok,
            "failed": len(writes) - ok,
            "results": results,
        }
    finally:
        try:
            await client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Write OPC UA nodes (allowlist-gated)")
    parser.add_argument("--endpoint", default="", help="Full opc.tcp:// endpoint (overrides --ip)")
    parser.add_argument("--ip", default="", help="Controller IP")
    parser.add_argument("--port", type=int, default=4840, help="OPC UA port (default 4840)")
    parser.add_argument("--node", default="", help="Single node spec (paired with --value)")
    parser.add_argument("--value", default="", help="Single value (JSON-parsed if possible)")
    parser.add_argument("--variant-type", default="", help="asyncua VariantType name (e.g. Int32, Boolean)")
    parser.add_argument("--writes-json", default="", help="JSON array of {node,value,variant_type?}")
    parser.add_argument("--stdin", action="store_true", help="Read JSON array from stdin")
    parser.add_argument("--namespace", type=int, default=None, help="Default ns for bare names (auto)")
    parser.add_argument("--dry-run", action="store_true", help="Validate writes but do not send")
    args = parser.parse_args()

    endpoint = args.endpoint.strip() or default_endpoint(args.ip, args.port)
    if not endpoint:
        emit_error("Provide --endpoint or --ip.")

    allowed, reason = _ip_allowed(_host_ip(endpoint))
    if not allowed:
        emit_error(reason)

    writes: list[dict] = []
    if args.stdin:
        raw = sys.stdin.read().strip()
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError as exc:
            emit_error(f"stdin is not valid JSON: {exc}")
            return
        if not isinstance(parsed, list):
            emit_error("stdin JSON must be an array of {node,value} objects.")
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
    if args.node:
        vraw = args.value
        try:
            val = json.loads(vraw) if vraw != "" else None
        except json.JSONDecodeError:
            val = vraw
        writes.append({
            "node": args.node,
            "value": val,
            "variant_type": (args.variant_type.strip() or None),
        })

    clean: list[dict] = []
    for w in writes:
        if not isinstance(w, dict) or not w.get("node"):
            emit_error("Each write must be an object with a 'node' field.")
            return
        clean.append({
            "node": str(w["node"]).strip(),
            "value": w.get("value"),
            "variant_type": (str(w.get("variant_type", "")).strip() or None) if w.get("variant_type") else None,
        })
    if not clean:
        emit_error("No writes supplied. Use --node/--value, --writes-json, or --stdin.")

    if args.dry_run:
        emit({"ok": True, "endpoint": endpoint, "dry_run": True, "writes": clean})
        return

    async def resolve_ns() -> int:
        if args.namespace is not None:
            return args.namespace
        client = await connect(endpoint)
        try:
            return await tags_namespace_index(client) or 2
        finally:
            try:
                await client.close()
            except Exception:
                pass

    try:
        ensure_asyncua()
        default_ns = asyncio.run(resolve_ns())
        result = asyncio.run(run(endpoint, clean, default_ns))
    except SystemExit:
        raise
    except Exception as exc:
        emit_error(f"opcua_write failed: {exc}")
        return
    emit(result)


if __name__ == "__main__":
    main()