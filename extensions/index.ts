/**
 * sylo-plc-comms — PLC comms layer for Studio 5000/Logix.
 *
 * CIP (EtherNet/IP via ciplogix) controller info + tag reads/writes, and OPC UA
 * (asyncua) browse/read/write. No Logix Designer SDK required. Split out of
 * sylo-allen-bradley on 2026-09-09 (see the sylo-logicforge/sylo-allen-bradley
 * packages for the SDK wrapper and L5X parse/IO-scaffold flows).
 */
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

const execFileAsync = promisify(execFile)

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPTS_DIR = path.join(PACKAGE_ROOT, 'scripts')

type ToolContentBlock = { type: 'text'; text: string }

// CIP (EtherNet/IP via ciplogix) and OPC UA (asyncua) scripts run on the same
// Python as the parse scripts (no Logix Designer SDK needed).

function resolvePythonInvocation(): { command: string; prefixArgs: string[] } {
  const envPython = process.env.SYLO_PYTHON?.trim()
  if (envPython) {
    return { command: envPython, prefixArgs: [] }
  }
  return { command: process.platform === 'win32' ? 'python' : 'python3', prefixArgs: [] }
}

function toolError(text: string): { content: ToolContentBlock[] } {
  return { content: [{ type: 'text', text }] }
}

function tail(text: string, lines = 12): string {
  return text.trim().split('\n').slice(-lines).join('\n').trim()
}

type ExecOutput = { stdout: string; stderr: string }

async function execScript(scriptName: string, args: string[], timeoutMs: number): Promise<ExecOutput> {
  const scriptPath = path.join(SCRIPTS_DIR, scriptName)
  const { command, prefixArgs } = resolvePythonInvocation()
  return execFileAsync(command, [...prefixArgs, scriptPath, ...args], {
    cwd: PACKAGE_ROOT,
    maxBuffer: 32 * 1024 * 1024,
    windowsHide: true,
    timeout: timeoutMs,
  })
}

async function runPythonScript(
  scriptName: string,
  args: string[],
  timeoutMs = 120_000,
): Promise<{ content: ToolContentBlock[] }> {
  try {
    const { stdout, stderr } = await execScript(scriptName, args, timeoutMs)
    let parsed: { ok?: boolean; error?: string; operator_chat?: string } | null = null
    const trimmed = stdout.trim()
    try {
      parsed = JSON.parse(trimmed) as { ok?: boolean; error?: string; operator_chat?: string }
    } catch {
      /* scripts print {"ok": false, "error": ...} on failure paths — fall through */
    }
    if (!parsed) {
      return toolError(tail(stdout) || stderr.trim() || `${scriptName} produced no output`)
    }
    if (parsed.ok === false) {
      return toolError(parsed.error ?? `${scriptName} failed`)
    }
    if (typeof parsed.operator_chat === 'string' && parsed.operator_chat.trim()) {
      return { content: [{ type: 'text', text: parsed.operator_chat.trim() }] }
    }
    return { content: [{ type: 'text', text: JSON.stringify(parsed, null, 2) }] }
  } catch (err) {
    // Non-zero exit: scripts print {"ok": false, "error": ...} before exiting 1 —
    // surface that instead of Node's generic "Command failed" message.
    const e = err as NodeJS.ErrnoException & { stdout?: string; stderr?: string }
    let parsed: { ok?: boolean; error?: string } | null = null
    try {
      parsed = JSON.parse(String(e.stdout ?? '').trim())
    } catch {
      parsed = null
    }
    if (parsed && typeof parsed.error === 'string' && parsed.error.trim()) {
      return toolError(parsed.error.trim())
    }
    const detail = [
      typeof e.stdout === 'string' ? tail(e.stdout) : '',
      typeof e.stderr === 'string' ? tail(e.stderr) : '',
    ]
      .filter(Boolean)
      .join('\n')
    const message = err instanceof Error ? err.message : String(err)
    return toolError(detail ? `${message}\n${detail}` : message)
  }
}

export default function syloPlcCommsExtension(pi: ExtensionAPI): void {
  // ---- CIP tag tools (EtherNet/IP via ciplogix) --------------------------------

  pi.registerTool({
    name: 'plc_comms_cip_plc_info',
    label: 'PLC comms CIP PLC info',
    description:
      'Full controller attributes via ciplogix (read-only CIP Identity): product name, vendor, revision, serial, keyswitch/mode, project name. No Logix Designer SDK required.',
    parameters: Type.Object({
      ip: Type.String({ description: 'Controller IPv4 address (e.g. 10.1.200.45)' }),
    }),
    async execute(_toolCallId, params) {
      const ip = String(params.ip ?? '').trim()
      if (!ip) return toolError('plc_comms_cip_plc_info requires ip.')
      return runPythonScript('cip_plc_info.py', ['--ip', ip], 60_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_cip_tag_list',
    label: 'PLC comms CIP tag list',
    description:
      'List controller (and optionally program-scoped) tags from a Logix PLC via ciplogix (read-only). Returns tag name, type, data type, array size. Optionally filter by substring. No SDK required.',
    parameters: Type.Object({
      ip: Type.String({ description: 'Controller IPv4 address' }),
      filter: Type.Optional(Type.String({ description: 'Case-insensitive tag-name substring filter' })),
      include_programs: Type.Optional(
        Type.Boolean({
          description: 'Also list program-scoped tags (extra round trip per program)',
        }),
      ),
      limit: Type.Optional(Type.Number({ description: 'Cap number of tags returned (0 = no cap)' })),
    }),
    async execute(_toolCallId, params) {
      const ip = String(params.ip ?? '').trim()
      if (!ip) return toolError('plc_comms_cip_tag_list requires ip.')
      const args = ['--ip', ip]
      const filter = String(params.filter ?? '').trim()
      if (filter) args.push('--filter', filter)
      if (params.include_programs === true) args.push('--include-programs')
      if (typeof params.limit === 'number' && params.limit > 0) args.push('--limit', String(params.limit))
      return runPythonScript('cip_tag_list.py', args, 180_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_cip_tag_read',
    label: 'PLC comms CIP tag read',
    description:
      'Read one or many Logix tags from a PLC via ciplogix (read-only). Pass an array of tag names; uses multi-service read. Bit/array/struct syntax follows pycomm3: MyTag, MyTag.0, MyArray[3], MyStruct.Member, Program:MainProgram.MyTag. No SDK required.',
    parameters: Type.Object({
      ip: Type.String({ description: 'Controller IPv4 address' }),
      tags: Type.Optional(Type.Array(Type.String(), { description: 'Tag names to read' })),
    }),
    async execute(_toolCallId, params) {
      const ip = String(params.ip ?? '').trim()
      if (!ip) return toolError('plc_comms_cip_tag_read requires ip.')
      const tags = Array.isArray(params.tags) ? params.tags.map((t) => String(t)).filter(Boolean) : []
      if (!tags.length) return toolError('plc_comms_cip_tag_read requires a non-empty tags array.')
      const args = ['--ip', ip, '--tags-json', JSON.stringify(tags)]
      return runPythonScript('cip_tag_read.py', args, 120_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_cip_tag_write',
    label: 'PLC comms CIP tag write',
    description:
      'Write one or many Logix tags to a PLC via ciplogix. GATED by the operator-managed download allowlist — the target IP must be present and enabled. Pass an array of {tag, value} objects. No SDK required.',
    parameters: Type.Object({
      ip: Type.String({ description: 'Controller IPv4 address — must be in the allowlist' }),
      writes: Type.Array(
        Type.Object({
          tag: Type.String({ description: 'Tag name (pycomm3 syntax; program scope via Program:..MyTag)' }),
          value: Type.Unknown({ description: 'Value (JSON type; bool/int/float/str/list)' }),
        }),
        { description: 'Tag writes to perform' },
      ),
      dry_run: Type.Optional(Type.Boolean({ description: 'Validate against allowlist but do not send to PLC' })),
    }),
    async execute(_toolCallId, params) {
      const ip = String(params.ip ?? '').trim()
      if (!ip) return toolError('plc_comms_cip_tag_write requires ip.')
      const writes = Array.isArray(params.writes) ? params.writes : []
      if (!writes.length) return toolError('plc_comms_cip_tag_write requires a non-empty writes array.')
      const args = ['--ip', ip, '--writes-json', JSON.stringify(writes)]
      if (params.dry_run === true) args.push('--dry-run')
      return runPythonScript('cip_tag_write.py', args, 120_000)
    },
  })

  // ---- OPC UA client tools (asyncua) -------------------------------------------

  pi.registerTool({
    name: 'plc_comms_opcua_status',
    label: 'PLC comms OPC UA status',
    description:
      'Probe an OPC UA server (read-only): endpoints, security policies, namespaces, tags namespace index, server status. Use to confirm the server is reachable and discover the tags namespace before browse/read/write. Requires the PLC OPC UA server to be enabled (Studio 5000 CIP Security → OPC UA Server).',
    parameters: Type.Object({
      ip: Type.Optional(Type.String({ description: 'Controller IP (endpoint opc.tcp://IP:4840)' })),
      endpoint: Type.Optional(Type.String({ description: 'Full opc.tcp:// endpoint (overrides ip)' })),
      port: Type.Optional(Type.Number({ description: 'OPC UA port (default 4840)' })),
    }),
    async execute(_toolCallId, params) {
      const endpoint = String(params.endpoint ?? '').trim()
      const ip = String(params.ip ?? '').trim()
      if (!endpoint && !ip) return toolError('plc_comms_opcua_status requires ip and/or endpoint.')
      const args = ['--ip', ip || '0']
      if (endpoint) args.push('--endpoint', endpoint)
      if (typeof params.port === 'number') args.push('--port', String(params.port))
      return runPythonScript('opcua_status.py', args, 60_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_opcua_browse',
    label: 'PLC comms OPC UA browse',
    description:
      'Browse an OPC UA address space node and return its children (read-only): node id, browse/display name, node class, data type, and value for Variable nodes. Default starting node is the Objects folder. Pass a node-id spec (ns=2;s=...) to browse a specific node.',
    parameters: Type.Object({
      ip: Type.Optional(Type.String({ description: 'Controller IP' })),
      endpoint: Type.Optional(Type.String({ description: 'Full opc.tcp:// endpoint (overrides ip)' })),
      node: Type.Optional(Type.String({ description: 'Node-id spec to browse (default Objects folder)' })),
      namespace: Type.Optional(Type.Number({ description: 'Default ns for bare node specs (auto: Tags ns)' })),
    }),
    async execute(_toolCallId, params) {
      const endpoint = String(params.endpoint ?? '').trim()
      const ip = String(params.ip ?? '').trim()
      if (!endpoint && !ip) return toolError('plc_comms_opcua_browse requires ip and/or endpoint.')
      const args = ['--ip', ip || '0']
      if (endpoint) args.push('--endpoint', endpoint)
      const node = String(params.node ?? '').trim()
      if (node) args.push('--node', node)
      if (typeof params.namespace === 'number') args.push('--namespace', String(params.namespace))
      return runPythonScript('opcua_browse.py', args, 90_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_opcua_tag_list',
    label: 'PLC comms OPC UA tag list',
    description:
      'List OPC UA tags by recursively browsing the controller Tags namespace (read-only). Returns tag node id, browse path, tag path (string NodeId identifier), data type, array dimensions. Optional substring filter. Capped by max-depth/max-nodes. Requires the OPC UA server enabled on the PLC.',
    parameters: Type.Object({
      ip: Type.Optional(Type.String({ description: 'Controller IP' })),
      endpoint: Type.Optional(Type.String({ description: 'Full opc.tcp:// endpoint (overrides ip)' })),
      filter: Type.Optional(Type.String({ description: 'Case-insensitive substring filter on tag/browse name' })),
      max_depth: Type.Optional(Type.Number({ description: 'Max browse depth (default 4)' })),
      max_nodes: Type.Optional(Type.Number({ description: 'Cap on collected tag nodes (default 2000)' })),
    }),
    async execute(_toolCallId, params) {
      const endpoint = String(params.endpoint ?? '').trim()
      const ip = String(params.ip ?? '').trim()
      if (!endpoint && !ip) return toolError('plc_comms_opcua_tag_list requires ip and/or endpoint.')
      const args = ['--ip', ip || '0']
      if (endpoint) args.push('--endpoint', endpoint)
      const filter = String(params.filter ?? '').trim()
      if (filter) args.push('--filter', filter)
      if (typeof params.max_depth === 'number') args.push('--max-depth', String(params.max_depth))
      if (typeof params.max_nodes === 'number') args.push('--max-nodes', String(params.max_nodes))
      return runPythonScript('opcua_tag_list.py', args, 180_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_opcua_read',
    label: 'PLC comms OPC UA read',
    description:
      'Read one or many OPC UA nodes by node-id spec or tag path (read-only). Bare names resolve to the Tags namespace (ns=2 on Rockwell). Returns per-node value, data type, source timestamp. Requires the OPC UA server enabled on the PLC.',
    parameters: Type.Object({
      ip: Type.Optional(Type.String({ description: 'Controller IP' })),
      endpoint: Type.Optional(Type.String({ description: 'Full opc.tcp:// endpoint (overrides ip)' })),
      nodes: Type.Array(Type.String(), { description: 'Node-id specs or bare tag names to read' }),
      namespace: Type.Optional(Type.Number({ description: 'Default ns for bare names (auto: Tags ns)' })),
    }),
    async execute(_toolCallId, params) {
      const endpoint = String(params.endpoint ?? '').trim()
      const ip = String(params.ip ?? '').trim()
      if (!endpoint && !ip) return toolError('plc_comms_opcua_read requires ip and/or endpoint.')
      const nodes = Array.isArray(params.nodes) ? params.nodes.map((n) => String(n)).filter(Boolean) : []
      if (!nodes.length) return toolError('plc_comms_opcua_read requires a non-empty nodes array.')
      const args = ['--ip', ip || '0', '--nodes-json', JSON.stringify(nodes)]
      if (endpoint) args.push('--endpoint', endpoint)
      if (typeof params.namespace === 'number') args.push('--namespace', String(params.namespace))
      return runPythonScript('opcua_read.py', args, 90_000)
    },
  })

  pi.registerTool({
    name: 'plc_comms_opcua_write',
    label: 'PLC comms OPC UA write',
    description:
      'Write one or many OPC UA nodes by node-id spec or tag path. GATED by the operator-managed download allowlist (endpoint host IP must be present and enabled). Pass an array of {node, value, variant_type?}. variant_type (e.g. Int32, Boolean, Float) is optional — asyncua infers from the Python value for common scalars. Requires the OPC UA server enabled on the PLC.',
    parameters: Type.Object({
      ip: Type.Optional(Type.String({ description: 'Controller IP — must be in the allowlist' })),
      endpoint: Type.Optional(Type.String({ description: 'Full opc.tcp:// endpoint (overrides ip)' })),
      writes: Type.Array(
        Type.Object({
          node: Type.String({ description: 'Node-id spec or bare tag name (Tags ns)' }),
          value: Type.Unknown({ description: 'Value (JSON type)' }),
          variant_type: Type.Optional(
            Type.String({ description: 'asyncua VariantType name, e.g. Int32, Boolean, Float, Double, String' }),
          ),
        }),
        { description: 'OPC UA node writes to perform' },
      ),
      namespace: Type.Optional(Type.Number({ description: 'Default ns for bare names (auto: Tags ns)' })),
      dry_run: Type.Optional(Type.Boolean({ description: 'Validate against allowlist but do not send' })),
    }),
    async execute(_toolCallId, params) {
      const endpoint = String(params.endpoint ?? '').trim()
      const ip = String(params.ip ?? '').trim()
      if (!endpoint && !ip) return toolError('plc_comms_opcua_write requires ip and/or endpoint.')
      const writes = Array.isArray(params.writes) ? params.writes : []
      if (!writes.length) return toolError('plc_comms_opcua_write requires a non-empty writes array.')
      const args = ['--ip', ip || '0', '--writes-json', JSON.stringify(writes)]
      if (endpoint) args.push('--endpoint', endpoint)
      if (typeof params.namespace === 'number') args.push('--namespace', String(params.namespace))
      if (params.dry_run === true) args.push('--dry-run')
      return runPythonScript('opcua_write.py', args, 90_000)
    },
  })
}