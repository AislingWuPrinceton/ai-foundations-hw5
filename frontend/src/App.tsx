import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE, ApiError, api } from './api'
import { AGENTS } from './agents'
import { agentActivity, groupRuns, humanEvents, toFeedItem, type FeedItem } from './events'
import type { AuditEvent, Cash, PendingAction, RunInfo, Ticket } from './types'
import { ActivityFeed } from './components/ActivityFeed'
import { AgentBoard } from './components/AgentBoard'
import { RunBadge, TicketStamp } from './components/Stamp'
import { TicketRail, itemLine, ticketTypeLabel } from './components/TicketRail'
import { Till } from './components/Till'

const POLL_MS = 1500
const HIDDEN_POLL_MS = 10_000 // background tab: keep tracking the run, but slowly

interface TicketEvents {
  events: AuditEvent[]
  cursor: number
  loaded: boolean
}

const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))

export default function App() {
  const [tickets, setTickets] = useState<Ticket[] | null>(null)
  const [connError, setConnError] = useState<string | null>(null)
  // ?ticket=103 preselects a ticket (handy for links and screenshots); it never starts a run.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const t = Number(new URLSearchParams(window.location.search).get('ticket'))
    return Number.isInteger(t) && t > 0 ? t : null
  })
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [eventsByTicket, setEventsByTicket] = useState<Record<number, TicketEvents>>({})
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [pickedRun, setPickedRun] = useState<Record<number, string>>({})
  const [tracked, setTracked] = useState<Record<number, RunInfo>>({}) // runs started or seen active this session
  const [starting, setStarting] = useState<number | null>(null)
  const [runError, setRunError] = useState<Record<number, string>>({})
  const [cash, setCash] = useState<Cash | null>(null)
  const [cashError, setCashError] = useState<string | null>(null)
  const [cashFlash, setCashFlash] = useState(false)
  const [pending, setPending] = useState<PendingAction[] | null>(null)
  const [pendingError, setPendingError] = useState<string | null>(null)
  const [approvingId, setApprovingId] = useState<number | null>(null)
  const [approvalError, setApprovalError] = useState<{ id: number; message: string } | null>(null)
  const [approvalNotice, setApprovalNotice] = useState<string | null>(null)

  const eventsRef = useRef(eventsByTicket)
  eventsRef.current = eventsByTicket
  const trackedRef = useRef(tracked)
  trackedRef.current = tracked
  const startingRef = useRef(false)
  const approvingRef = useRef(false)

  // ---------------------------------------------------------------- loaders

  const refreshTickets = useCallback(async () => {
    try {
      const list = await api.tickets()
      setTickets(list)
      setConnError(null)
      setSelectedId((cur) => cur ?? list[0]?.id ?? null)
      // Resume tracking any run the backend says is still active (e.g. after a page reload).
      for (const t of list) {
        if (t.active_run_id && trackedRef.current[t.id]?.run_id !== t.active_run_id) {
          api.run(t.active_run_id).then((run) => setTracked((p) => ({ ...p, [t.id]: run }))).catch(() => {})
        }
      }
    } catch (e) {
      setConnError(errText(e))
    }
  }, [])

  const refreshCash = useCallback(async (flash = false) => {
    try {
      setCash(await api.cash())
      setCashError(null)
      if (flash) {
        setCashFlash(true)
        setTimeout(() => setCashFlash(false), 1600)
      }
    } catch (e) {
      setCashError(errText(e))
    }
  }, [])

  const refreshPending = useCallback(async () => {
    try {
      setPending(await api.pendingActions())
      setPendingError(null)
    } catch (e) {
      setPendingError(errText(e))
    }
  }, [])

  /** Pull new audit events for one ticket and merge them, de-duplicated by event_id. */
  const pullEvents = useCallback(async (ticketId: number) => {
    const after = eventsRef.current[ticketId]?.cursor ?? -1
    const { events, cursor } = await api.ticketEvents(ticketId, after)
    setEventsByTicket((prev) => {
      const old = prev[ticketId] ?? { events: [], cursor: -1, loaded: false }
      const seen = new Set(old.events.map((e) => e.event_id))
      const fresh = events.filter((e) => !seen.has(e.event_id))
      return {
        ...prev,
        [ticketId]: {
          events: fresh.length ? [...old.events, ...fresh].sort((a, b) => a.event_id - b.event_id) : old.events,
          cursor: Math.max(old.cursor, cursor),
          loaded: true,
        },
      }
    })
  }, [])

  const refreshAll = useCallback(() => {
    refreshTickets()
    refreshCash()
    refreshPending()
  }, [refreshTickets, refreshCash, refreshPending])

  // Initial load: read-only. Nothing is run or approved on page load.
  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  // Load the selected ticket's history from the audit trail once.
  useEffect(() => {
    if (selectedId === null || eventsRef.current[selectedId]?.loaded) return
    pullEvents(selectedId).then(() => setEventsError(null)).catch((e) => setEventsError(errText(e)))
  }, [selectedId, pullEvents])

  // ---------------------------------------------------------------- polling (only while a run is active)

  const runningKey = Object.values(tracked).filter((r) => r.status === 'running').map((r) => r.run_id).sort().join(',')

  useEffect(() => {
    if (!runningKey) return // nothing running: no polling at all
    let busy = false
    let stopped = false
    let last = 0
    const tick = async (force = false) => {
      if (busy || stopped) return
      if (!force && document.hidden && Date.now() - last < HIDDEN_POLL_MS) return
      busy = true
      last = Date.now()
      try {
        for (const run of Object.values(trackedRef.current).filter((r) => r.status === 'running')) {
          await pullEvents(run.ticket_id)
          let info: RunInfo
          try {
            info = await api.run(run.run_id)
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) {
              // The backend restarted or was reset and no longer knows this run.
              info = { ...run, status: 'failed', error: 'The backend no longer has this run (restarted or reset).' }
            } else throw e
          }
          if (stopped) return
          if (info.status !== 'running') {
            setTracked((p) => ({ ...p, [run.ticket_id]: info }))
            await pullEvents(run.ticket_id) // final events after run_end
            refreshAll() // ticket status, cash, and pending actions come from the backend, not from the run result
          }
        }
        setConnError(null)
        setEventsError(null)
      } catch (e) {
        if (e instanceof ApiError && e.isConnection) setConnError(e.message)
        else setEventsError(errText(e))
      } finally {
        busy = false
      }
    }
    const onVisible = () => { if (!document.hidden) tick(true) }
    tick(true)
    const timer = setInterval(() => tick(), POLL_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [runningKey, pullEvents, refreshAll])

  // ---------------------------------------------------------------- actions

  async function startRun(ticketId: number) {
    if (startingRef.current || tracked[ticketId]?.status === 'running') return // no double starts
    startingRef.current = true
    setStarting(ticketId)
    setRunError((p) => ({ ...p, [ticketId]: '' }))
    try {
      const run = await api.startRun(ticketId, notes[ticketId])
      setTracked((p) => ({ ...p, [ticketId]: run }))
      setPickedRun((p) => ({ ...p, [ticketId]: run.run_id }))
      refreshTickets()
    } catch (e) {
      setRunError((p) => ({ ...p, [ticketId]: errText(e) }))
      if (e instanceof ApiError && e.status === 409) refreshTickets() // picks up the run already in progress
    } finally {
      startingRef.current = false
      setStarting(null)
    }
  }

  async function reject(action: PendingAction, rejectedBy: string, note: string): Promise<boolean> {
    if (approvingRef.current) return false
    approvingRef.current = true
    setApprovingId(action.id)
    setApprovalError(null)
    setApprovalNotice(null)
    try {
      await api.reject(action.id, rejectedBy, note)
      setApprovalNotice(`Rejected #${action.id}. It can no longer execute.`)
      await Promise.all([refreshPending(), refreshTickets()])
      if (action.ticket_id != null && eventsRef.current[action.ticket_id]?.loaded) pullEvents(action.ticket_id).catch(() => {})
      return true
    } catch (e) {
      setApprovalError({ id: action.id, message: errText(e) })
      refreshPending()
      return false
    } finally {
      approvingRef.current = false
      setApprovingId(null)
    }
  }

  async function approve(action: PendingAction, approvedBy: string): Promise<boolean> {
    if (approvingRef.current) return false // no double submissions
    approvingRef.current = true
    setApprovingId(action.id)
    setApprovalError(null)
    setApprovalNotice(null)
    try {
      const res = await api.approve(action.id, approvedBy, action.amount)
      setApprovalNotice(`Approved #${action.id} (${res.action.kind.replace('_', ' ')}). The backend confirmed it executed.`)
      await Promise.all([refreshCash(true), refreshPending(), refreshTickets()])
      if (action.ticket_id != null && eventsRef.current[action.ticket_id]?.loaded) pullEvents(action.ticket_id).catch(() => {})
      return true
    } catch (e) {
      setApprovalError({ id: action.id, message: errText(e) })
      refreshPending() // the action may have changed underneath us
      return false
    } finally {
      approvingRef.current = false
      setApprovingId(null)
    }
  }

  // ---------------------------------------------------------------- derived view

  const selected = tickets?.find((t) => t.id === selectedId) ?? null
  const ticketEvents = selectedId !== null ? eventsByTicket[selectedId] : undefined
  const runs = useMemo(() => groupRuns(ticketEvents?.events ?? []), [ticketEvents])
  const trackedRun = selectedId !== null ? tracked[selectedId] : undefined
  const viewRunId = (selectedId !== null && pickedRun[selectedId]) || trackedRun?.run_id || runs.at(-1)?.runId
  const viewRun = runs.find((r) => r.runId === viewRunId)
  const isLive = !!trackedRun && trackedRun.run_id === viewRunId && trackedRun.status === 'running'
  const viewStatus = isLive ? 'running'
    : trackedRun?.run_id === viewRunId && trackedRun ? trackedRun.status
    : viewRun ? (viewRun.status === 'running' ? 'incomplete' : viewRun.status) : undefined

  const activity = useMemo(() => {
    const run = viewRun && { ...viewRun, status: isLive ? 'running' : viewRun.status === 'running' ? 'incomplete' : viewRun.status }
    return AGENTS.map((a) => agentActivity(run, a.role))
  }, [viewRun, isLive])
  const feed = useMemo(
    () => (viewRun?.events ?? []).map(toFeedItem).filter((x): x is FeedItem => x !== null),
    [viewRun],
  )
  const history = useMemo(() => humanEvents(ticketEvents?.events ?? []), [ticketEvents])
  const runningIds = new Set(Object.values(tracked).filter((r) => r.status === 'running').map((r) => r.ticket_id))
  const runBusy = selected ? starting === selected.id || runningIds.has(selected.id) || !!selected.active_run_id : true

  return (
    <div className="desk">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">CC</span>
          <div>
            <h1>Campus Customs</h1>
            <p>Operations desk · five-agent team</p>
          </div>
        </div>
        <div className="topbar-right">
          <a className="topbar-cash" href="#till">
            {cash ? cash.balance.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : '—'} checking
            {pending && pending.length > 0 && <b> · {pending.length} to sign</b>}
          </a>
          <span className={`conn ${connError ? 'conn-bad' : tickets ? 'conn-ok' : ''}`} role="status">
            {connError ? 'Backend offline' : tickets ? 'Connected' : 'Connecting…'}
            <span className="conn-url">{API_BASE}</span>
          </span>
          <button type="button" className="btn btn-ghost" onClick={refreshAll}>Refresh</button>
        </div>
      </header>

      {connError && (
        <div className="banner" role="alert">
          <b>Backend offline.</b> {connError} Start it from <code>backend/</code> with{' '}
          <code>../.venv/bin/uvicorn main:app --reload --port 8000</code>, then press Refresh.
        </div>
      )}

      <div className="layout">
        <TicketRail tickets={tickets} selectedId={selectedId} runningIds={runningIds} onSelect={setSelectedId} />

        <main className="workspace" aria-label="Selected ticket">
          {!selected ? (
            <div className="workspace-empty">{tickets === null ? 'Loading…' : 'Select a ticket.'}</div>
          ) : (
            <>
              <section className="ticket-card" aria-labelledby="ticket-title">
                <div className="ticket-card-main">
                  <p className="ticket-kicker">
                    Ticket #{selected.id} · {ticketTypeLabel(selected.type)}
                  </p>
                  <h2 id="ticket-title">{selected.subject}</h2>
                  <dl className="ticket-facts">
                    {itemLine(selected) && (<><dt>Item</dt><dd>{itemLine(selected)}</dd></>)}
                    {selected.invoice_id != null && (<><dt>Invoice</dt><dd>#{selected.invoice_id}</dd></>)}
                    {selected.lease_id != null && (<><dt>Lease</dt><dd>#{selected.lease_id}</dd></>)}
                    <dt>Opened</dt><dd>{new Date(selected.created_at).toLocaleString()}</dd>
                    <dt>Status</dt><dd><TicketStamp ticket={selected} /></dd>
                  </dl>
                </div>
                <div className="ticket-card-run">
                  <button
                    type="button"
                    className="btn btn-run"
                    onClick={() => startRun(selected.id)}
                    disabled={runBusy}
                    aria-describedby="run-hint"
                  >
                    {starting === selected.id ? 'Starting…' : runningIds.has(selected.id) ? 'Agents working…' : 'Start agent team'}
                  </button>
                  <label className="field note-field">
                    <span>Decisions for the team (optional)</span>
                    <textarea
                      rows={3}
                      maxLength={1000}
                      value={notes[selected.id] ?? ''}
                      onChange={(e) => setNotes((p) => ({ ...p, [selected.id]: e.target.value }))}
                      disabled={runBusy}
                      placeholder="e.g. an approved discount. Sent with the next run."
                    />
                  </label>
                  <p id="run-hint" className="run-hint">
                    {selected.resolved
                      ? 'The backend marks this ticket resolved. Running again is allowed but rarely needed.'
                      : 'Runs only when you press the button. Payments wait for your approval.'}
                  </p>
                  {runError[selected.id] && <p className="error-box" role="alert">{runError[selected.id]}</p>}
                </div>
              </section>

              <div className="run-bar">
                {runs.length > 0 || trackedRun ? (
                  <>
                    <label className="run-pick">
                      <span>Run</span>
                      <select
                        value={viewRunId ?? ''}
                        onChange={(e) => setPickedRun((p) => ({ ...p, [selected.id]: e.target.value }))}
                      >
                        {trackedRun && !runs.some((r) => r.runId === trackedRun.run_id) && (
                          <option value={trackedRun.run_id}>{trackedRun.run_id} · starting</option>
                        )}
                        {[...runs].reverse().map((r, i) => (
                          <option key={r.runId} value={r.runId}>
                            {r.runId} · {r.startedTs ? new Date(r.startedTs).toLocaleString() : ''}{i === 0 ? ' · latest' : ''}
                          </option>
                        ))}
                      </select>
                    </label>
                    {viewStatus && <RunBadge status={viewStatus} />}
                    {viewRun?.usage && (
                      <span className="run-usage">
                        {viewRun.usage.requests} requests · {viewRun.usage.total_tokens?.toLocaleString()} tokens
                      </span>
                    )}
                  </>
                ) : (
                  <span className="muted">{ticketEvents?.loaded ? 'No runs recorded for this ticket yet.' : 'Loading history…'}</span>
                )}
              </div>

              {trackedRun?.run_id === viewRunId && trackedRun?.error && (
                <p className="error-box" role="alert">Run error: {trackedRun.error}</p>
              )}
              {viewStatus && viewStatus !== 'running' && !selected.resolved && (
                <p className="note-box">
                  This run has ended, but the backend still lists the ticket as{' '}
                  <b>{selected.status.replace('_', ' ')}</b>. It is marked resolved only when the backend says so.
                </p>
              )}
              {eventsError && <p className="error-box" role="alert">Couldn't load activity: {eventsError}</p>}

              <AgentBoard activity={activity} hasRun={!!viewRun || isLive} />
              <ActivityFeed items={feed} live={isLive} />
            </>
          )}
        </main>

        <Till
          cash={cash}
          cashError={cashError}
          cashFlash={cashFlash}
          pending={pending}
          pendingError={pendingError}
          approvingId={approvingId}
          approvalError={approvalError}
          approvalNotice={approvalNotice}
          history={history}
          onApprove={approve}
          onReject={reject}
          onRefresh={() => { refreshCash(); refreshPending() }}
        />
      </div>
    </div>
  )
}
