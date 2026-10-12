import type { Ticket } from '../types'

/** Rubber-stamp status. "Resolved" appears only when the backend says resolved = true. */
export function TicketStamp({ ticket }: { ticket: Pick<Ticket, 'status' | 'resolved'> }) {
  if (ticket.resolved) return <span className="stamp stamp-resolved">✓ Resolved</span>
  if (ticket.status === 'pending_approval') return <span className="stamp stamp-pending">⏸ Awaiting approval</span>
  if (ticket.status === 'open') return <span className="stamp stamp-open">● Open</span>
  return <span className="stamp">{ticket.status}</span>
}

const RUN_LABELS: Record<string, string> = {
  running: 'Running',
  completed: 'Finished · completed',
  needs_human: 'Finished · needs a human',
  blocked: 'Finished · blocked',
  failed: 'Failed',
  limit_exceeded: 'Stopped · limit reached',
  incomplete: 'Incomplete (no end event)',
}

export function RunBadge({ status }: { status: string }) {
  const tone = status === 'running' ? 'live' : status === 'failed' || status === 'limit_exceeded' ? 'bad'
    : status === 'completed' ? 'good' : 'warn'
  return (
    <span className={`run-badge run-${tone}`}>
      {status === 'running' && <span className="pulse" aria-hidden="true" />}
      {RUN_LABELS[status] ?? status}
    </span>
  )
}
