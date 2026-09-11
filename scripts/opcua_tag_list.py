#!/usr/bin/env python3
"""List OPC UA tags by recursively browsing the controller's Tags namespace.

Read-only. Starts from the Objects folder and collects every Variable node
whose NodeId is in the Tags namespace (Rockwell ns=2). Struct members and
array elements appear as nested children and are flattened into a 'path'.

Limits: --max-depth (default 4) and --max-nodes (default 2000) protect against
runaway browse on large controllers.

Usage:
  py -3.12 opcua_tag_list.py --ip 10.1.200.45
  py -3.12 opcua_tag_list.py --ip 10.1.200.45 --filter IA00 --max-nodes 500
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
    tags_namespace_index,
)


async def collect(
    node,
    tags_ns: int,
    path: list[str],
    depth: int,
    max_depth: int,
    max_nodes: int,
    flt: str,
    out: list[dict],
) -> None:
    if len(out) >= max_nodes:
        return
    from asyncua import ua

    node_id = node.nodeid
    ns_idx = getattr(node_id, "NamespaceIndex", None)
    try:
        nc = await node.read_node_class()
    except Exception:
        nc = None
    try:
        bn = await node.read_browse_name()
        bn_str = str(bn)
    except Exception:
        bn_str = str(node_id)
    try:
        dn = await node.read_display_name()
        dn_str = str(dn)
    except Exception:
        dn_str = bn_str

    cur_path = path + [bn_str]

    # Only collect Variable nodes in the tags namespace
    is_var = nc is not None and "Variable" in str(nc)
    if is_var and ns_idx == tags_ns:
        entry: dict[str, Any] = {
            "node_id": str(node_id),
            "browse_path": ".".join(cur_path),
            "display_name": dn_str,
            "node_class": str(nc),
        }
        try:
            dt = await node.read_data_type()
            entry["data_type"] = str(dt)
        except Exception:
            entry["data_type"] = None
        try:
            entry["value_rank"] = await node.read_value_rank()
        except Exception:
            pass
        try:
            # array dimensions
            dims = await node.read_attribute(ua.Attributes.ArrayDimensions)
            entry["array_dimensions"] = jsonable(dims.Value.Value if hasattr(dims, "Value") else None)
        except Exception:
            pass
        # Identifier string (the tag path) for ns=2 string node ids
        ident = getattr(node_id, "Identifier", None)
        entry["tag"] = str(ident) if isinstance(ident, str) else None
        if (not flt) or flt in (entry["tag"] or "").lower() or flt in bn_str.lower():
            out.append(entry)
        if len(out) >= max_nodes:
            return

    if depth >= max_depth:
        return
    try:
        children = await node.get_children()
    except Exception:
        return
    for ch in children:
        await collect(ch, tags_ns, cur_path, depth + 1, max_depth, max_nodes, flt, out)
        if len(out) >= max_nodes:
            return


async def run(endpoint: str, flt: str, max_depth: int, max_nodes: int) -> dict:
    from asyncua import ua

    client = await connect(endpoint)
    try:
        tags_ns = await tags_namespace_index(client)
        if tags_ns is None:
            emit_error("Could not determine the Tags namespace index on this server.")
        root = client.get_node(ua.ObjectIds.ObjectsFolder)
        out: list[dict] = []
        await collect(root, tags_ns, [], 0, max_depth, max_nodes, flt, out)
        return {
            "ok": True,
            "endpoint": endpoint,
            "tags_namespace_index": tags_ns,
            "tag_count": len(out),
            "truncated": len(out) >= max_nodes,
            "tags": out,
        }
    finally:
        try:
            await client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="List OPC UA tags (browse Tags namespace)")
    parser.add_argument("--endpoint", default="", help="Full opc.tcp:// endpoint (overrides --ip)")
    parser.add_argument("--ip", default="", help="Controller IP")
    parser.add_argument("--port", type=int, default=4840, help="OPC UA port (default 4840)")
    parser.add_argument("--filter", default="", help="Case-insensitive substring filter on tag/browse name")
    parser.add_argument("--max-depth", type=int, default=4, help="Max browse depth (default 4)")
    parser.add_argument("--max-nodes", type=int, default=2000, help="Cap on collected tag nodes (default 2000)")
    args = parser.parse_args()

    endpoint = args.endpoint.strip() or default_endpoint(args.ip, args.port)
    if not endpoint:
        emit_error("Provide --endpoint or --ip.")
    try:
        ensure_asyncua()
        result = asyncio.run(run(endpoint, args.filter.strip().lower(), args.max_depth, args.max_nodes))
    except SystemExit:
        raise
    except Exception as exc:
        emit_error(f"opcua_tag_list failed: {exc}")
        return
    emit(result)


if __name__ == "__main__":
    main()