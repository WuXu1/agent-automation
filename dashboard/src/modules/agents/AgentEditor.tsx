import { Plus, Save, TerminalSquare, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useMode } from '@/telemetry/mode'
import type { AgentDetail, AgentMesh } from '@/telemetry/types'
import { AgentBadge } from '@/ui/AgentBadge'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Drawer } from '@/ui/Drawer'
import { EnhanceArea } from '@/ui/EnhanceArea'
import type { AddServerPreset } from './AddServer'
import { Automations } from './Automations'
import { SkillsPanel } from './SkillsPanel'
import { mcp as mcpApi } from '@/telemetry/tools'
import { useRegistry } from '@/telemetry/registry'
import { EFFORTS } from './shared'
import { deleteAgent, loadAgent, updateAgent } from './writes'

// Agents are added and moved only through Claude: this drawer edits one that exists.
export type EditorTarget = { mode: 'edit'; profile: string }

const input = 'w-full rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-medium text-ink">{label}</span>
        {hint && <span className="text-2xs text-ink-faint">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

/** Edit or delete an agent profile. Every write is behind a confirm step that says what will change. */
export function AgentEditor({ target, mesh, onClose, onAddServer, onWatch }: {
  target: EditorTarget | null
  mesh: AgentMesh
  onClose: () => void
  onAddServer: (p: AddServerPreset) => void
  /** Opens the agent's live terminal (what it is doing on the server). */
  onWatch?: (profile: string) => void
}) {
  const [tab, setTab] = useState<'profile' | 'skills' | 'mcp' | 'auto'>('profile')
  const mode = useMode((s) => s.mode)
  const [detail, setDetail] = useState<AgentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', description: '', soul: '', model: '', effort: 'medium' })
  const [confirmDelete, setConfirmDelete] = useState('')
  const editing = target?.profile ?? null
  const agent = editing ? mesh.agents.find((a) => a.profile === editing) : undefined
  const models = useMemo(() => [...new Set(['deepseek-flash', ...mesh.agents.map((a) => a.model).filter(Boolean) as string[]])], [mesh.agents])

  // The parent remounts this editor per agent (key), so state starts fresh; this only loads the real profile (its SOUL is
  // not in the list feed).
  useEffect(() => {
    if (!editing) return
    let stop = false
    loadAgent(editing).then((d) => {
      if (stop) return
      setDetail(d)
      setForm({ name: d.name, description: d.description, soul: d.soul.replace(/\n$/, ''), model: d.model ?? '', effort: d.effort ?? 'medium' })
    }).catch((e: unknown) => { if (!stop) setError(e instanceof Error ? e.message : 'Could not read the profile') })
    return () => { stop = true }
  }, [editing])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const changes = useMemo(() => {
    if (!detail) return []
    const out: string[] = []
    if (form.name.trim() !== detail.name) out.push('name')
    if (form.description.trim() !== detail.description.trim()) out.push('description')
    if (form.soul.trim() !== detail.soul.trim()) out.push('SOUL')
    if (form.model.trim() && form.model.trim() !== (detail.model ?? '')) out.push(`model → ${form.model.trim()}`)
    if (form.effort !== (detail.effort ?? 'medium')) out.push(`effort → ${form.effort}`)
    return out
  }, [form, detail])

  const save = async () => {
    if (!detail) return
    const patch: Record<string, string> = {}
    if (form.name.trim() !== detail.name) patch.name = form.name.trim()
    if (form.description.trim() !== detail.description.trim()) patch.description = form.description.trim()
    if (form.soul.trim() !== detail.soul.trim()) patch.soul = form.soul.trim()
    if (form.model.trim() && form.model.trim() !== (detail.model ?? '')) patch.model = form.model.trim()
    if (form.effort !== (detail.effort ?? 'medium')) patch.effort = form.effort
    const d = await updateAgent(detail.profile, patch)
    setDetail(d)
    play('confirm')
  }

  const remove = async () => {
    if (!detail) return
    await deleteAgent(detail.profile, confirmDelete.trim())
    play('warn')
    onClose()
  }

  const lead = detail?.reportsTo ? mesh.agents.find((a) => a.profile === detail.reportsTo) : undefined

  const footer = target && tab === 'profile' && (detail ? (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-start gap-2">
        <ConfirmButton label={changes.length ? `Save ${changes.length} change${changes.length > 1 ? 's' : ''}` : 'Save'}
          confirmLabel={`Save ${changes.join(', ')}`} tone="memory" icon={<Save className="size-3.5" />} disabled={!changes.length} onConfirm={save} />
      </div>
      <p className="text-2xs text-ink-faint">
        {mode === 'live' ? 'Each file is backed up first. Name, description and SOUL reach new chats (/new); model and effort apply from the next message.' : 'Demo: changes stay in this tab.'}
      </p>
    </div>
  ) : null)

  return (
    <Drawer open={Boolean(target)} onClose={onClose} wide footer={footer}
      actions={onWatch && editing ? (
        <button type="button" onClick={() => onWatch(editing)} title={`Watch what ${agent?.name ?? 'this agent'} is doing on the server, live`}
          className="press inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-[#04060a] px-2 py-1 text-[11px] text-ink-dim transition-colors hover:border-white/25 hover:text-ink">
          <TerminalSquare className="size-3.5 text-[#86efac]" aria-hidden />Live logs
        </button>) : undefined}
      title={<span className="inline-flex items-center gap-2"><AgentBadge id={agent?.id ?? null} />{agent?.name ?? 'Agent'}<span className="num text-2xs font-normal text-ink-faint">{editing}</span></span>}>
      {error && <p role="alert" className="mb-3 rounded-lg border border-alarm/40 bg-alarm/10 px-3 py-2 text-[12px] text-[#fca5a5]">{error}</p>}
      {!detail && !error && <div className="h-40 animate-pulse rounded-lg bg-white/[0.03]" />}
      {detail && (
        <div className="mb-4 flex gap-1 rounded-lg border border-line p-0.5 text-[12px]">
          {([['profile', 'Profile'], ['skills', 'Skills'], ['mcp', `MCP · ${agent?.mcp.length ?? 0}`], ['auto', 'Automations']] as const).map(([k, label]) => (
            <button key={k} type="button" aria-pressed={tab === k} onClick={() => setTab(k)}
              className={cn('press flex-1 rounded-md px-2.5 py-1.5', tab === k ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{label}</button>
          ))}
        </div>
      )}
      {detail && tab === 'skills' && <SkillsPanel profile={detail.profile} agentName={detail.name} />}
      {detail && tab === 'auto' && <Automations agents={mesh.agents} profile={detail.profile} />}
      {detail && agent && tab === 'mcp' && <AgentServers agent={agent} onAdd={() => onAddServer({ source: 'catalog', profiles: [detail.profile] })} />}
      {detail && tab === 'profile' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <input className={input} value={form.name} placeholder="e.g. Nora"
                onChange={set('name')} />
            </Field>
            <Field label="Telegram">
              <div className="flex h-[38px] items-center text-[12px] text-ink-dim">{detail.telegram ? 'has its own bot' : 'no bot yet (works through the board)'}</div>
            </Field>
          </div>
          {detail.profile !== 'default' && (
            <p className="text-[12px] text-ink-dim">Reports to <b className="text-ink">{lead?.name ?? 'the chief'}</b>
              <span className="text-ink-faint"> · agents are added and moved through Claude, not here</span></p>
          )}
          <Field label="What it does" hint="its lead reads this when handing out cards">
            <EnhanceArea field="description" name={form.name.trim()} className={cn(input, 'resize-y leading-relaxed')} rows={3} value={form.description}
              onChange={(v) => setForm((f) => ({ ...f, description: v.slice(0, 600) }))}
              placeholder="Nora: research and reading. Finds sources, summarises papers, keeps a reading list." maxLength={600} />
          </Field>
          <div className="grid grid-cols-[1fr_auto] gap-3">
            <Field label="Model">
              <input className={cn(input, 'num')} list="agent-models" value={form.model} onChange={set('model')} placeholder="deepseek-flash" />
              <datalist id="agent-models">{models.map((m) => <option key={m} value={m}>{m}</option>)}</datalist>
            </Field>
            <Field label="Reasoning effort">
              <div className="flex h-[38px] gap-0.5 rounded-lg border border-line p-0.5">
                {EFFORTS.map((e) => (
                  <button key={e} type="button" aria-pressed={form.effort === e} onClick={() => setForm((f) => ({ ...f, effort: e }))}
                    className={cn('press rounded-md px-2.5 text-[12px]', form.effort === e ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{e}</button>
                ))}
              </div>
            </Field>
          </div>
          <Field label="SOUL" hint={`${form.soul.length.toLocaleString('en-GB')} / 20,000 · who it is, how it speaks, what it never does`}>
            <EnhanceArea field="soul" name={form.name.trim()} about={form.description.trim()}
              className={cn(input, 'min-h-[260px] resize-y font-mono text-[12px] leading-relaxed')} rows={14} value={form.soul}
              onChange={(v) => setForm((f) => ({ ...f, soul: v.slice(0, 20000) }))} maxLength={20000}
              />
          </Field>
          {detail && detail.profile !== 'default' && (
            <details className="rounded-lg border border-alarm/25 px-3 py-2">
              <summary className="cursor-pointer text-[12px] text-[#fca5a5]">Delete this agent</summary>
              <p className="mt-2 text-2xs text-ink-faint">The whole profile is exported to an archive on the VM first (<span className="num">hermes profile export</span>), then deleted. Its memories in Mem0 stay.</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <input className={cn(input.replace('w-full ', ''), 'num w-40')} value={confirmDelete} onChange={(e) => setConfirmDelete(e.target.value)} placeholder={`type ${detail.profile}`} aria-label="Type the profile id to confirm" />
                <ConfirmButton label="Delete" confirmLabel={`Archive and delete ${detail.name}`} tone="danger" icon={<Trash2 className="size-3.5" />}
                  disabled={confirmDelete.trim() !== detail.profile} onConfirm={remove} />
              </div>
            </details>
          )}
        </div>
      )}
    </Drawer>
  )
}

/** One agent's MCP servers: switch (staged, applied with one confirm), remove (backed up), add from the catalog or your own. */
function AgentServers({ agent, onAdd }: { agent: AgentMesh['agents'][number]; onAdd: () => void }) {
  const mode = useMode((s) => s.mode)
  const MCP_RULE = useRegistry((r) => r.reg.mcp)
  const [staged, setStaged] = useState<Record<string, boolean>>({})
  const count = Object.keys(staged).length
  return (
    <div className="space-y-3">
      {agent.mcp.length === 0 ? <p className="text-[12px] text-ink-faint">{agent.name} has no MCP servers yet.</p> : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {agent.mcp.map((m) => {
            const on = staged[m.name] ?? m.enabled
            return (
              <li key={m.name} className="flex items-center gap-2.5 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="num text-[12px] text-ink">{m.name}</div>
                  <div className="truncate text-2xs text-ink-faint">{MCP_RULE[m.name.toLowerCase()] ?? (on ? 'on' : 'switched off')}</div>
                </div>
                <ConfirmButton label="Remove" confirmLabel={`Remove from ${agent.name}`} tone="danger" size="sm" icon={<Trash2 className="size-3.5" />}
                  onConfirm={async () => { await mcpApi.remove(m.name, agent.profile); play('warn') }} />
                <button type="button" role="switch" aria-checked={on} aria-label={`${m.name} ${on ? 'on' : 'off'}`}
                  onClick={() => setStaged((st) => { const n = { ...st }; if (m.name in n) delete n[m.name]; else n[m.name] = !m.enabled; return n })}
                  className={cn('press relative h-5 w-9 shrink-0 rounded-full border transition-colors', on ? 'border-agent/60 bg-agent/40' : 'border-line-strong bg-white/[0.04]', m.name in staged && 'ring-1 ring-runway/70')}>
                  <span className={cn('absolute top-0.5 size-3.5 rounded-full bg-ink transition-[left] duration-150', on ? 'left-[18px]' : 'left-0.5')} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button tone="memory" icon={<Plus className="size-3.5" />} onClick={onAdd}>Add a server</Button>
        {count > 0 && (
          <>
            <ConfirmButton label={`Apply ${count}`} confirmLabel={`Write ${count} change${count > 1 ? 's' : ''}`} tone="memory"
              onConfirm={async () => { await updateAgent(agent.profile, { mcp: staged }); setStaged({}); play('confirm') }} />
            <Button tone="ghost" onClick={() => setStaged({})}>Discard</Button>
          </>
        )}
      </div>
      <p className="text-2xs text-ink-faint">{mode === 'live' ? 'MCP servers load at gateway start: changes wait for a quiet restart (the yellow bar). The config is backed up first.' : 'Demo: changes stay in this tab.'}</p>
    </div>
  )
}
