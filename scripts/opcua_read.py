#!/usr/bin/env python3
"""Read one or many OPC UA nodes by node-id spec or tag path.

Accepts:
  --nodes "ns=2;s=MyTag,MyOtherTag"      (bare names use Tags namespace, ns=2)
  --nodes-json '["ns=2;s=MyTag","MyDint"]'
  --stdin                                 (JSON array of specs)

Returns per-node value + status. Uses asyncua read for each node.

Usage:
  py -3.12 opcua_read.py --ip 10.1.200.45 --nodes "SafetyOneShot,IA000105"
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from _json_out import emit, emit_error
from _opcua_client import (
    connect,
    default_endpoint,
    ensure_asyncua,
    jsonable,
    parse_node_id,
    tags_namespace_index,
)


async def read_one(client, spec: str, default_ns: int) -> dict:
    from asyncua import ua

    try:
        node = client.get_node(parse_node_id(spec, default_ns))
    except Exception as exc:
        return {"node": spec, "ok": False, "value": None, "error": f"bad node id: {exc}"}
    try:
        val = await node.read_value()
    except Exception as exc:
        return {"node": spec, "ok": False, "value": None, "error": str(exc)}
    out: dict[str, Any] = {"node": spec, "ok": True, "value": jsonable(val), "error": None}
    try:
        dt = await node.read_data_type()
        out["data_type"] = str(dt)
    except Exception:
        pass
    try:
        # Source timestamp for diagnostics
        ts = await node.read_attribute(ua.Attributes.SourceTimestamp)
        out["source_timestamp"] = jsonable(ts.Value.Value if hasattr(ts, "Value") else None)
    except Exception:
        pass
    return out


async def run(endpoint: str, specs: list[str], default_ns: int) -> dict:
    client = await connect(endpoint)
    try:
        results = []
        for s in specs:
            results.append(await read_one(client, s, default_ns))
        ok = sum(1 for r in results if r["ok"])
        return {
            "ok": True,
            "endpoint": endpoint,
            "namespace": default_ns,
            "requested": len(specs),
            "succeeded": ok,
            "failed": len(specs) - ok,
            "results": results,
        }
    finally:
        try:
            await client.close()
        except Exception:
            pass


def main() -> None:
    import json
    import sys

    parser = argparse.ArgumentParser(description="Read OPC UA nodes (read-only)")
    parser.add_argument("--endpoint", default="", help="Full opc.tcp:// endpoint (overrides --ip)")
    parser.add_argument("--ip", default="", help="Controller IP")
    parser.add_argument("--port", type=int, default=4840, help="OPC UA port (default 4840)")
    parser.add_argument("--nodes", default="", help="Comma-separated node-id specs / tag names")
    parser.add_argument("--nodes-json", default="", help="JSON array of node-id specs")
    parser.add_argument("--stdin", action="store_true", help="Read JSON array from stdin")
    parser.add_argument("--namespace", type=int, default=None, help="Default ns for bare names (auto)")
    args = parser.parse_args()

    endpoint = args.endpoint.strip() or default_endpoint(args.ip, args.port)
    if not endpoint:
        emit_error("Provide --endpoint or --ip.")

    specs: list[str] = []
    if args.stdin:
        raw = sys.stdin.read().strip()
        try:
            parsed = json.loads(raw) if raw else []
        except json.JSONDecodeError as exc:
            emit_error(f"stdin is not valid JSON: {exc}")
            return
        if not isinstance(parsed, list):
            emit_error("stdin JSON must be an array of node specs.")
            return
        specs = [str(x).strip() for x in parsed if str(x).strip()]
    if args.nodes_json:
        try:
            parsed = json.loads(args.nodes_json)
        except json.JSONDecodeError as exc:
            emit_error(f"--nodes-json is not valid JSON: {exc}")
            return
        specs.extend(str(x).strip() for x in parsed if str(x).strip())
    if args.nodes:
        specs.extend(x.strip() for x in args.nodes.split(",") if x.strip())
    specs = [s for s in specs if s]
    if not specs:
        emit_error("No node specs supplied. Use --nodes, --nodes-json, or --stdin.")

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
        result = asyncio.run(run(endpoint, specs, default_ns))
    except SystemExit:
        raise
    except Exception as exc:
        emit_error(f"opcua_read failed: {exc}")
        return
    emit(result)


if __name__ == "__main__":
    main()