// A distinct shape per agent, so agents are told apart by silhouette and label, not color alone.

const PATHS: Record<string, string> = {
  // star: the desk lead
  boss: 'M12 2.8l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 16.8l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z',
  // stacked box: the stockroom
  inventory: 'M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5zM3.5 7.5L12 12l8.5-4.5M12 12v9',
  // ledger book with a coin mark
  accounting: 'M5 3.5h11a3 3 0 013 3v14H8a3 3 0 01-3-3zM5 17.5a3 3 0 013-3h11M10.5 7.5h5M10.5 10.5h5',
  // house with a door: the premises
  facilities: 'M3 11l9-7.5 9 7.5M5.5 9v11.5h13V9M10 20.5v-6h4v6',
  // speech bubble: the front counter
  customer_service: 'M4 5h16v10.5H10l-5 4v-4H4zM8 9.5h8M8 12.5h5',
  // arrow: the desk runner (system)
  runner: 'M4 12h14M13 6l6 6-6 6',
  // pen nib: the human approver signs
  human: 'M4 20l3.5-1 10-10-2.5-2.5-10 10zM14 5.5l2.5-2.5 4.5 4.5-2.5 2.5',
}

export function Glyph({ role, size = 22, title }: { role: string; size?: number; title?: string }) {
  const filled = role === 'boss'
  return (
    <svg
      className={`glyph glyph-${role}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <path
        d={PATHS[role] ?? PATHS.runner}
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth={filled ? 1.2 : 1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
