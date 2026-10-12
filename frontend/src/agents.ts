import type { AgentRole } from './types'

export interface AgentMeta {
  role: AgentRole
  name: string
  station: string // where they sit at the desk
  duty: string // what they handle
  initials: string
}

/** The five agents, in the order they appear on the desk. Names and duties match backend/prompts/*.md. */
export const AGENTS: AgentMeta[] = [
  { role: 'boss', name: 'Boss', station: 'Desk lead', duty: 'Routes the ticket, decides, sets status', initials: 'BO' },
  { role: 'inventory', name: 'Inventory', station: 'Stockroom', duty: 'Stock, shortfalls, vendors, restock orders', initials: 'IN' },
  { role: 'accounting', name: 'Accounting', station: 'Ledger', duty: 'Invoices, cash, margins, payments', initials: 'AC' },
  { role: 'facilities', name: 'Facilities', station: 'Premises', duty: 'Lease, landlord, rent timing', initials: 'FA' },
  { role: 'customer_service', name: 'Customer Service', station: 'Front counter', duty: 'Drafts replies to requesters', initials: 'CS' },
]

export const AGENT_BY_ROLE = Object.fromEntries(AGENTS.map((a) => [a.role, a])) as Record<AgentRole, AgentMeta>

export function isAgentRole(value: unknown): value is AgentRole {
  return typeof value === 'string' && value in AGENT_BY_ROLE
}

/** Display name for any audit `agent` value, including the runner and human approvers. */
export function actorName(agent: unknown): string {
  if (isAgentRole(agent)) return AGENT_BY_ROLE[agent].name
  if (agent === 'runner') return 'Desk runner'
  if (agent === 'human') return 'Human approver'
  return String(agent ?? 'unknown')
}
