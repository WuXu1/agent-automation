import { cn } from '@/lib/cn'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { agentName, isAgentId } from '@/telemetry/agents'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import type { MemoryEvent } from '@/telemetry/types'
import { useBrainUi } from './store'

const VERB: Record<MemoryEvent['kind'], string> = {
  read: 'looked up', search: 'searched', add: 'added a note', update: 'changed a note', delete: 'deleted a note',
}

function who(e: MemoryEvent): string {
  if (isAgentId(e.agent)) return agentName(e.agent)
  return e.agent === 'dashboard' ? 'You' : 'Mem0'
}

/** What touched memory recently: agents' look-ups (demo heartbeat, or changes found on each live poll) and your own edits. */
export function Activity({ className }: { className?: string }) {
  const events = useBrain((s) => s.events)
  const select = useBrainUi((s) => s.select)
  useNow(15_000)
  return (
    <section aria-label="Memory activity" className={cn('glass flex min-h-0 flex-col', className)}>
      <header className="flex items-center justify-between px-4 pt-3 pb-1.5">
        <h2 className="text-[12px] font-semibold">Activity</h2>
        <span className="text-2xs text-ink-faint">memory reads and writes</span>
      </header>
      {events.length === 0 ? (
        <p className="px-4 pb-3.5 text-[12px] text-ink-faint">Quiet so far. Look-ups appear here as the agents work.</p>
      ) : (
        <ol className="min-h-0 overflow-hidden px-1.5 pb-1.5" aria-live="polite">
          {events.slice(0, 6).map((e) => (
            <li key={`${e.at}-${e.kind}-${e.memoryIds[0] ?? ''}`} className="animate-[feed-in_180ms_var(--ease-out)]">
              <button
                type="button"
                disabled={!e.memoryIds.length || e.kind === 'delete'}
                onClick={() => e.memoryIds[0] && select(e.memoryIds[0])}
                className="press flex w-full items-baseline gap-2 rounded-lg px-2.5 py-1 text-left text-[12px] hover:bg-white/[0.04] disabled:hover:bg-transparent"
              >
                <span className={cn('shrink-0 font-semibold', isAgentId(e.agent) ? 'text-[#f0abfc]' : 'text-memory')}>{who(e)}</span>
                <span className="min-w-0 flex-1 truncate text-ink-dim">
                  {VERB[e.kind]}{e.note ? <> “<span className="text-ink">{e.note}</span>”</> : null}
                  {e.kind !== 'delete' && e.memoryIds.length > 1 ? ` · ${e.memoryIds.length} notes` : ''}
                </span>
                <span className="num shrink-0 text-[10px] text-ink-faint">{ago(e.at)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
