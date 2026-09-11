#!/usr/bin/env python3
"""Browse an OPC UA address space node and return its children.

Read-only. Default starting node is the root Objects folder. Pass a node-id
spec (ns=2;s=... or bare name) to browse a specific node.

Usage:
  py -3.12 opcua_browse.py --ip 10.1.200.45
  py -3.12 opcua_browse.py --ip 10.1.200.45 --node "ns=2;s=MyTag"
"""

from __future__ import annotations

import argparse
import asyncio

from _json_out import emit, emit_error
from _opcua_client import (
    connect,
    default_endpoint,
    ensure_asyncua,
    jsonable,
    parse_node_id,
    tags_namespace_index,
)


async def run(endpoint: str, node_spec: str, default_ns: int) -> dict:
    from asyncua import ua

    client = await connect(endpoint)
    try:
        if node_spec:
            node = client.get_node(parse_node_id(node_spec, default_ns))
        else:
            node = client.get_node(ua.ObjectIds.ObjectsFolder)

        try:
            children = await node.get_children()
        except Exception as exc:
            emit_error(f"browse failed for {node_spec or 'Objects'}: {exc}")

        out_children = []
        for ch in children:
            entry = {
                "node_id": str(ch.nodeid),
                "browse_name": None,
                "display_name": None,
                "node_class": None,
                "data_type": None,
                "value": None,
            }
            try:
                bn = await ch.read_browse_name()
                entry["browse_name"] = str(bn)
            except Exception:
                pass
            try:
                dn = await ch.read_display_name()
                entry["display_name"] = str(dn)
            except Exception:
                pass
            try:
                nc = await ch.read_node_class()
                entry["node_class"] = str(nc)
            except Exception:
                pass
            # If it's a Variable, grab data type + value
            if entry["node_class"] and "Variable" in str(entry["node_class"]):
                try:
                    dt = await ch.read_data_type()
                    entry["data_type"] = str(dt)
                except Exception:
                    pass
                try:
                    val = await ch.read_value()
                    entry["value"] = jsonable(val)
                except Exception:
                    pass
            out_children.append(entry)

        return {
            "ok": True,
            "endpoint": endpoint,
            "browsed_node": node_spec or "ObjectsFolder",
            "child_count": len(out_children),
            "children": out_children,
        }
    finally:
        try:
            await client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Browse OPC UA address space (read-only)")
    parser.add_argument("--endpoint", default="", help="Full opc.tcp:// endpoint (overrides --ip)")
    parser.add_argument("--ip", default="", help="Controller IP")
    parser.add_argument("--port", type=int, default=4840, help="OPC UA port (default 4840)")
    parser.add_argument("--node", default="", help="Node-id spec to browse (default Objects folder)")
    parser.add_argument(
        "--namespace",
        type=int,
        default=None,
        help="Default namespace index for bare node specs (auto: Tags namespace, else 2)",
    )
    args = parser.parse_args()

    endpoint = args.endpoint.strip() or default_endpoint(args.ip, args.port)
    if not endpoint:
        emit_error("Provide --endpoint or --ip.")

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
        result = asyncio.run(run(endpoint, args.node.strip(), default_ns))
    except SystemExit:
        raise
    except Exception as exc:
        emit_error(f"opcua_browse failed: {exc}")
        return
    emit(result)


if __name__ == "__main__":
    main()