#!/usr/bin/env python3
"""Shared asyncua (OPC UA client) helpers for sylo-plc-comms scripts.

asyncua is async, so each script wraps a coroutine in asyncio.run(). This
helper centralizes endpoint connect, namespace resolution, node-id parsing,
and JSON coercion of OPC UA variant values.

Rockwell Logix OPC UA server conventions:
  - Default endpoint: opc.tcp://<ip>:4840
  - The user tags live in the namespace named "Tags" (namespace index 2 on
    most 5380/5580 controllers). Tags are String NodeIds whose identifier is
    the full tag path, e.g. ns=2;s=MyTag  or  ns=2;s=Program:MainProgram.MyTag
"""

from __future__ import annotations

import asyncio
from typing import Any

from _json_out import emit_error


def ensure_asyncua() -> str:
    """pip-install asyncua if not importable. Returns a status string."""
    try:
        import asyncua  # noqa: F401

        return "already_importable"
    except ImportError:
        pass

    import subprocess
    import sys

    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "asyncua", "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return "installed"


def default_endpoint(ip: str, port: int = 4840, path: str = "") -> str:
    base = f"opc.tcp://{ip}:{port}"
    return f"{base}{path}" if path else base


async def connect(endpoint: str, timeout: float = 10.0):
    """Open an asyncua Client and return it. Caller must `await client.close()`
    (prefer `async with`). On failure, emit_error + exit."""
    from asyncua import Client

    client = Client(url=endpoint, timeout=timeout)
    try:
        await client.connect()
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        emit_error(f"OPC UA connect failed to {endpoint}: {msg}")
    return client


async def namespaces(client) -> list[dict[str, Any]]:
    """Return [{index, uri}] for the server."""
    try:
        uris = await client.get_namespace_array()
    except Exception as exc:
        emit_error(f"get_namespace_array failed: {exc}")
        return []
    return [{"index": i, "uri": u} for i, u in enumerate(uris)]


async def tags_namespace_index(client) -> int | None:
    """Find the namespace index whose URI ends with 'Tags' (Rockwell convention).
    Falls back to index 2 if no match."""
    ns = await namespaces(client)
    for entry in ns:
        uri = str(entry["uri"])
        if uri.rstrip("/").endswith("Tags"):
            return entry["index"]
    return 2 if len(ns) > 2 else None


def parse_node_id(spec: str, default_ns: int = 2):
    """Parse a node id spec into an asyncua ua.NodeId.

    Accepted forms:
      "ns=2;s=MyTag"          -> NodeId("MyTag", 2, StringNodeId)
      "MyTag"                 -> NodeId("MyTag", default_ns)
      "ns=3;i=1001"           -> NodeId(1001, 3, NumericNodeId)
    """
    from asyncua import ua

    spec = spec.strip()
    ns = default_ns
    if "ns=" in spec:
        parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in spec.split(";") if "=" in p}
        ns = int(parts.get("ns", default_ns))
        if "s" in parts:
            return ua.NodeId(parts["s"], ns)
        if "i" in parts:
            return ua.NodeId(int(parts["i"]), ns, ua.NodeIdType.Numeric)
        if "b" in parts:
            return ua.NodeId(bytes.fromhex(parts["b"]), ns, ua.NodeIdType.ByteString)
        if "g" in parts:
            return ua.NodeId(parts["g"], ns, ua.NodeIdType.Guid)
    # Bare identifier -> string node id in default namespace
    if spec.isdigit():
        return ua.NodeId(int(spec), ns, ua.NodeIdType.Numeric)
    return ua.NodeId(spec, ns)


def jsonable(v: Any) -> Any:
    """Coerce OPC UA variant values to JSON-friendly Python types."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return v.hex()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): jsonable(val) for k, val in v.items()}
    # Extension objects / datetimes / enums -> string
    try:
        import datetime
        if isinstance(v, datetime.datetime):
            return v.isoformat()
    except Exception:
        pass
    return str(v)


# Map common OPC UA browse names / NodeId types to a short type label
def variant_type_label(vt) -> str:
    try:
        return str(vt.name if hasattr(vt, "name") else vt)
    except Exception:
        return str(vt)