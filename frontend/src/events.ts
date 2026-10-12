// Turns raw audit events (GET /api/events) into runs, feed items, and agent summaries.
// Everything shown comes from these events; nothing is invented on the client.

import { actorName, isAgentRole } from './agents'
import type { AgentReport, AgentRole, AuditEvent } from './types'

export interface RunGroup {
  runId: string
  ticketId: number
  events: AuditEvent[] // sorted by event_id
  startedTs?: string
  status: string // from run_end, else "running" / "unknown"
  summary?: string | null
  usage?: Record<string, number>
}

const isRunId = (id?: string) => !!id && !id.startsWith('approval-') && !id.startsWith('human-')

/** Agent-team runs for one ticket, oldest first. Human approval events are kept out of runs. */
export function groupRuns(events: AuditEvent[]): RunGroup[] {
  const byRun = new Map<string, AuditEvent[]>()
  for (const e of events) {
    if (!isRunId(e.run_id)) continue
    const list = byRun.get(e.run_id!) ?? []
    list.push(e)
    byRun.set(e.run_id!, list)
  }
  const runs: RunGroup[] = []
  for (const [runId, list] of byRun) {
    list.sort((a, b) => a.event_id - b.event_id)
    const end = list.find((e) => e.event === 'run_end')
    runs.push({
      runId,
      ticketId: Number(list[0].ticket_id),
      events: list,
      startedTs: list[0].ts,
      status: end ? String(end.status) : 'running',
      summary: (end?.summary as string | null | undefined) ?? null,
      usage: end?.usage as Record<string, number> | undefined,
    })
  }
  return runs.sort((a, b) => a.events[0].event_id - b.events[0].event_id)
}

export function humanEvents(events: AuditEvent[]): AuditEvent[] {
  return events.filter((e) => e.agent === 'human').sort((a, b) => a.event_id - b.event_id)
}

// ------------------------------------------------------------------ feed

export type FeedTone = 'info' | 'message' | 'tool' | 'result' | 'delegate' | 'action' | 'warn' | 'error' | 'done'

export interface FeedItem {
  id: number
  actor: string // audit agent value
  tone: FeedTone
  title: string
  body?: string
  detail?: string // collapsible raw content
  tMs?: number
}

const money = (n: unknown) =>
  typeof n === 'number' ? n.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : String(n)

const argText = (args: unknown) =>
  args && typeof args === 'object'
    ? Object.entries(args as Record<string, unknown>)
        .map(([k, v]) => `${k}=${typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}`)
        .join(', ')
    : ''

function pretty(raw: unknown): string {
  if (typeof raw !== 'string') return JSON.stringify(raw, null, 2)
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function resultHeadline(raw: unknown): string {
  try {
    const r = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (r && typeof r === 'object') {
      const o = r as Record<string, unknown>
      if (o.ok === false || o.found === false) return `refused: ${String(o.error ?? 'error')}`
      if (o.ok === true && o.action) return `stored pending action #${(o.action as { id: number }).id}`
      return 'returned data'
    }
  } catch {
    /* clipped JSON; fall through */
  }
  return 'returned data'
}

const roleName = (r: unknown) => actorName(r)

/** One feed item per meaningful event; low-level loop plumbing is skipped. */
export function toFeedItem(e: AuditEvent): FeedItem | null {
  const base = { id: e.event_id, actor: String(e.agent ?? ''), tMs: e.t_ms }
  switch (e.event) {
    case 'run_start':
      return {
        ...base,
        tone: 'info',
        title: `Run started on ${String(e.model ?? 'the model')}`,
        body: e.human_instructions ? `Human decisions sent with this run: ${String(e.human_instructions)}` : undefined,
      }
    case 'agent_start':
      return { ...base, tone: 'info', title: `${roleName(e.agent)} picked up the ticket`, body: depthText(e) }
    case 'agent_step': {
      if (e.kind === 'model_response') {
        const text = String(e.text ?? '').trim()
        const calls = (e.tool_calls as { tool: string; args: unknown }[] | undefined) ?? []
        const plain = calls.filter((c) => c.tool !== 'delegate' && !c.tool.startsWith('final_result'))
        if (!text && plain.length === 0) return null
        return {
          ...base,
          tone: 'message',
          title: text ? 'said' : 'decided to use tools',
          body: text || plain.map((c) => `${c.tool}(${argText(c.args)})`).join('\n'),
        }
      }
      if (e.kind === 'agent_output') {
        const out = e.output as AgentReport | undefined
        if (!out?.summary) return null
        return { ...base, tone: 'done', title: `filed report — ${out.status.replace('_', ' ')}`, body: out.summary }
      }
      return null
    }
    case 'mcp_tool_call':
      return { ...base, tone: 'tool', title: `called MCP tool ${String(e.tool)}`, body: argText(e.args) || undefined }
    case 'mcp_tool_result':
      return {
        ...base,
        tone: e.ok === false ? 'warn' : 'result',
        title: `${String(e.tool)} ${resultHeadline(e.result)}`,
        detail: pretty(e.result),
      }
    case 'mcp_tool_error':
      return { ...base, tone: 'error', title: `${String(e.tool)} failed`, body: String(e.error ?? '') }
    case 'delegation_start':
      return {
        ...base,
        tone: 'delegate',
        title: `delegated to ${roleName(e.to_agent)}`,
        body: String(e.task ?? ''),
        detail: Array.isArray(e.findings) && e.findings.length ? `Findings passed:\n• ${e.findings.join('\n• ')}` : undefined,
      }
    case 'delegation_end':
      return {
        ...base,
        tone: e.status === 'error' ? 'error' : 'delegate',
        title: `${roleName(e.to_agent)} reported back — ${String(e.status ?? '').replace('_', ' ')}`,
        body: String(e.summary ?? e.error ?? ''),
      }
    case 'delegation_refused':
      return { ...base, tone: 'warn', title: `delegation to ${roleName(e.to_agent)} refused`, body: String(e.reason ?? '') }
    case 'pending_action_prepared':
      return {
        ...base,
        tone: 'action',
        title: `prepared ${kindLabel(e.kind)} #${String(e.action_id)} for ${money(e.amount)}`,
        body: e.already_pending ? 'Already pending — no duplicate created.' : 'Waiting for a human to approve it.',
      }
    case 'guardrail_block':
      return { ...base, tone: 'warn', title: 'guardrail stopped an action', body: String(e.reason ?? '') }
    case 'duplicate_write_skipped':
      return { ...base, tone: 'info', title: `skipped a repeat ${String(e.tool)}`, body: String(e.reason ?? '') || undefined }
    case 'limit_exceeded':
      return { ...base, tone: 'error', title: 'run stopped by a limit', body: String(e.reason ?? '') }
    case 'run_error':
      return { ...base, tone: 'error', title: 'run failed', body: String(e.error ?? '') }
    case 'run_end': {
      const u = e.usage as Record<string, number> | undefined
      return {
        ...base,
        tone: e.status === 'failed' || e.status === 'limit_exceeded' ? 'error' : 'done',
        title: `Run finished — ${String(e.status).replace('_', ' ')}`,
        body: u ? `${u.requests} model requests · ${u.total_tokens?.toLocaleString()} tokens · ${u.tool_calls} tool calls` : undefined,
      }
    }
    default:
      return null
  }
}

function depthText(e: AuditEvent): string | undefined {
  const chain = e.chain as string[] | undefined
  return chain && chain.length > 1 ? `via ${chain.map(roleName).join(' → ')}` : undefined
}

export function kindLabel(kind: unknown): string {
  return kind === 'invoice_payment' ? 'invoice payment' : kind === 'rent_payment' ? 'rent payment'
    : kind === 'restock_purchase' ? 'restock purchase' : String(kind)
}

// ------------------------------------------------------------------ agent summaries

export type AgentState = 'idle' | 'working' | 'done'

export interface AgentActivity {
  role: AgentRole
  state: AgentState
  involved: boolean
  report?: AgentReport
  tools: { name: string; count: number; failed: number }[]
  delegatedTo: AgentRole[]
  delegatedFrom: AgentRole[]
  prepared: { id: number; kind: string; amount: number }[]
  lastLine?: string
}

/** What each agent did in one run, built only from that run's audit events. */
export function agentActivity(run: RunGroup | undefined, role: AgentRole): AgentActivity {
  const a: AgentActivity = { role, state: 'idle', involved: false, tools: [], delegatedTo: [], delegatedFrom: [], prepared: [] }
  if (!run) return a
  const tools = new Map<string, { count: number; failed: number }>()
  let open = 0
  for (const e of run.events) {
    if (e.event === 'delegation_start' && e.to_agent === role && isAgentRole(e.agent)) {
      if (!a.delegatedFrom.includes(e.agent)) a.delegatedFrom.push(e.agent)
    }
    if (e.agent !== role) continue
    a.involved = true
    switch (e.event) {
      case 'agent_start':
        open++
        a.state = 'working'
        break
      case 'agent_end':
        open = Math.max(0, open - 1)
        if (open === 0) a.state = 'done'
        break
      case 'mcp_tool_call': {
        const t = tools.get(String(e.tool)) ?? { count: 0, failed: 0 }
        t.count++
        tools.set(String(e.tool), t)
        a.lastLine = `Called ${String(e.tool)}`
        break
      }
      case 'mcp_tool_result':
        if (e.ok === false) tools.get(String(e.tool))!.failed++
        break
      case 'delegation_start':
        if (isAgentRole(e.to_agent) && !a.delegatedTo.includes(e.to_agent)) a.delegatedTo.push(e.to_agent)
        a.lastLine = `Delegated to ${roleName(e.to_agent)}`
        break
      case 'pending_action_prepared':
        a.prepared.push({ id: Number(e.action_id), kind: String(e.kind), amount: Number(e.amount) })
        break
      case 'agent_step':
        if (e.kind === 'model_response' && String(e.text ?? '').trim()) a.lastLine = String(e.text).trim()
        if (e.kind === 'agent_output' && e.output) a.report = e.output as AgentReport
        break
    }
  }
  a.tools = [...tools].map(([name, t]) => ({ name, ...t }))
  if (run.status !== 'running' && a.state === 'working') a.state = 'done' // run ended mid-step (limit/error)
  return a
}
