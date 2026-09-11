#!/usr/bin/env python3
"""Shared ciplogix (EtherNet/IP) connect helper for sylo-plc-comms scripts.

Handles vendored-wheel install-on-demand and provides a thin connect wrapper.
Does NOT touch the Logix Designer SDK. Read/write path uses pycomm3-compatible
LogixDriver API (ciplogix is a hardened pycomm3 fork).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from _json_out import emit_error


def ensure_ciplogix() -> str:
    """pip-install the vendored ciplogix wheel (+ pycomm3 dep) if not importable.

    Returns a status string for diagnostics.
    """
    try:
        import ciplogix  # noqa: F401

        return "already_importable"
    except ImportError:
        pass

    root = Path(__file__).resolve().parent.parent
    wheels = list((root / "vendor" / "ciplogix").glob("ciplogix-*.whl"))
    if not wheels:
        raise RuntimeError(
            "ciplogix wheel not found under vendor/ciplogix/. "
            "Restore from packages/sylo-plc-comms/vendor/ciplogix/."
        )
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", str(wheels[0]), "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return str(wheels[0])


def open_driver(ip: str, init_tags: bool = False):
    """Ensure ciplogix is importable, open a LogixDriver, return the live plc handle.

    Caller is responsible for plc.close() (use a try/finally). On connection
    failure this calls emit_error and exits (script convention).
    """
    try:
        ensure_ciplogix()
    except Exception as exc:
        emit_error(f"ciplogix setup failed: {exc}")

    from ciplogix import LogixDriver

    plc = LogixDriver(ip, init_tags=init_tags)
    try:
        plc.open()
    except Exception as exc:
        emit_error(f"connection failed to {ip}: {exc}")

    if not plc.connected:
        emit_error(f"connection did not open to {ip}")

    return plc


def normalize_tag_entry(t: dict[str, Any]) -> dict[str, Any]:
    """Reduce a ciplogix tag dict to the fields the agent/UI needs."""
    return {
        "tag_name": t.get("tag_name"),
        "tag_type": t.get("tag_type"),
        "data_type": t.get("data_type_name") or t.get("data_type"),
        "array_size": t.get("array") or None,
        "program": t.get("program") or None,
        "instance_id": t.get("instance_id"),
        "dimensions": t.get("dimensions"),
    }


def _jsonable(v):
    """Coerce common non-JSON ciplogix values (bytes, datetime, enum)."""
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
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(val) for k, val in v.items()}
    return str(v)


def plc_info_dict(plc) -> dict[str, Any]:
    """Full controller attributes via ciplogix get_plc_info + extras."""
    info = plc.get_plc_info()
    keyswitch = str(info.get("keyswitch", "UNKNOWN") or "UNKNOWN").upper()
    key_position = (
        "REM" if keyswitch.startswith("REMOTE")
        else ("RUN" if keyswitch == "RUN" else ("PROG" if keyswitch == "PROG" else None))
    )
    mode = (
        "RUN" if "RUN" in keyswitch
        else ("PROGRAM" if "PROG" in keyswitch else None)
    )
    out = {
        "ip": str(getattr(plc, "_ip", "") or ""),
        "product_name": _jsonable(info.get("product_name")),
        "vendor": _jsonable(info.get("vendor")),
        "revision": _jsonable(info.get("revision")),
        "serial": _jsonable(info.get("serial")),
        "device_type": _jsonable(info.get("device_type")),
        "product_code": _jsonable(info.get("product_code")),
        "keyswitch": keyswitch,
        "key_position": key_position,
        "mode": mode,
        "major_revision": _jsonable(info.get("major_revision")),
        "minor_revision": _jsonable(info.get("minor_revision")),
        "status": _jsonable(info.get("status")),
        "state": _jsonable(info.get("state")),
        "name": _jsonable(getattr(plc, "name", None)),
        "project_name": _jsonable(getattr(plc, "project_name", None)),
    }
    # Some ciplogix builds expose controller attributes via .get_config()
    try:
        cfg = plc.get_config()  # type: ignore[attr-defined]
        if isinstance(cfg, dict):
            out["config"] = _jsonable(cfg)
    except Exception:
        pass
    return out