import { cn } from '@/lib/cn'

export type Tone = 'memory' | 'agent' | 'ok' | 'runway' | 'alarm' | 'ink'

const FILL: Record<Tone, string> = {
  memory: 'bg-memory', agent: 'bg-agent', ok: 'bg-ok', runway: 'bg-runway', alarm: 'bg-alarm', ink: 'bg-ink-dim',
}

export interface Mark {
  at: number
  label: string
  tone?: Tone
}

/**
 * A horizontal meter with the thresholds that matter drawn on it (the 80 % heads-up, the closing point, the disk alarm),
 * so the number is read against its limit, not on its own.
 */
export function Meter({ value, max, tone, marks = [], label, className }: {
  value: number
  max: number
  tone: Tone
  marks?: Mark[]
  label: string
  className?: string
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className={cn('relative', className)}>
      <meter className="sr-only" aria-label={label} min={0} max={max} value={value} />
      <div aria-hidden className="relative h-2 overflow-hidden rounded-full bg-white/[0.07]">
        <div className={cn('h-full rounded-full transition-[width] duration-500 ease-[var(--ease-out)]', FILL[tone])} style={{ width: `${pct}%` }} />
      </div>
      {marks.map((m) => (
        <div key={m.label} className="absolute top-0 h-2" style={{ left: `${Math.min(100, (m.at / max) * 100)}%` }} aria-hidden>
          <div className={cn('h-full w-px', m.tone === 'alarm' ? 'bg-alarm' : m.tone === 'runway' ? 'bg-runway' : 'bg-ink-dim')} />
        </div>
      ))}
      {marks.length > 0 && (
        <div className="relative mt-1 h-4 text-[10px] text-ink-faint">
          {marks.map((m) => {
            const left = Math.min(100, (m.at / max) * 100)
            return (
              <span key={m.label} className="absolute whitespace-nowrap" style={left > 70 ? { right: `${100 - left}%` } : { left: `${left}%`, transform: 'translateX(-50%)' }}>
                {m.label}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
