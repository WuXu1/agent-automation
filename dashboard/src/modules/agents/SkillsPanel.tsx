import { Check, Download, Eye, PenLine, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useMode } from '@/telemetry/mode'
import { skills as api, type HubSkill, type Skill } from '@/telemetry/tools'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { EnhanceArea } from '@/ui/EnhanceArea'

const input = 'w-full rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'
const SOURCE: Record<Skill['source'], { label: string; tone: string; title: string }> = {
  builtin: { label: 'Hermes', tone: 'border-line text-ink-faint', title: 'Ships with Hermes: switch it off rather than remove it' },
  hub: { label: 'hub', tone: 'border-memory/40 text-memory', title: 'Installed from a skills registry' },
  local: { label: 'yours', tone: 'border-agent/40 text-[#f0abfc]', title: 'Written for this setup' },
  dashboard: { label: 'team list', tone: 'border-line text-ink-faint', title: 'Written by the dashboard from the team chart' },
}

function Toggle({ on, staged, onClick, label }: { on: boolean; staged: boolean; onClick: () => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} onClick={onClick}
      className={cn('press relative h-5 w-9 shrink-0 rounded-full border transition-colors', on ? 'border-agent/60 bg-agent/40' : 'border-line-strong bg-white/[0.04]',
        staged && 'ring-1 ring-runway/70 ring-offset-1 ring-offset-transparent')}>
      <span className={cn('absolute top-0.5 size-3.5 rounded-full bg-ink transition-[left] duration-150', on ? 'left-[18px]' : 'left-0.5')} />
    </button>
  )
}

/** One agent's skills: switch them on or off (staged, applied together), remove added ones, find more, write your own. */
export function SkillsPanel({ profile, agentName }: { profile: string; agentName: string }) {
  const mode = useMode((s) => s.mode)
  const [list, setList] = useState<Skill[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [show, setShow] = useState<'all' | 'on' | 'off' | 'added'>('all')
  const [staged, setStaged] = useState<Record<string, boolean>>({})
  const [pane, setPane] = useState<'list' | 'find' | 'write'>('list')

  useEffect(() => {
    let stop = false
    api.list(profile).then((l) => { if (!stop) setList(l) }).catch((e: unknown) => { if (!stop) setError(e instanceof Error ? e.message : 'Could not read the skills') })
    return () => { stop = true }
  }, [profile])

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase()
    return (list ?? []).filter((s) => {
      const on = staged[s.name] ?? s.enabled
      if (show === 'on' && !on) return false
      if (show === 'off' && on) return false
      if (show === 'added' && s.source !== 'hub' && s.source !== 'local') return false
      return !t || s.name.includes(t) || s.description.toLowerCase().includes(t) || s.category.includes(t)
    })
  }, [list, q, show, staged])
  const groups = useMemo(() => {
    const g = new Map<string, Skill[]>()
    for (const s of shown) g.set(s.category || 'other', [...(g.get(s.category || 'other') ?? []), s])
    return [...g.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [shown])
  const count = Object.keys(staged).length
  const onCount = (list ?? []).filter((s) => s.enabled).length

  const toggle = (s: Skill) => {
    play('tick')
    setStaged((st) => {
      const next = { ...st }
      if (s.name in next) delete next[s.name]
      else next[s.name] = !s.enabled
      return next
    })
  }
  const apply = async () => {
    let l = list
    for (const [name, on] of Object.entries(staged)) l = await api.setEnabled(profile, name, on)
    setList(l ? [...l] : l)
    setStaged({})
    play('confirm')
  }

  if (error) return <p role="alert" className="text-[12px] text-[#fca5a5]">{error}</p>
  if (!list) return <div className="h-40 animate-pulse rounded-lg bg-white/[0.03]" />

  return (
    <div className="space-y-3">
      <div className="flex gap-1 rounded-lg border border-line p-0.5 text-[12px]">
        {([['list', `Installed · ${onCount} on`], ['find', 'Find on skills.sh'], ['write', 'Write one']] as const).map(([k, label]) => (
          <button key={k} type="button" aria-pressed={pane === k} onClick={() => setPane(k)}
            className={cn('press flex-1 rounded-md px-2.5 py-1.5', pane === k ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{label}</button>
        ))}
      </div>

      {pane === 'list' && (
        <>
          <div className="flex items-center gap-2">
            <input className={cn(input, 'min-w-0 flex-1')} value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Filter ${list.length} skills`} aria-label="Filter skills" />
            <select className="w-28 shrink-0 rounded-lg border border-line bg-white/[0.02] px-2.5 py-2 text-[13px] text-ink outline-none focus:border-line-strong" value={show} onChange={(e) => setShow(e.target.value as typeof show)} aria-label="Show">
              <option value="all">All</option><option value="on">On</option><option value="off">Off</option><option value="added">Added</option>
            </select>
          </div>
          {count > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-runway/40 bg-runway/[0.07] px-3 py-2">
              <span className="flex-1 text-[12px] text-[#fcd34d]">{count} change{count > 1 ? 's' : ''} staged</span>
              <Button tone="ghost" size="sm" onClick={() => setStaged({})}>Discard</Button>
              <ConfirmButton label={`Apply ${count}`} confirmLabel={`Write to ${agentName}'s config`} tone="memory" icon={<Check className="size-3.5" />} onConfirm={apply} />
            </div>
          )}
          <div className="space-y-3">
            {groups.map(([cat, items]) => (
              <section key={cat}>
                <h4 className="mb-1 text-2xs font-medium tracking-wide text-ink-faint uppercase">{cat.replace(/-/g, ' ')} <span className="num normal-case">· {items.length}</span></h4>
                <ul className="divide-y divide-line rounded-lg border border-line">
                  {items.map((s) => {
                    const on = staged[s.name] ?? s.enabled
                    return (
                      <li key={s.name} className="flex items-center gap-2.5 px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className={cn('num truncate text-[12px]', on ? 'text-ink' : 'text-ink-faint line-through decoration-ink-faint/50')}>{s.name}</span>
                            <span title={SOURCE[s.source].title} className={cn('rounded-full border px-1.5 text-[10px]', SOURCE[s.source].tone)}>{SOURCE[s.source].label}</span>
                          </div>
                          <p className="truncate text-2xs text-ink-faint" title={s.description}>{s.description}</p>
                        </div>
                        {(s.source === 'hub' || s.source === 'local') && (
                          <ConfirmButton label="Remove" confirmLabel={`Remove ${s.name}`} tone="danger" size="sm" icon={<Trash2 className="size-3.5" />}
                            onConfirm={async () => { setList(await api.remove(profile, s.name)); play('warn') }} />
                        )}
                        {s.source !== 'dashboard' && <Toggle on={on} staged={s.name in staged} onClick={() => toggle(s)} label={`${s.name} ${on ? 'on' : 'off'}`} />}
                      </li>
                    )
                  })}
                </ul>
              </section>
            ))}
            {groups.length === 0 && <p className="text-[12px] text-ink-faint">Nothing matches.</p>}
          </div>
          <p className="text-2xs text-ink-faint">{mode === 'live' ? 'Switching writes skills.disabled in the profile’s config.yaml (backed up first). Skills reach new chats (/new); no restart needed. Removing archives your own skill on the VM first.' : 'Demo: changes stay in this tab.'}</p>
        </>
      )}

      {pane === 'find' && <FindSkills profile={profile} agentName={agentName} onInstalled={async () => setList(await api.list(profile))} />}
      {pane === 'write' && <WriteSkill profile={profile} agentName={agentName} onCreated={(l) => { setList(l); setPane('list') }} />}
    </div>
  )
}

function installs(n: number): string {
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}m` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n)
}

function FindSkills({ profile, agentName, onInstalled }: { profile: string; agentName: string; onInstalled: () => Promise<void> }) {
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<HubSkill[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<Record<string, string>>({})
  const [done, setDone] = useState<Record<string, string>>({})
  const box = useRef<HTMLInputElement>(null)
  useEffect(() => { box.current?.focus() }, [])
  const search = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!q.trim()) return
    setBusy(true); setError(null)
    try { setResults(await api.search(profile, q.trim())) } catch (err) { setError(err instanceof Error ? err.message : 'Search failed') } finally { setBusy(false) }
  }
  return (
    <div className="space-y-3">
      <form onSubmit={search} className="flex gap-2">
        <input ref={box} className={cn(input, 'flex-1')} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. pdf, spreadsheets, flashcards" aria-label="Search skills.sh" />
        <Button type="submit" tone="memory" icon={<Search className="size-3.5" />} disabled={busy || !q.trim()}>{busy ? 'Searching…' : 'Search skills.sh'}</Button>
      </form>
      <p className="text-2xs text-ink-faint">Searches skills.sh only, most installed first. Hermes scans every skill before it installs and refuses one its scanner blocks.</p>
      {error && <p role="alert" className="text-[12px] text-[#fca5a5]">{error}</p>}
      {results && results.length === 0 && <p className="text-[12px] text-ink-faint">Nothing found.</p>}
      <ul className="space-y-2">
        {results?.map((r) => (
          <li key={r.identifier} className="rounded-lg border border-line px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="num text-[12px] text-ink">{r.name}</span>
              {r.trust_level === 'trusted' && <span className="rounded-full border border-[#6ee7b7]/40 px-1.5 text-[10px] text-[#6ee7b7]">trusted</span>}
              {r.installs !== null && <span className="num ml-auto text-[10px] text-ink-faint">{installs(r.installs)} installs</span>}
            </div>
            <p className="num mt-0.5 truncate text-2xs text-ink-dim">from {r.repo}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" tone="ghost" icon={<Eye className="size-3.5" />} onClick={async () => {
                try { const t = await api.inspect(profile, r.identifier); setPreview((p) => ({ ...p, [r.identifier]: t })) }
                catch (err) { setPreview((p) => ({ ...p, [r.identifier]: err instanceof Error ? err.message : 'Could not read it' })) }
              }}>Preview</Button>
              {done[r.identifier] ? <span className="text-2xs text-[#6ee7b7]">{done[r.identifier]}</span> : (
                <ConfirmButton label="Install" confirmLabel={`Install on ${agentName}`} tone="memory" size="sm" icon={<Download className="size-3.5" />}
                  onConfirm={async () => { const t = await api.install(profile, r.identifier); setDone((d) => ({ ...d, [r.identifier]: t.split('\n').pop() || 'Installed' })); play('confirm'); await onInstalled() }} />
              )}
            </div>
            {preview[r.identifier] && <pre className="mt-2 max-h-56 overflow-auto rounded-md bg-black/30 p-2 text-[11px] whitespace-pre-wrap text-ink-dim">{preview[r.identifier]}</pre>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function WriteSkill({ profile, agentName, onCreated }: { profile: string; agentName: string; onCreated: (l: Skill[]) => void }) {
  const [name, setName] = useState('')
  const [when, setWhen] = useState('')
  const [body, setBody] = useState('')
  const ok = /^[a-z0-9][a-z0-9_-]{1,47}$/.test(name) && when.trim() && body.trim()
  return (
    <div className="space-y-3">
      <label className="block">
        <span className="mb-1 block text-[12px] font-medium">Name</span>
        <input className={cn(input, 'num')} value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-'))} placeholder="rain-plan" />
      </label>
      <label className="block">
        <span className="mb-1 block text-[12px] font-medium">When to use it <span className="font-normal text-ink-faint">· one line; {agentName} reads it to decide</span></span>
        <input className={input} value={when} maxLength={300} onChange={(e) => setWhen(e.target.value)} placeholder="Use when rain is forecast for a tennis session." />
      </label>
      <div>
        <span className="mb-1 block text-[12px] font-medium">Steps</span>
        <EnhanceArea field="skill" aria-label="Steps" name={agentName} about={when} className={cn(input, 'min-h-[200px] resize-y font-mono text-[12px] leading-relaxed')}
          value={body} onChange={setBody} maxLength={20000} placeholder={'1. Check the forecast for the session.\n2. If rain is likely, offer the indoor court.'} />
      </div>
      <ConfirmButton label="Create skill" confirmLabel={`Add ${name || 'it'} to ${agentName}`} tone="memory" icon={<PenLine className="size-3.5" />} disabled={!ok}
        onConfirm={async () => { onCreated(await api.create(profile, { name, description: when.trim(), body: body.trim() })); play('confirm') }} />
    </div>
  )
}
