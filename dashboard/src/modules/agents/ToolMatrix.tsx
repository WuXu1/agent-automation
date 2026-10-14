import { Check, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useMode } from '@/telemetry/mode'
import type { AgentState } from '@/telemetry/types'
import { AgentBadge } from '@/ui/AgentBadge'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'
import type { AddServerPreset } from './AddServer'
import { useRegistry } from '@/telemetry/registry'
import { MCP_ORDER } from './shared'
import { updateAgent } from './writes'

type Staged = Record<string, Record<string, boolean>>   // profile -> server -> new state

/**
 * Tools down the side (so the list can grow long), agents across (narrow columns, so many fit), both headers pinned while
 * it scrolls, and a filter. An MCP dot switches that server for that agent (staged, applied together behind one confirm:
 * one restart covers them all); an empty cell offers to copy the server onto that agent. Tools after the divider are part
 * of Hermes, shown but not switched.
 */
export function ToolMatrix({ agents, onOpen, onAdd }: { agents: AgentState[]; onOpen: (profile: string) => void; onAdd: (p: AddServerPreset) => void }) {
  const mode = useMode((s) => s.mode)
  const { tools: TOOLS, mcp: MCP_RULE } = useRegistry((r) => r.reg)
  const [staged, setStaged] = useState<Staged>({})
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<'all' | 'mcp' | 'hermes'>('all')
  const servers = useMemo(() => {
    const all = new Set(agents.flatMap((a) => a.mcp.map((m) => m.name)))
    const order = (n: string) => { const i = MCP_ORDER.indexOf(n.toLowerCase()); return i < 0 ? 99 : i }
    return [...all].sort((a, b) => order(a) - order(b) || a.localeCompare(b))
  }, [agents])
  const t = q.trim().toLowerCase()
  const shownServers = kind === 'hermes' ? [] : servers.filter((n) => !t || n.toLowerCase().includes(t) || (MCP_RULE[n.toLowerCase()] ?? '').toLowerCase().includes(t))
  const shownTools = kind === 'mcp' ? [] : TOOLS.filter((x) => !t || x.label.toLowerCase().includes(t) || x.rule.toLowerCase().includes(t))
  const count = Object.values(staged).reduce((n, m) => n + Object.keys(m).length, 0)
  const summary = Object.entries(staged).flatMap(([p, m]) => Object.entries(m).map(([s, on]) => `${agents.find((a) => a.profile === p)?.name ?? p} ${s} ${on ? 'on' : 'off'}`))

  const toggle = (a: AgentState, server: string, current: boolean) => {
    play('tick')
    setStaged((st) => {
      const mine = { ...(st[a.profile] ?? {}) }
      if (server in mine) delete mine[server]
      else mine[server] = !current
      const next = { ...st, [a.profile]: mine }
      if (!Object.keys(mine).length) delete next[a.profile]
      return next
    })
  }

  const apply = async () => {
    for (const [profile, m] of Object.entries(staged)) await updateAgent(profile, { mcp: m })
    setStaged({})
    play('confirm')
  }

  const head = 'sticky top-0 z-10 bg-deck/95 backdrop-blur'
  const side = 'sticky left-0 z-[5] bg-deck/95 backdrop-blur'

  return (
    <Panel title="Tools and MCP servers" className="lg:col-span-12" bodyClassName="px-0 pb-3"
      aside={<Button size="sm" tone="memory" icon={<Plus className="size-3.5" />} onClick={() => onAdd({ source: 'catalog' })}>Add MCP server</Button>}>
      <div className="mb-2 flex flex-wrap items-center gap-2 px-4">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Filter ${servers.length + TOOLS.length} tools`} aria-label="Filter tools"
          className="min-w-0 flex-1 rounded-lg border border-line bg-white/[0.02] px-3 py-1.5 text-[12px] outline-none placeholder:text-ink-faint focus:border-line-strong sm:max-w-[280px]" />
        <div className="flex gap-0.5 rounded-lg border border-line p-0.5 text-[12px]">
          {([['all', 'All'], ['mcp', `MCP · ${servers.length}`], ['hermes', `Built in · ${TOOLS.length}`]] as const).map(([k, l]) => (
            <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}
              className={cn('press rounded-md px-2.5 py-1', kind === k ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{l}</button>
          ))}
        </div>
        <span className="ml-auto hidden text-2xs text-ink-faint md:inline">click a dot to switch it · click · to copy a server onto that agent</span>
      </div>
      <div className="max-h-[560px] overflow-auto">
        <table className="border-separate border-spacing-0 text-[12px]">
          <thead>
            <tr>
              <th className={cn(head, side, 'z-20 min-w-[230px] border-b border-line px-4 py-2 text-left text-2xs font-medium text-ink-faint')}>Tool</th>
              {agents.map((a) => (
                <th key={a.id} className={cn(head, 'w-[58px] min-w-[58px] border-b border-line px-0.5 py-1.5 font-normal')}>
                  <button type="button" onClick={() => onOpen(a.profile)} title={`${a.name}: open`} className="press mx-auto flex w-[54px] flex-col items-center gap-0.5 rounded-md py-0.5 hover:bg-white/[0.04]">
                    <AgentBadge id={a.id} />
                    <span className="w-full truncate text-center text-[10px] text-ink-dim">{a.name}</span>
                  </button>
                </th>
              ))}
              <th className={cn(head, 'w-full border-b border-line')} aria-hidden />
            </tr>
          </thead>
          <tbody>
            {shownServers.length > 0 && (
              <tr><td colSpan={agents.length + 2} className={cn(side, 'px-4 pt-2.5 pb-1 text-2xs font-medium tracking-wide text-ink-faint uppercase')}>MCP servers</td></tr>
            )}
            {shownServers.map((n) => {
              const have = agents.filter((a) => a.mcp.some((m) => m.name === n))
              const on = have.filter((a) => a.mcp.find((m) => m.name === n)?.enabled).length
              return (
                <tr key={n} className="group/row">
                  <td className={cn(side, 'border-b border-line px-4 py-1.5 group-hover/row:bg-white/[0.03]')}>
                    <div className="num text-ink">{n.replace('hermes_', '')}</div>
                    <div className="truncate text-[10px] text-ink-faint" title={MCP_RULE[n.toLowerCase()] ?? ''}>{on} of {agents.length} on{MCP_RULE[n.toLowerCase()] ? ` · ${MCP_RULE[n.toLowerCase()]}` : ''}</div>
                  </td>
                  {agents.map((a) => {
                    const m = a.mcp.find((x) => x.name === n)
                    if (!m) {
                      return (
                        <td key={a.id} className="border-b border-line text-center group-hover/row:bg-white/[0.02]">
                          <button type="button" onClick={() => onAdd({ source: 'copy', server: n, profiles: [a.profile] })} title={`Copy ${n} onto ${a.name}`} aria-label={`${a.name}: ${n} not set up; copy it`}
                            className="press mx-auto grid size-7 place-items-center rounded-md text-ink-faint hover:bg-white/[0.06] hover:text-ink">·</button>
                        </td>
                      )
                    }
                    const pending = staged[a.profile]?.[m.name]
                    const now = pending ?? m.enabled
                    return (
                      <td key={a.id} className="border-b border-line text-center group-hover/row:bg-white/[0.02]">
                        <button type="button" onClick={() => toggle(a, m.name, m.enabled)} aria-pressed={now}
                          aria-label={`${a.name}: ${n} ${now ? 'on' : 'off'}${pending !== undefined ? ' (not applied yet)' : ''}`}
                          title={`${n} for ${a.name}: ${now ? 'on' : 'off'}${pending !== undefined ? ' · staged' : ''}`}
                          className={cn('press mx-auto grid size-7 place-items-center rounded-md hover:bg-white/[0.06]', pending !== undefined && 'ring-1 ring-runway/70')}>
                          {now ? <span className="size-2.5 rounded-full bg-agent" /> : <span className="size-2.5 rounded-full border border-ink-faint" />}
                        </button>
                      </td>
                    )
                  })}
                  <td aria-hidden className="border-b border-line group-hover/row:bg-white/[0.02]" />
                </tr>
              )
            })}
            {shownTools.length > 0 && (
              <tr><td colSpan={agents.length + 2} className={cn(side, 'px-4 pt-3.5 pb-1 text-2xs font-medium tracking-wide text-ink-faint uppercase')}>Built into Hermes</td></tr>
            )}
            {shownTools.map((x) => (
              <tr key={x.key} className="group/row">
                <td className={cn(side, 'border-b border-line px-4 py-1.5 group-hover/row:bg-white/[0.03]')}>
                  <div className="text-ink">{x.label}</div>
                  <div className="truncate text-[10px] text-ink-faint" title={x.rule}>{x.rule}</div>
                </td>
                {agents.map((a) => (
                  <td key={a.id} className="border-b border-line py-1.5 text-center group-hover/row:bg-white/[0.02]" title={`${x.label}: ${x.who.includes(a.id) ? x.rule : 'no'}`}>
                    {x.who.includes(a.id) ? <span className="mx-auto block size-2.5 rounded-full bg-agent/70" aria-label="on" /> : <span className="text-ink-faint" aria-label="none">·</span>}
                  </td>
                ))}
                <td aria-hidden className="border-b border-line group-hover/row:bg-white/[0.02]" />
              </tr>
            ))}
            {!shownServers.length && !shownTools.length && (
              <tr><td colSpan={agents.length + 2} className="px-4 py-4 text-[12px] text-ink-faint">Nothing matches.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {count > 0 ? (
        <div className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-runway/40 bg-runway/[0.07] px-3 py-2.5">
          <div className="min-w-0 flex-1 text-[12px]">
            <span className="font-medium text-[#fcd34d]">{count} change{count > 1 ? 's' : ''} staged</span>
            <span className="text-ink-dim"> · {summary.join(', ')}</span>
            <div className="text-2xs text-ink-faint">{mode === 'live' ? 'Applied to each profile’s config.yaml (backed up first); they take effect after a quiet gateway restart.' : 'Demo: applied in this tab only.'}</div>
          </div>
          <Button tone="ghost" size="sm" onClick={() => setStaged({})}>Discard</Button>
          <ConfirmButton label={`Apply ${count}`} confirmLabel={`Write ${count} change${count > 1 ? 's' : ''}`} tone="memory" icon={<Check className="size-3.5" />} onConfirm={apply} />
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 px-4 text-2xs text-ink-faint">
          <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-agent" />on</span>
          <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full border border-ink-faint" />set up, switched off</span>
          <span>· not set up for that agent. Open an agent for its skills and to remove a server.</span>
        </div>
      )}
    </Panel>
  )
}
