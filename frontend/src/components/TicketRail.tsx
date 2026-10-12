import type { KeyboardEvent } from 'react'
import type { Ticket } from '../types'
import { TicketStamp } from './Stamp'

const TYPE_LABELS: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Price override',
}

export const ticketTypeLabel = (type: string) => TYPE_LABELS[type] ?? type

export function itemLine(t: Ticket): string | null {
  if (t.sku) return `${t.sku} · size ${t.size ?? '—'} · qty ${t.qty ?? '—'}`
  if (t.lease_id != null) return `Lease ${t.lease_id}`
  return null
}

interface Props {
  tickets: Ticket[] | null
  selectedId: number | null
  runningIds: Set<number>
  onSelect: (id: number) => void
}

export function TicketRail({ tickets, selectedId, runningIds, onSelect }: Props) {
  // Arrow keys move between stubs, like a listbox.
  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!tickets || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return
    e.preventDefault()
    const next = (index + (e.key === 'ArrowDown' ? 1 : -1) + tickets.length) % tickets.length
    onSelect(tickets[next].id)
    document.getElementById(`stub-${tickets[next].id}`)?.focus()
  }

  return (
    <nav className="rail" aria-label="Tickets">
      <h2 className="rail-title">Ticket spike</h2>
      {tickets === null ? (
        <div className="stub stub-skeleton" aria-busy="true">Loading tickets…</div>
      ) : tickets.length === 0 ? (
        <p className="empty">No tickets in the database.</p>
      ) : (
        <ul className="stubs">
          {tickets.map((t, i) => (
            <li key={t.id}>
              <button
                id={`stub-${t.id}`}
                type="button"
                className={`stub${t.id === selectedId ? ' stub-selected' : ''}${t.resolved ? ' stub-resolved' : ''}`}
                aria-current={t.id === selectedId ? 'true' : undefined}
                onClick={() => onSelect(t.id)}
                onKeyDown={(e) => onKeyDown(e, i)}
              >
                <span className="stub-top">
                  <span className="stub-no">#{t.id}</span>
                  <span className="stub-type">{ticketTypeLabel(t.type)}</span>
                </span>
                <span className="stub-subject">{t.subject}</span>
                {itemLine(t) && <span className="stub-item">{itemLine(t)}</span>}
                <span className="stub-bottom">
                  <TicketStamp ticket={t} />
                  {runningIds.has(t.id) && <span className="stub-live">agents working…</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  )
}
