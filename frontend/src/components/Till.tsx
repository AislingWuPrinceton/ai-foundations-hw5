import { useEffect, useRef, useState, type FormEvent } from 'react'
import { actorName } from '../agents'
import { kindLabel } from '../events'
import type { AuditEvent, Cash, PendingAction } from '../types'
import { Glyph } from './Glyph'

const money = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function actionTarget(a: PendingAction): string {
  if (a.kind === 'invoice_payment') return `Invoice ${a.ref_id} · from ${a.account}`
  if (a.kind === 'rent_payment') return `Lease ${a.ref_id} rent due ${a.due_date} · from ${a.account}`
  return `Vendor ${a.ref_id} · ${a.qty} × ${a.sku} size ${a.size}`
}

interface TillProps {
  cash: Cash | null
  cashError: string | null
  cashFlash: boolean
  pending: PendingAction[] | null
  pendingError: string | null
  approvingId: number | null
  approvalError: { id: number; message: string } | null
  approvalNotice: string | null
  history: AuditEvent[]
  onApprove: (action: PendingAction, approvedBy: string) => Promise<boolean>
  onReject: (action: PendingAction, rejectedBy: string, note: string) => Promise<boolean>
  onRefresh: () => void
}

export function Till(props: TillProps) {
  const { cash, cashError, cashFlash, pending, pendingError, approvingId, approvalError, approvalNotice, history } = props
  const [reviewing, setReviewing] = useState<PendingAction | null>(null)

  return (
    <aside id="till" className="till" aria-label="Cash and approvals">
      <section className="drawer" aria-labelledby="drawer-title">
        <h2 id="drawer-title" className="drawer-title">Cash drawer</h2>
        {cashError ? (
          <p className="drawer-error" role="alert">{cashError}</p>
        ) : cash === null ? (
          <p className="drawer-amount drawer-loading" aria-busy="true">…</p>
        ) : (
          <>
            <p className={`drawer-amount${cashFlash ? ' flash' : ''}`} aria-live="polite">
              <span className="sr-only">Checking balance: </span>
              {money(cash.balance)}
            </p>
            <p className="drawer-meta">checking · as of {cash.date} · from the backend</p>
          </>
        )}
        <button type="button" className="btn btn-ghost-light" onClick={props.onRefresh}>Recount</button>
      </section>

      <section className="slips" aria-labelledby="slips-title">
        <h2 id="slips-title" className="section-title">Awaiting your signature</h2>
        <p className="slips-hint">Agents can only prepare these. Nothing is paid or ordered until a person approves it here.</p>
        {approvalNotice && <p className="notice" role="status">{approvalNotice}</p>}
        {pendingError ? (
          <p className="error-box" role="alert">{pendingError}</p>
        ) : pending === null ? (
          <p className="empty" aria-busy="true">Loading pending actions…</p>
        ) : pending.length === 0 ? (
          <p className="empty">No payments or purchases are waiting.</p>
        ) : (
          <ul className="slip-list">
            {pending.map((a) => (
              <li key={a.id} className={`slip slip-${a.kind}`}>
                <div className="slip-top">
                  <span className="slip-kind">{kindLabel(a.kind)}</span>
                  <span className="slip-no">#{a.id}</span>
                </div>
                <p className="slip-amount">{money(a.amount)}</p>
                <p className="slip-purpose"><b>Purpose:</b> {a.reason}</p>
                <p className="slip-meta">{actionTarget(a)}</p>
                <p className="slip-meta">
                  Ticket {a.ticket_id ?? '—'} · prepared by {actorName(a.prepared_by)}
                </p>
                {approvalError?.id === a.id && <p className="error-box" role="alert">{approvalError.message}</p>}
                <button
                  type="button"
                  className="btn btn-approve"
                  disabled={approvingId !== null}
                  onClick={() => setReviewing(a)}
                >
                  {approvingId === a.id ? 'Working…' : 'Review & approve / reject'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {history.length > 0 && (
        <section className="history" aria-labelledby="history-title">
          <h2 id="history-title" className="section-title">Signed on this ticket</h2>
          <ul>
            {history.map((e) => (
              <li key={e.event_id}>
                <Glyph role="human" size={14} />
                <span>{historyLine(e)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {reviewing && (
        <ApproveDialog
          action={reviewing}
          busy={approvingId === reviewing.id}
          onCancel={() => setReviewing(null)}
          onConfirm={async (name) => {
            const ok = await props.onApprove(reviewing, name)
            if (ok) setReviewing(null)
          }}
          onReject={async (name) => {
            const ok = await props.onReject(reviewing, name, 'Rejected on the dashboard')
            if (ok) setReviewing(null)
          }}
          error={approvalError?.id === reviewing.id ? approvalError.message : null}
        />
      )}
    </aside>
  )
}

function historyLine(e: AuditEvent): string {
  const who = String(e.approved_by ?? e.rejected_by ?? 'someone')
  const amount = typeof e.amount === 'number' ? ` ${money(e.amount)}` : ''
  switch (e.event) {
    case 'approval_requested': return `${who} asked to approve action #${e.action_id}${amount}`
    case 'approval_executed': return `${who} approved action #${e.action_id}; checking now ${money(Number(e.checking_balance_after))}`
    case 'approval_refused': return `Approval of action #${e.action_id} refused: ${String(e.error)}`
    case 'action_rejected': return `${who} rejected action #${e.action_id}${amount}`
    default: return e.event
  }
}

interface DialogProps {
  action: PendingAction
  busy: boolean
  error: string | null
  onCancel: () => void
  onConfirm: (approvedBy: string) => void
  onReject: (rejectedBy: string) => void
}

function ApproveDialog({ action, busy, error, onCancel, onConfirm, onReject }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState('')

  useEffect(() => {
    const d = ref.current
    if (d && !d.open) d.showModal() // native modal: traps focus, Esc closes
  }, [])

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!busy && name.trim()) onConfirm(name.trim())
  }

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="dlg-title" onCancel={(e) => { e.preventDefault(); if (!busy) onCancel() }}>
      <form onSubmit={submit}>
        <h2 id="dlg-title">Approve {kindLabel(action.kind)} #{action.id}</h2>
        <p className="dialog-amount">{money(action.amount)}</p>
        <p>{action.reason}</p>
        <p className="slip-meta">{actionTarget(action)} · ticket {action.ticket_id ?? '—'}</p>
        <p className="dialog-warn">
          {action.kind === 'restock_purchase'
            ? 'This records a purchase order with the vendor. The server re-checks the price and refuses if the vendor still has an open invoice.'
            : 'This moves real money out of checking. The server re-checks the amount and the records and refuses if cash would go negative.'}
        </p>
        <label className="field">
          <span>Sign as (your name)</span>
          <input
            autoFocus
            required
            maxLength={80}
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={busy}
            autoComplete="name"
          />
        </label>
        {error && <p className="error-box" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn btn-plain" onClick={onCancel} disabled={busy}>Cancel</button>
          <button
            type="button"
            className="btn btn-reject"
            disabled={busy || !name.trim()}
            onClick={() => { if (!busy && name.trim()) onReject(name.trim()) }}
          >
            Reject
          </button>
          <button type="submit" className="btn btn-approve" disabled={busy || !name.trim()}>
            {busy ? 'Approving…' : `Approve ${money(action.amount)}`}
          </button>
        </div>
      </form>
    </dialog>
  )
}
