// Types mirror backend/models.py (the FastAPI response models from Problem 7).

export type TicketStatus = 'open' | 'pending_approval' | 'closed' | string

export interface Ticket {
  id: number
  type: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: TicketStatus
  resolved: boolean
  created_at: string
  active_run_id: string | null
}

export type RunState = 'running' | 'completed' | 'needs_human' | 'blocked' | 'failed' | 'limit_exceeded'

export interface Finding {
  fact: string
  source: string
}

export interface ApprovalRequest {
  action: string
  action_id: number | null
  tool: string | null
  ref_id: number | null
  amount: number | null
  reason: string
}

export interface AgentReport {
  role: AgentRole
  ticket_id: number
  status: 'completed' | 'needs_human' | 'blocked' | 'failed'
  summary: string
  findings: Finding[]
  actions_taken: string[]
  approvals_needed: ApprovalRequest[]
  missing_info: string[]
  customer_reply_draft: string | null
}

export interface UsageSummary {
  requests: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  tool_calls: number
}

export interface TicketRunResult {
  run_id: string
  ticket_id: number
  model: string
  status: RunState
  boss_report: AgentReport | null
  usage: UsageSummary
  seconds: number
  error: string | null
}

export interface RunInfo {
  run_id: string
  ticket_id: number
  status: RunState
  instructions: string | null
  started_at: string
  finished_at: string | null
  error: string | null
  result: TicketRunResult | null
}

/** One entry of output/audit_trail.json, as returned by GET /api/events. */
export interface AuditEvent {
  event_id: number
  event: string
  ts?: string
  run_id?: string
  seq?: number
  t_ms?: number
  ticket_id?: number | null
  agent?: string
  [key: string]: unknown
}

export interface EventsResponse {
  events: AuditEvent[]
  next_cursor: number
  total: number
}

export type PendingKind = 'invoice_payment' | 'rent_payment' | 'restock_purchase'

export interface PendingAction {
  id: number
  kind: PendingKind
  ticket_id: number | null
  ref_id: number
  account: string | null
  amount: number
  due_date: string | null
  sku: string | null
  size: string | null
  qty: number | null
  reason: string
  prepared_by: string
  prepared_at: string
  status: 'pending' | 'executed' | 'rejected'
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  result: Record<string, unknown> | null
}

export interface ApprovalResponse {
  action: PendingAction
  result: Record<string, unknown> | null
  checking_balance: number | null
}

export interface Cash {
  account: string
  balance: number
  date: string
}

export type AgentRole = 'boss' | 'inventory' | 'accounting' | 'facilities' | 'customer_service'
