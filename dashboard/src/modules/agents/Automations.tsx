import { Pause, Pencil, Play, Plus, Server, Trash2, Zap } from 'lucide-react'
import { chiefId } from '@/telemetry/team'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { ago, stamp } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { agentName } from '@/telemetry/agents'
import { useMode } from '@/telemetry/mode'
import { automationsApi, type Automation, type AutomationInput, type VmTimer } from '@/telemetry/tools'
import type { AgentState } from '@/telemetry/types'
import { AgentBadge } from '@/ui/AgentBadge'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'

const input = 'w-full rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'
const PRESETS: Array<[string, string]> = [['every morning at 8', '0 8 * * *'], ['weekdays at 9', '0 9 * * 1-5'], ['every evening at 9', '0 21 * * *'],
  ['every Sunday at 6pm', '0 18 * * 0'], ['every 2 hours', 'every 2h'], ['every 30 minutes', '30m']]
const DELIVER: Array<[string, string]> = [['telegram', 'Telegram'], ['origin', 'where it was set up'], ['local', 'nowhere (just run it)']]

function when(ms: number | null, now: number): string {
  if (!ms) return '–'
  if (ms <= now) return ago(ms, now)
  const m = Math.round((ms - now) / 60_000)
  if (m < 60) return `in ${Math.max(1, m)} min`
  const h = Math.round(m / 60)
  return h < 36 ? `in ${h} h` : `in ${Math.round(h / 24)} days`
}

function idFor(profile: string, agents: AgentState[]): string {
  return agents.find((a) => a.profile === profile)?.id ?? (profile === 'default' ? chiefId() : profile)
}

function Form({ initial, agents, fixedProfile, onSave, onCancel, creating }: {
  initial: AutomationInput & { profile?: string }
  agents: AgentState[]
  fixedProfile?: string
  creating?: boolean
  onSave: (profile: string, v: AutomationInput) => Promise<void>
  onCancel: () => void
}) {
  const [v, setV] = useState({ profile: fixedProfile ?? initial.profile ?? 'default', name: initial.name ?? '', schedule: initial.schedule ?? '0 8 * * *',
    prompt: initial.prompt ?? '', deliver: initial.deliver || 'telegram' })
  const ok = v.schedule.trim() && (!creating || v.prompt.trim())
  return (
    <div className="space-y-2.5 rounded-lg border border-agent/30 bg-agent/[0.04] px-3 py-3">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-2.5 sm:grid-cols-2">
        {creating && !fixedProfile && (
          <label className="block"><span className="mb-1 block text-[12px] font-medium">Agent</span>
            <select className={input} value={v.profile} onChange={(e) => setV({ ...v, profile: e.target.value })}>
              {agents.map((a) => <option key={a.profile} value={a.profile}>{a.name}</option>)}
            </select></label>
        )}
        <label className="block"><span className="mb-1 block text-[12px] font-medium">Name</span>
          <input className={input} value={v.name} maxLength={80} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="Sunday week ahead" /></label>
        <label className="block"><span className="mb-1 block text-[12px] font-medium">When</span>
          <input className={cn(input, 'num')} value={v.schedule} maxLength={60} onChange={(e) => setV({ ...v, schedule: e.target.value })} placeholder="0 8 * * *  or  every 2h" /></label>
        <label className="block"><span className="mb-1 block text-[12px] font-medium">Send the result to</span>
          <select className={input} value={v.deliver} onChange={(e) => setV({ ...v, deliver: e.target.value })}>
            {DELIVER.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
      </div>
      <div className="flex flex-wrap gap-1">
        {PRESETS.map(([l, s]) => (
          <button key={s} type="button" onClick={() => setV({ ...v, schedule: s })}
            className={cn('press rounded-full border px-2 py-0.5 text-[11px]', v.schedule === s ? 'border-agent/60 text-ink' : 'border-line text-ink-faint hover:text-ink-dim')}>{l}</button>
        ))}
      </div>
      <label className="block"><span className="mb-1 block text-[12px] font-medium">What it should do <span className="font-normal text-ink-faint">· the agent gets this as its message each time</span></span>
        <textarea className={cn(input, 'resize-y leading-relaxed')} rows={3} maxLength={4000} value={v.prompt} onChange={(e) => setV({ ...v, prompt: e.target.value })}
          placeholder="Look at my calendar for the week ahead and send me a short plan." /></label>
      <div className="flex flex-wrap items-center gap-2">
        <ConfirmButton label={creating ? 'Create automation' : 'Save'} confirmLabel={creating ? `Schedule it for ${agentName(idFor(v.profile, agents))}` : 'Save the changes'}
          tone="memory" size="sm" disabled={!ok} onConfirm={() => onSave(v.profile, { name: v.name.trim() || undefined, schedule: v.schedule.trim(), prompt: v.prompt.trim() || undefined, deliver: v.deliver })} />
        <Button size="sm" tone="ghost" onClick={onCancel}>Cancel</Button>
        <span className="text-2xs text-ink-faint">Times are UK time. Each run is one agent turn on its own model.</span>
      </div>
    </div>
  )
}

function status(j: Automation): { label: string; dot: string; text: string } {
  if (j.state === 'completed') return { label: 'finished', dot: 'bg-ink-faint/40', text: 'text-ink-faint' }
  if (j.state === 'paused') return { label: 'paused', dot: 'border border-ink-faint', text: 'text-ink-faint' }
  if (j.lastStatus && j.lastStatus !== 'ok') return { label: 'last run failed', dot: 'bg-alarm', text: 'text-[#fca5a5]' }
  return { label: 'on', dot: 'bg-ok', text: 'text-ink-dim' }
}

/** One automation on one line; click it for what it does, how the last run went, and to edit it. */
function Row({ j, agents, onChange }: { j: Automation; agents: AgentState[]; onChange: (l: Automation[]) => void }) {
  const now = useNow(30_000).getTime()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const st = status(j)
  const paused = j.state === 'paused'
  const finished = j.state === 'completed'
  const overdue = paused && j.nextAt !== null && j.nextAt < now
  const title = j.name || j.prompt.slice(0, 60) || j.script || j.id
  return (
    <li className={cn(finished && 'opacity-60')}>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_9rem_auto]">
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="press flex min-w-0 items-center gap-2.5 rounded-md text-left">
          <span className={cn('size-2 shrink-0 rounded-full', st.dot)} title={st.label} aria-label={st.label} />
          <span className="min-w-0">
            <span className="block truncate text-[13px] text-ink">{title}</span>
            <span className="num block truncate text-[11px] text-ink-faint">
              {j.schedule}{j.mode === 'script' ? ' · script' : ''}{j.repeat ? ` · ${j.repeat.done} of ${j.repeat.times}` : ''}
            </span>
          </span>
        </button>
        <span className={cn('num hidden text-right text-[11px] sm:block', st.text)} title={j.nextAt ? stamp(j.nextAt) : undefined}>
          {finished ? 'finished' : paused ? 'paused' : st.label === 'last run failed' ? 'last run failed' : j.nextAt ? `next ${when(j.nextAt, now)}` : '–'}
        </span>
        <div className="flex items-center gap-0.5">
          {!finished && (paused ? (
            <ConfirmButton label="" ariaLabel={overdue ? 'Resume (it runs once now)' : 'Resume'} confirmLabel={overdue ? 'Resume (runs once now)' : 'Resume'}
              tone="ghost" size="sm" icon={<Play className="size-3.5" />} onConfirm={async () => { onChange(await automationsApi.act(j, 'resume')); play('confirm') }} />
          ) : (
            <ConfirmButton label="" ariaLabel="Pause" confirmLabel="Pause it" tone="ghost" size="sm" icon={<Pause className="size-3.5" />}
              onConfirm={async () => { onChange(await automationsApi.act(j, 'pause')); play('tick') }} />
          ))}
          {!finished && (
            <ConfirmButton label="" ariaLabel="Run now" confirmLabel="Run it once now" tone="ghost" size="sm" icon={<Zap className="size-3.5" />}
              onConfirm={async () => { onChange(await automationsApi.act(j, 'run')); play('confirm') }} />
          )}
          <ConfirmButton label="" ariaLabel="Delete" confirmLabel="Delete it" tone="ghost" confirmTone="danger" size="sm" icon={<Trash2 className="size-3.5" />}
            onConfirm={async () => { onChange(await automationsApi.remove(j)); play('warn') }} />
        </div>
      </div>
      {open && (
        <div className="mx-3 mb-2.5 rounded-lg border border-line bg-white/[0.02] px-3 py-2.5">
          {editing ? (
            <Form initial={j} agents={agents} fixedProfile={j.profile} onCancel={() => setEditing(false)}
              onSave={async (_, v) => { onChange(await automationsApi.edit(j, v)); setEditing(false); play('confirm') }} />
          ) : (
            <>
              <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-[12px]">
                <dt className="text-ink-faint">Status</dt><dd className={st.text}>{st.label}</dd>
                <dt className="text-ink-faint">When</dt><dd className="num text-ink-dim">{j.schedule}{j.nextAt && !paused && !finished ? ` · next ${stamp(j.nextAt)}` : ''}</dd>
                <dt className="text-ink-faint">Last run</dt><dd className="num text-ink-dim">{j.lastAt ? `${stamp(j.lastAt)} · ${j.lastStatus ?? '–'}` : 'not yet'}</dd>
                <dt className="text-ink-faint">Sends to</dt><dd className="text-ink-dim">{DELIVER.find(([k]) => k === j.deliver)?.[1] ?? (j.deliver || '–')}</dd>
                <dt className="text-ink-faint">Runs</dt><dd className="text-ink-dim">{j.mode === 'script' ? `the script ${j.script ?? ''} (no AI)` : `an agent turn${j.script ? ` with the output of ${j.script}` : ''}`}</dd>
              </dl>
              {j.prompt && <p className="mt-2 text-[12px] leading-relaxed whitespace-pre-line text-ink-dim">{j.prompt}</p>}
              {j.lastError && st.label === 'last run failed' && <p className="mt-2 text-[12px] text-[#fca5a5]">{j.lastError}</p>}
              {j.mode === 'agent' && !finished && (
                <Button size="sm" className="mt-2.5" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>Edit</Button>
              )}
            </>
          )}
        </div>
      )}
    </li>
  )
}

const rank = (j: Automation) => (j.state === 'completed' ? 2 : j.state === 'paused' ? 1 : 0)

/** One agent's automations under its name: what runs first, then paused, then (when shown) finished. */
/** Timers on the VM itself (systemd, not Hermes): shown so nothing scheduled is hidden, but changed only on the VM. */
function VmTimers({ timers }: { timers: VmTimer[] }) {
  return (
    <section className="rounded-xl border border-line" aria-label="On the VM itself">
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Server className="size-4 text-ink-faint" />
        <span className="text-[13px] font-medium text-ink">On the VM itself</span>
        <span className="num text-2xs text-ink-faint">{timers.length} timer{timers.length === 1 ? '' : 's'} · read only</span>
      </header>
      <ul className="divide-y divide-line">
        {timers.map((t) => (
          <li key={t.unit} className="flex items-center gap-3 px-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13px] text-ink">
                <span className="truncate">{t.label || t.unit}</span>
                {!t.described && <span className="rounded-full border border-runway/40 px-1.5 text-[10px] text-[#fcd34d]" title="On the VM but not in the dashboard's registry yet">new</span>}
              </div>
              <div className="num truncate text-2xs text-ink-faint">{t.unit}.timer · {t.schedule || 'no calendar line'}</div>
            </div>
            <div className="text-right text-2xs text-ink-faint">
              {t.nextAt && <div>next {stamp(t.nextAt)}</div>}
              {t.lastAt && <div>last {ago(t.lastAt)}</div>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Group({ agent, jobs, agents, header, onChange }: {
  agent: AgentState | undefined
  jobs: Automation[]
  agents: AgentState[]
  header: boolean
  onChange: (l: Automation[]) => void
}) {
  const [adding, setAdding] = useState(false)
  const profile = agent?.profile ?? jobs[0]?.profile ?? 'default'
  const on = jobs.filter((j) => rank(j) === 0).length
  const paused = jobs.filter((j) => rank(j) === 1).length
  const sorted = [...jobs].sort((a, b) => rank(a) - rank(b) || (a.nextAt ?? Infinity) - (b.nextAt ?? Infinity))
  return (
    <section className="overflow-hidden rounded-lg border border-line">
      {header && (
        <header className="flex items-center gap-2.5 border-b border-line bg-white/[0.02] px-3 py-2">
          <AgentBadge id={agent?.id ?? chiefId()} />
          <span className="text-[13px] font-medium text-ink">{agent?.name ?? profile}</span>
          <span className="num text-[11px] text-ink-faint">{on} on{paused ? ` · ${paused} paused` : ''}</span>
          <Button size="sm" tone="ghost" className="ml-auto" icon={<Plus className="size-3.5" />} onClick={() => setAdding(true)}
            aria-label={`New automation for ${agent?.name ?? profile}`}>New</Button>
        </header>
      )}
      {sorted.length > 0 ? (
        <ul className="divide-y divide-line">{sorted.map((j) => <Row key={j.id} j={j} agents={agents} onChange={onChange} />)}</ul>
      ) : !adding && <p className="px-3 py-3 text-[12px] text-ink-faint">Nothing scheduled.</p>}
      {adding && (
        <div className="border-t border-line p-3">
          <Form initial={{ profile }} agents={agents} fixedProfile={profile} creating onCancel={() => setAdding(false)}
            onSave={async (p, v) => { onChange(await automationsApi.create(p, { ...v, schedule: v.schedule!, prompt: v.prompt! })); setAdding(false); play('confirm') }} />
        </div>
      )}
    </section>
  )
}

/**
 * The agents' scheduled jobs (Hermes cron), grouped by agent, or one agent's in its editor: when each runs next, how the
 * last run went; pause, resume, run now, edit, delete, or schedule a new one. Every change goes through `hermes cron`.
 */
export function Automations({ agents, profile, className }: { agents: AgentState[]; profile?: string; className?: string }) {
  const mode = useMode((s) => s.mode)
  const [jobs, setJobs] = useState<Automation[] | null>(null)
  const [timers, setTimers] = useState<VmTimer[]>([])
  const [error, setError] = useState<string | null>(null)
  const [showDone, setShowDone] = useState(false)
  const [adding, setAdding] = useState(false)
  useEffect(() => {
    let stop = false
    // every 30 s, so a job Claude or an agent adds on the VM shows without a reload
    const read = () => automationsApi.all().then((l) => { if (!stop) { setJobs(l.jobs); setTimers(l.timers); setError(null) } }).catch((e: unknown) => { if (!stop) setError(e instanceof Error ? e.message : 'Could not read the automations') })
    void read()
    const id = window.setInterval(read, 30_000)
    return () => { stop = true; window.clearInterval(id) }
  }, [mode])
  const all = (jobs ?? []).filter((j) => !profile || j.profile === profile)
  // one-off reminders that have fired stay in jobs.json as 'completed': hidden unless asked for
  const finished = all.filter((j) => j.state === 'completed').length
  const shown = all.filter((j) => showDone || j.state !== 'completed')
  const on = all.filter((j) => rank(j) === 0).length
  const paused = all.filter((j) => rank(j) === 1).length
  // every agent that has something, in the team's order; in the editor just the one
  // (and any profile with jobs the agent list does not know yet, so nothing is hidden)
  const known = agents.map((a) => a.profile)
  const groups = profile ? [profile] : [...known, ...[...new Set(shown.map((j) => j.profile))].filter((p) => !known.includes(p))].filter((p) => shown.some((j) => j.profile === p))
  const doneToggle = finished > 0 && (
    <button type="button" aria-pressed={showDone} onClick={() => setShowDone(!showDone)}
      className={cn('press rounded-full border px-2.5 py-0.5 text-[11px]', showDone ? 'border-line-strong text-ink' : 'border-line text-ink-faint hover:text-ink-dim')}>
      {showDone ? 'Hide' : 'Show'} {finished} finished
    </button>
  )
  const body = (
    <div className="space-y-3">
      {error && <p role="alert" className="text-[12px] text-[#fca5a5]">{error}</p>}
      {!jobs && !error && <div className="h-24 animate-pulse rounded-lg bg-white/[0.03]" />}
      {profile && doneToggle && <div className="flex justify-end">{doneToggle}</div>}
      {jobs && groups.map((p) => (
        <Group key={p} agent={agents.find((a) => a.profile === p)} jobs={shown.filter((j) => j.profile === p)} agents={agents} header={!profile} onChange={setJobs} />
      ))}
      {jobs && !profile && groups.length === 0 && <p className="text-[12px] text-ink-faint">No automations yet.</p>}
      {!profile && timers.length > 0 && <VmTimers timers={timers} />}
      {!profile && (adding ? (
        <Form initial={{}} agents={agents} creating onCancel={() => setAdding(false)}
          onSave={async (p, v) => { setJobs(await automationsApi.create(p, { ...v, schedule: v.schedule!, prompt: v.prompt! })); setAdding(false); play('confirm') }} />
      ) : (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-1">
          <Button size="sm" tone="memory" icon={<Plus className="size-3.5" />} onClick={() => setAdding(true)}>New automation</Button>
          <span className="text-2xs text-ink-faint">or the New button on an agent’s row</span>
        </div>
      ))}
      <p className="pt-1 text-2xs text-ink-faint">{mode === 'live' ? 'Read from each agent’s cron/jobs.json; changes go through hermes cron on the VM and are logged. A paused job whose time has passed runs once when resumed.' : 'Demo: changes stay in this tab.'}</p>
    </div>
  )
  if (profile) return body
  return (
    <Panel title="Automations" className={className}
      aside={jobs ? <span className="flex items-center gap-3"><span className="num text-2xs text-ink-faint">{on} on · {paused} paused</span>{doneToggle}</span> : null}>
      {body}
    </Panel>
  )
}
