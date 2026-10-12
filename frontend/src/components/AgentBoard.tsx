import { AGENTS, AGENT_BY_ROLE } from '../agents'
import { kindLabel, type AgentActivity } from '../events'
import { Glyph } from './Glyph'

const STATE_LABEL = { idle: 'Not involved', working: 'Working', done: 'Done' } as const
const money = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

function Evidence({ a }: { a: AgentActivity }) {
  const items: string[] = []
  for (const t of a.tools) items.push(`Called ${t.name}${t.count > 1 ? ` ×${t.count}` : ''}${t.failed ? ` (${t.failed} refused)` : ''}`)
  for (const r of a.delegatedTo) items.push(`Delegated to ${AGENT_BY_ROLE[r].name}`)
  for (const p of a.prepared) items.push(`Prepared ${kindLabel(p.kind)} #${p.id} · ${money(p.amount)}`)
  if (a.delegatedFrom.length) items.push(`Asked by ${a.delegatedFrom.map((r) => AGENT_BY_ROLE[r].name).join(', ')}`)
  if (!items.length) return null
  return (
    <ul className="evidence" aria-label="Evidence from the audit trail">
      {items.map((i) => <li key={i}>{i}</li>)}
    </ul>
  )
}

export function AgentBoard({ activity, hasRun }: { activity: AgentActivity[]; hasRun: boolean }) {
  return (
    <section className="board" aria-labelledby="board-title">
      <h3 id="board-title" className="section-title">The team on this run</h3>
      <ul className="agents">
        {AGENTS.map((meta) => {
          const a = activity.find((x) => x.role === meta.role)!
          const state = a.state
          return (
            <li key={meta.role} className={`agent agent-${meta.role} agent-${state}${a.involved ? '' : ' agent-quiet'}`}>
              <article aria-label={`${meta.name}, ${meta.station}`}>
                <header className="agent-head">
                  <span className="agent-badge" aria-hidden="true">
                    <Glyph role={meta.role} />
                  </span>
                  <span className="agent-names">
                    <span className="agent-name">{meta.name}</span>
                    <span className="agent-station">{meta.station} · {meta.duty}</span>
                  </span>
                  <span className={`agent-state state-${state}`}>
                    {state === 'working' && <span className="pulse" aria-hidden="true" />}
                    {hasRun ? STATE_LABEL[state] : 'Standing by'}
                  </span>
                </header>
                {a.report ? (
                  <div className="agent-report">
                    <p className="agent-summary">{a.report.summary}</p>
                    <p className="agent-report-status">Report status: <b>{a.report.status.replace('_', ' ')}</b></p>
                  </div>
                ) : a.lastLine ? (
                  <p className="agent-last">{a.lastLine}</p>
                ) : (
                  <p className="agent-last muted">{hasRun ? 'No activity on this run.' : 'Waiting for a run.'}</p>
                )}
                <Evidence a={a} />
              </article>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
