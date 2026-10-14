import { cn } from '@/lib/cn'
import { useRoster } from '@/telemetry/agents'
import type { AgentId } from '@/telemetry/types'

/** An agent's initial in a violet ring (violet means "agent" everywhere). */
export function AgentBadge({ id, size = 'sm', className }: { id: AgentId | null; size?: 'sm' | 'md'; className?: string }) {
  const agent = useRoster((s) => (id ? s.list.find((a) => a.id === id) : undefined))
  return (
    <span
      title={agent ? `${agent.name} · ${agent.role}` : 'A helper'}
      className={cn(
        'inline-grid shrink-0 place-items-center rounded-full border font-semibold',
        agent ? 'border-agent/50 bg-agent/10 text-[#f0abfc]' : 'border-line-strong bg-white/[0.04] text-ink-faint',
        size === 'sm' ? 'size-5 text-[9px]' : 'size-8 text-[12px]',
        className,
      )}
    >
      {agent ? agent.name.slice(0, 2) : '·'}
    </span>
  )
}
