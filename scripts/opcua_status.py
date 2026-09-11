#!/usr/bin/env python3
"""Probe an OPC UA server: endpoints, security policies, namespaces, server state.

Read-only. Use to confirm the server is reachable and discover the tags
namespace index before browse/read/write.

Usage:
  py -3.12 opcua_status.py --endpoint opc.tcp://10.1.200.45:4840
  py -3.12 opcua_status.py --ip 10.1.200.45
"""

from __future__ import annotations

import argparse
import asyncio

from _json_out import emit, emit_error
from _opcua_client import (
    connect,
    default_endpoint,
    ensure_asyncua,
    namespaces,
    tags_namespace_index,
    jsonable,
)


async def run(endpoint: str) -> dict:
    client = await connect(endpoint)
    try:
        # Endpoints + security policies
        endpoints = []
        try:
            eps = await client.get_endpoints()
            for ep in eps:
                endpoints.append({
                    "endpoint": str(ep.EndpointUrl),
                    "security_policy": str(ep.SecurityPolicyUri),
                    "security_mode": str(ep.SecurityMode),
                    "transport": str(ep.TransportPolicyUri) if ep.TransportPolicyUri else None,
                    "user_identity_tokens": [
                        str(t.PolicyId) for t in (ep.UserIdentityTokens or [])
                    ],
                })
        except Exception as exc:
            endpoints = [{"error": str(exc)}]

        # Server state / status
        server_state = None
        server_status = None
        try:
            svr = client.get_server_node()
            server_state = jsonable(await svr.get_child(["0:ServerStatus"]))
        except Exception:
            pass
        try:
            state_node = client.get_node("i=2259")  # Server_ServerStatus
            server_status = jsonable(await state_node.read_value())
        except Exception as exc:
            server_status = {"error": str(exc)}

        ns = await namespaces(client)
        tags_ns = await tags_namespace_index(client)

        return {
            "ok": True,
            "endpoint": endpoint,
            "connected": True,
            "endpoints": endpoints,
            "namespaces": ns,
            "tags_namespace_index": tags_ns,
            "server_status": server_status,
            "server_state": server_state,
        }
    finally:
        try:
            await client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe an OPC UA server (read-only)")
    parser.add_argument("--endpoint", default="", help="Full opc.tcp:// endpoint (overrides --ip)")
    parser.add_argument("--ip", default="", help="Controller IP (default endpoint opc.tcp://IP:4840)")
    parser.add_argument("--port", type=int, default=4840, help="OPC UA port (default 4840)")
    args = parser.parse_args()

    endpoint = args.endpoint.strip() or default_endpoint(args.ip, args.port)
    if not endpoint:
        emit_error("Provide --endpoint or --ip.")
    try:
        ensure_asyncua()
        result = asyncio.run(run(endpoint))
    except Exception as exc:
        emit_error(f"opcua_status failed: {exc}")
        return
    emit(result)


if __name__ == "__main__":
    main()