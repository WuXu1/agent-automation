import { Check, Sparkles, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useApp } from '@/app/store'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { api } from '@/telemetry/live/client'
import { useMode } from '@/telemetry/mode'
import { useSettings } from '@/telemetry/settings'
import { brainApi } from '@/telemetry/tools'
import { Button } from '@/ui/Button'
import { Chip } from '@/ui/Chip'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'

const input = 'rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'

/** The model for the dashboard's own AI jobs (✦ enhance, tidying and sorting memories); agents keep their own. */
function DashboardAi() {
  const settings = useSettings((s) => s.settings)
  const save = useSettings((s) => s.save)
  const [error, setError] = useState<string | null>(null)
  const set = async (patch: Parameters<typeof save>[0]) => {
    setError(null)
    try { await save(patch); play('confirm') } catch (e) { setError(e instanceof Error ? e.message : 'Could not save') }
  }
  if (!settings) return <Panel title="Dashboard AI" className="lg:col-span-6"><div className="h-40 animate-pulse rounded-lg bg-white/[0.03]" /></Panel>
  return (
    <Panel title="Dashboard AI" aside={<span className="text-2xs text-ink-faint">✦ enhance, tidying and sorting memories</span>} className="lg:col-span-6">
      <p className="mb-2.5 text-[12px] text-ink-dim">Default model for everything here that is not one agent’s own work. Each agent keeps the model set in its profile.</p>
      <fieldset className="space-y-1.5">
        <legend className="sr-only">Default model</legend>
        {settings.models.map((m) => (
          <label key={m.id} className={cn('press flex w-full cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-left',
              !m.available && 'cursor-not-allowed opacity-40', settings.model === m.id ? 'border-agent/60 bg-agent/10' : 'border-line hover:border-line-strong')}>
            <input type="radio" name="dash-model" className="sr-only" checked={settings.model === m.id} disabled={!m.available}
              onChange={() => void set({ model: m.id })} />
            <span className={cn('grid size-4 shrink-0 place-items-center rounded-full border', settings.model === m.id ? 'border-agent' : 'border-line-strong')}>
              {settings.model === m.id && <span className="size-2 rounded-full bg-agent" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] text-ink">{m.label} <span className="num text-2xs text-ink-faint">{m.id}</span></span>
              <span className="block text-2xs text-ink-faint">{m.available ? m.note : `no ${m.provider} key on the VM`}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <label className="mt-3.5 flex items-center gap-2.5 text-[12px] text-ink-dim">
        <input type="checkbox" checked={settings.tidyMemories} onChange={(e) => void set({ tidyMemories: e.target.checked })} />
        <span><Sparkles className="mr-1 inline size-3.5 text-[#f0abfc]" />Tidy new memories with AI by default (you still see it before it is saved)</span>
      </label>
      {error && <p role="alert" className="mt-2 text-[12px] text-[#fca5a5]">{error}</p>}
    </Panel>
  )
}

/** The brain's sections: rename, merge one into another, or have the AI sort every note again. */
function Sections() {
  const mode = useMode((s) => s.mode)
  const sections = useBrain((s) => s.sections)
  const graph = useBrain((s) => s.graph)
  const loadBrain = useBrain((s) => s.loadBrain)
  const setBrain = useBrain((s) => s.setBrain)
  const assign = useBrain((s) => s.assign)
  const sorting = useBrain((s) => s.sorting)
  const counts = useMemo(() => {
    const m = new Map<string, number>()
    for (const n of graph.nodes) m.set(n.cluster, (m.get(n.cluster) ?? 0) + 1)
    return m
  }, [graph])
  const [edit, setEdit] = useState<Record<string, { label: string; blurb: string }>>({})
  const done = (id: string) => setEdit((cur) => { const next = { ...cur }; delete next[id]; return next })
  const [into, setInto] = useState<Record<string, string>>({})
  const rename = async (id: string) => {
    const e = edit[id]!
    if (mode === 'live') { await brainApi.rename(id, e.label, e.blurb); await loadBrain() }
    else setBrain(sections.map((s) => (s.id === id ? { ...s, label: e.label, blurb: e.blurb } : s)))
    done(id)
    play('confirm')
  }
  const merge = async (id: string) => {
    const target = into[id]!
    if (mode === 'live') { await brainApi.merge(id, target); await loadBrain() }
    else {
      const moved = Object.fromEntries(Object.entries(assign).map(([k, v]) => [k, v === id ? target : v]))
      for (const n of graph.nodes) if (n.cluster === id) moved[n.id] = target
      setBrain(sections.filter((s) => s.id !== id), moved)
    }
    play('warn')
  }
  return (
    <Panel title="Brain sections" className="lg:col-span-6"
      aside={sorting ? <Chip signal="memory" breathe>AI sorting new notes</Chip> : <span className="text-2xs text-ink-faint">{sections.length} sections</span>}>
      <p className="mb-2.5 text-[12px] text-ink-dim">The AI puts every new note (yours, or one an agent saves on Telegram) in the section it fits, and starts a new one when nothing fits.</p>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {sections.map((s) => {
          const e = edit[s.id]
          return (
            <li key={s.id} className="px-3 py-2">
              {e ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  <input className={cn(input, 'w-44 py-1.5')} value={e.label} maxLength={32} aria-label="Section name" onChange={(ev) => setEdit({ ...edit, [s.id]: { ...e, label: ev.target.value } })} />
                  <input className={cn(input, 'min-w-0 flex-1 py-1.5')} value={e.blurb} maxLength={80} aria-label="Section description" onChange={(ev) => setEdit({ ...edit, [s.id]: { ...e, blurb: ev.target.value } })} />
                  <Button size="sm" tone="memory" icon={<Check className="size-3.5" />} disabled={!e.label.trim()} onClick={() => void rename(s.id)}>Save</Button>
                  <Button size="sm" tone="ghost" onClick={() => done(s.id)}>Cancel</Button>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="size-2 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12px] text-ink">{s.label} {!s.builtin && <span className="ml-1 rounded-full border border-memory/40 px-1.5 text-[10px] text-memory">started by the AI</span>}</span>
                    <span className="block truncate text-2xs text-ink-faint">{s.blurb}</span>
                  </span>
                  <span className="num w-8 text-right text-[11px] text-ink-dim">{counts.get(s.id) ?? 0}</span>
                  <Button size="sm" tone="ghost" onClick={() => setEdit({ ...edit, [s.id]: { label: s.label, blurb: s.blurb } })}>Rename</Button>
                  {sections.length > 1 && (
                    <span className="inline-flex items-center gap-1">
                      <select className={cn(input, 'w-32 px-2 py-1 text-[12px]')} value={into[s.id] ?? ''} aria-label={`Merge ${s.label} into`}
                        onChange={(ev) => setInto({ ...into, [s.id]: ev.target.value })}>
                        <option value="">Merge into…</option>
                        {sections.filter((x) => x.id !== s.id).map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
                      </select>
                      {into[s.id] && <ConfirmButton label="Merge" confirmLabel={`Move ${counts.get(s.id) ?? 0} notes`} tone="danger" size="sm" onConfirm={() => merge(s.id)} />}
                    </span>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <ConfirmButton label="Re-sort every note" confirmLabel={`Have the AI sort all ${graph.nodes.length} again`} size="sm" icon={<Sparkles className="size-3.5" />}
          disabled={mode !== 'live'} onConfirm={async () => { await brainApi.resort(); await loadBrain(); play('confirm') }} />
        <span className="text-2xs text-ink-faint">{mode === 'live' ? `About ${Math.max(1, Math.ceil(graph.nodes.length / 40))} small AI calls (well under a penny). The notes themselves do not change.` : 'Live only.'}</span>
      </div>
    </Panel>
  )
}

function About() {
  const mode = useMode((s) => s.mode)
  const sound = useApp((s) => s.sound)
  const toggleSound = useApp((s) => s.toggleSound)
  const [version, setVersion] = useState<string | null>(null)
  useEffect(() => {
    if (mode !== 'live') return
    api<{ version: string }>('/health').then((h) => setVersion(h.version)).catch(() => setVersion(null))
  }, [mode])
  return (
    <Panel title="This dashboard" className="lg:col-span-6">
      <dl className="divide-y divide-line text-[12px]">
        <div className="flex items-center justify-between py-2"><dt className="text-ink-dim">Interface sounds</dt>
          <dd><Button size="sm" tone="ghost" icon={sound ? <Volume2 className="size-3.5" /> : <VolumeX className="size-3.5" />} onClick={toggleSound}>{sound ? 'On' : 'Off'}</Button></dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Data</dt><dd className="text-ink">{mode === 'live' ? 'Live, from the VM' : 'Demo (switch at the top)'}</dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Bridge</dt><dd className="num text-ink">{version ? `hermes-dash ${version}` : mode === 'live' ? '…' : 'not connected'}</dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Who may open it</dt><dd className="text-ink">your Tailscale login only</dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Every change</dt><dd className="text-right text-ink">backed up first, logged in <span className="num">hermes-dash/actions.log</span></dd></div>
      </dl>
    </Panel>
  )
}

/** Settings: the dashboard's AI model, the brain's sections, this dashboard (balances moved to Integrations). */
export default function SettingsView() {
  const mode = useMode((s) => s.mode)
  const load = useSettings((s) => s.load)
  useEffect(() => { void load() }, [mode, load])
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] p-3 md:p-6">
        <p className="mb-3 text-[13px] text-ink-dim">The dashboard’s own AI model, how the brain is organised, and this dashboard. Balances and sign-ins are under Integrations.</p>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-12">
          <DashboardAi />
          <Sections />
          <About />
        </div>
      </div>
    </div>
  )
}
