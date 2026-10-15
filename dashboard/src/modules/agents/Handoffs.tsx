import { agentName } from '@/telemetry/agents'
import { useTeam } from '@/telemetry/team'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import type { Handoff } from '@/telemetry/types'
import { Panel } from '@/ui/Panel'
import { KIND } from './shared'

export function Handoffs({ handoffs, onOpen, className }: { handoffs: Handoff[]; onOpen: (id: string) => void; className?: string }) {
  useNow(30_000)
  const chief = useTeam((s) => s.team.chief)
  const name = (x: Handoff['from']) => (x === 'owner' ? 'You' : x === 'helper' ? 'A helper' : agentName(x))
  return (
    <Panel title="Handoffs" aside={<span className="text-2xs text-ink-faint">from the board</span>} className={className}>
      {handoffs.length === 0 ? <p className="text-[12px] text-ink-faint">Nothing has moved between agents lately.</p> : (
        <ol className="-mx-2 grid max-h-[300px] grid-cols-[minmax(0,1fr)] gap-x-4 gap-y-0.5 overflow-y-auto md:grid-cols-2 xl:grid-cols-3">
          {handoffs.slice(0, 20).map((h) => {
            const agent = h.to === chief || h.to === 'owner' ? h.from : h.to
            const can = agent !== 'owner' && agent !== 'helper'
            return (
              <li key={`${h.cardId}-${h.kind}-${h.at}`}>
                <button type="button" disabled={!can} onClick={() => can && onOpen(agent)}
                  className="press w-full rounded-lg px-2 py-1.5 text-left hover:bg-white/[0.04] disabled:hover:bg-transparent">
                  <div className="flex items-baseline gap-1.5 text-[12px]">
                    <span className="font-semibold text-[#f0abfc]">{name(h.from)}</span>
                    <span className="text-ink-faint">{KIND[h.kind].label}{h.kind === 'assign' ? ` to ${name(h.to)}` : ''}</span>
                    <span className="num ml-auto text-[10px] text-ink-faint">{ago(h.at)}</span>
                  </div>
                  <div className="line-clamp-1 text-[12px] text-ink-dim">{h.title}</div>
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </Panel>
  )
}
