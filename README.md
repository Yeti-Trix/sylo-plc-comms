# sylo-plc-comms

Sylo package: **PLC comms layer for Studio 5000/Logix** — CIP (EtherNet/IP via
`ciplogix`, vendored wheel) controller info + tag reads/writes, and OPC UA
(`asyncua`) browse/read/write against the controller's OPC UA server. **No
Logix Designer SDK required.**

Split out of `sylo-allen-bradley` on 2026-09-09. Sibling packages in this
bundle:

- `sylo-allen-bradley` — Logix Designer SDK wrapper (`.acd` upload/download, L5X export/import). SDK not bundled.
- `sylo-logicforge` — L5X parse/IO-scaffold, Parse Rules UI, bundled LogicForge backend.

## Tools

| Tool | What it does |
|---|---|
| `plc_comms_cip_plc_info` | Full controller attributes (read-only CIP Identity) |
| `plc_comms_cip_tag_list` | Controller + program tag list (read-only) |
| `plc_comms_cip_tag_read` | Read one/many tags (pycomm3 syntax) |
| `plc_comms_cip_tag_write` | Write one/many tags — **allowlist-gated** |
| `plc_comms_opcua_status` | Probe the OPC UA server (endpoints, namespaces) |
| `plc_comms_opcua_browse` | Browse the address space (read-only) |
| `plc_comms_opcua_tag_list` | Recursive Tags-namespace listing (read-only) |
| `plc_comms_opcua_read` | Read nodes by node-id/tag path (read-only) |
| `plc_comms_opcua_write` | Write nodes — **allowlist-gated** |

## Allowlist

Writes (`cip_tag_write`, `opcua_write`) are gated by the same operator-managed
download allowlist as project downloads. The **canonical file lives in
`sylo-logicforge`** at `packages/sylo-logicforge/assets/download-allowlist.json`
(this package's loader resolves it across the monorepo); env override:
`LOGICFORGE_DOWNLOAD_ALLOWLIST`.

## Python

`ciplogix` installs on demand from `vendor/ciplogix/*.whl` (committed);
`asyncua` pip-installs on demand (see `scripts/requirements.txt`). Runs on the
same `SYLO_PYTHON` as the other controls packages — no SDK Python needed.


## Install

`pi install npm:sylo-plc-comms` — or from the **Capability manager → Pi.dev package catalog** in Sylo (it appears in the Sylo packages strip).

Releases publish automatically from GitHub Actions (npm trusted publishing, with provenance): bump `version` in `package.json`, commit, tag `vX.Y.Z`, push the tag.
