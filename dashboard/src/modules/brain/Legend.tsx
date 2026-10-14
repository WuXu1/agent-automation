import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import type { ClusterId } from '@/telemetry/types'
import { useBrainUi } from './store'

/** The sections (eight built in, plus any the AI started) with their counts; picking one flies there and dims the rest. */
export function Legend({ className }: { className?: string }) {
  const graph = useBrain((s) => s.graph)
  const focusCluster = useBrainUi((s) => s.focusCluster)
  const focus = useBrainUi((s) => s.focus)
  const select = useBrainUi((s) => s.select)
  const counts = new Map<ClusterId, number>()
  for (const n of graph.nodes) counts.set(n.cluster, (counts.get(n.cluster) ?? 0) + 1)

  const toggle = (id: ClusterId) => {
    play('tick')
    select(null)
    focus(focusCluster === id ? null : id)
  }

  return (
    <section aria-label="Themes" className={cn('glass p-1.5', className)}>
      <h2 className="hidden px-2.5 pt-1 pb-1 text-2xs font-medium tracking-wide text-ink-faint uppercase md:block">Themes</h2>
      <ul className="flex gap-1 overflow-x-auto md:max-h-[44vh] md:flex-col md:gap-0 md:overflow-y-auto">
        {graph.sections.map((c) => {
          const on = focusCluster === c.id
          return (
            <li key={c.id} className="shrink-0">
              <button
                type="button"
                aria-pressed={on}
                onClick={() => toggle(c.id)}
                className={cn(
                  'press flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1 text-left hover:bg-white/[0.05]',
                  on && 'bg-white/[0.07]',
                  focusCluster && !on && 'opacity-55',
                )}
              >
                <span className="size-2 shrink-0 rounded-full" style={{ background: c.color, boxShadow: on ? `0 0 10px ${c.color}` : undefined }} aria-hidden />
                <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink" title={c.blurb}>{c.label}</span>
                <span className="num text-[11px] text-ink-dim">{counts.get(c.id) ?? 0}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
