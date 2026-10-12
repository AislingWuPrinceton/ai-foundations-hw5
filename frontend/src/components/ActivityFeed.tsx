import { useMemo, useState } from 'react'
import { AGENTS, actorName, isAgentRole } from '../agents'
import type { FeedItem } from '../events'
import { Glyph } from './Glyph'

interface Props {
  items: FeedItem[]
  live: boolean
}

export function ActivityFeed({ items, live }: Props) {
  const [filter, setFilter] = useState<string>('all')
  const shown = useMemo(() => (filter === 'all' ? items : items.filter((i) => i.actor === filter)), [items, filter])

  return (
    <section className="feed" aria-labelledby="feed-title">
      <div className="feed-head">
        <h3 id="feed-title" className="section-title">Activity log</h3>
        <div className="feed-filter" role="group" aria-label="Filter by agent">
          {[{ role: 'all', name: 'Everyone' }, ...AGENTS, { role: 'runner', name: 'Runner' }].map((a) => (
            <button
              key={a.role}
              type="button"
              className={`chip chip-${a.role}`}
              aria-pressed={filter === a.role}
              onClick={() => setFilter(a.role)}
            >
              {a.role !== 'all' && <Glyph role={a.role} size={14} />}
              {a.name}
            </button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="empty">{live ? 'Waiting for the first agent step…' : 'No activity to show for this selection.'}</p>
      ) : (
        <ol className="log" aria-live={live ? 'polite' : 'off'} aria-relevant="additions">
          {shown.map((item) => (
            <li key={item.id} className={`entry tone-${item.tone} actor-${isAgentRole(item.actor) ? item.actor : item.actor || 'runner'}`}>
              <span className="entry-actor">
                <Glyph role={item.actor || 'runner'} size={16} />
                <span>{actorName(item.actor)}</span>
              </span>
              <div className="entry-body">
                <p className="entry-title">{item.title}</p>
                {item.body && <p className="entry-text">{item.body}</p>}
                {item.detail && (
                  <details className="entry-detail">
                    <summary>Show raw</summary>
                    <pre>{item.detail}</pre>
                  </details>
                )}
              </div>
              {item.tMs !== undefined && <span className="entry-time">{(item.tMs / 1000).toFixed(1)}s</span>}
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
