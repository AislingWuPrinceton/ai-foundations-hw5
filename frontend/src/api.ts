import type {
  ApprovalResponse,
  AuditEvent,
  Cash,
  EventsResponse,
  PendingAction,
  RunInfo,
  Ticket,
} from './types'

export const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

/** An HTTP error from the backend (status > 0) or a network failure (status 0). */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
  get isConnection(): boolean {
    return this.status === 0
  }
}

function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? JSON.stringify(d)).join('; ')
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
  return JSON.stringify(detail)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    })
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_BASE}. Is it running?`)
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    throw new ApiError(res.status, body?.detail !== undefined ? detailText(body.detail) : `HTTP ${res.status}`)
  }
  return body as T
}

export const api = {
  tickets: () => request<{ tickets: Ticket[] }>('/api/tickets').then((r) => r.tickets),
  startRun: (ticketId: number, instructions?: string) =>
    request<RunInfo>(`/api/tickets/${ticketId}/run`, {
      method: 'POST',
      body: JSON.stringify({ instructions: instructions?.trim() || null }),
    }),
  run: (runId: string) => request<RunInfo>(`/api/runs/${encodeURIComponent(runId)}`),
  cash: () => request<Cash>('/api/cash'),
  pendingActions: () =>
    request<{ actions: PendingAction[] }>('/api/pending-actions?status=pending').then((r) => r.actions),
  approve: (actionId: number, approvedBy: string, confirmAmount: number) =>
    request<ApprovalResponse>(`/api/pending-actions/${actionId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved_by: approvedBy, confirm_amount: confirmAmount }),
    }),

  reject: (actionId: number, rejectedBy: string, note: string) =>
    request<ApprovalResponse>(`/api/pending-actions/${actionId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ rejected_by: rejectedBy, note }),
    }),

  /** Every audit event for one ticket after `after`, following pages until caught up. */
  async ticketEvents(ticketId: number, after: number): Promise<{ events: AuditEvent[]; cursor: number }> {
    const events: AuditEvent[] = []
    let cursor = after
    for (let page = 0; page < 50; page++) {
      const r = await request<EventsResponse>(`/api/events?ticket_id=${ticketId}&after=${cursor}&limit=500`)
      events.push(...r.events)
      cursor = r.next_cursor
      if (cursor >= r.total - 1) break
    }
    return { events, cursor }
  },
}
