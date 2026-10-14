import { ChevronDown, Cloud, KeyRound, Plus, RefreshCw, Sparkles, Wrench } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { ago, dateShort } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { agentName, useRoster } from '@/telemetry/agents'
import { useMode } from '@/telemetry/mode'
import { useSettings } from '@/telemetry/settings'
import { integrationsApi, mcp, type Hub, type IntegrationCard, type IntegrationStatus, type Suggestion } from '@/telemetry/tools'
import { AgentBadge } from '@/ui/AgentBadge'
import { Button } from '@/ui/Button'
import { Chip, type Signal } from '@/ui/Chip'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'

const STATUS: Record<IntegrationStatus, { label: string; signal: Signal; ring: string }> = {
  connected: { label: 'Connected', signal: 'ok', ring: 'border-line' },
  expiring: { label: 'Expiring soon', signal: 'warn', ring: 'border-runway/40' },
  attention: { label: 'Attention needed', signal: 'alarm', ring: 'border-alarm/45' },
  unknown: { label: 'Not checked', signal: 'idle', ring: 'border-line' },
  off: { label: 'Not in use', signal: 'idle', ring: 'border-line' },
}
const ORDER: IntegrationStatus[] = ['attention', 'expiring', 'unknown', 'connected', 'off']

function money(value: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(value)
}

/** The same frame for every card: title row, one big line, two small ones, then who uses it and where its secret lives. */
function Frame({ title, kind, chip, headline, lines, footer, ring = 'border-line', badge }: {
  title: string; kind: string; chip: React.ReactNode; headline: React.ReactNode; lines: string[]; footer: React.ReactNode; ring?: string; badge?: React.ReactNode
}) {
  return (
    <article className={cn('glass flex h-[236px] flex-col border p-4', ring)}>
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-1.5 text-[14px] font-semibold text-ink"><span className="truncate">{title}</span>{badge}</h3>
          <p className="truncate text-2xs text-ink-faint" title={kind}>{kind}</p>
        </div>
        {chip}
      </header>
      <div className="mt-3 flex h-10 min-w-0 items-end">{headline}</div>
      <ul className="mt-2 min-h-[36px] space-y-0.5 text-[12px] text-ink-dim">
        {lines.slice(0, 2).map((f) => <li key={f} className="truncate" title={f}>{f}</li>)}
      </ul>
      <div className="mt-auto space-y-1.5 border-t border-line pt-3">{footer}</div>
    </article>
  )
}

function UsedBy({ ids, none = 'nothing uses it yet' }: { ids: string[]; none?: string }) {
  return (
    <div className="flex h-5 items-center gap-1.5 text-2xs text-ink-faint">
      {ids.length ? <>used by {ids.map((id) => <AgentBadge key={id} id={id} />)}</> : none}
    </div>
  )
}

function Card({ c, extra }: { c: IntegrationCard; extra?: React.ReactNode }) {
  const s = STATUS[c.status]
  const b = c.balance
  const big = b && b.value !== null
    ? <span className="num text-[24px] leading-none font-semibold tracking-tight text-ink">
        {b.currency ? money(b.value, b.currency) : `${Math.round(b.value / 1000)}k`}
        {b.limit ? <span className="ml-1.5 text-[12px] font-normal text-ink-faint">of {Math.round(b.limit / 1000)}k credits</span> : null}
      </span>
    : <span className="truncate text-[15px] font-medium text-ink" title={c.facts[0]}>{c.facts[0] ?? '—'}</span>
  const lines = b && b.value !== null ? c.facts : c.facts.slice(1)
  return (
    <Frame title={c.name} kind={c.kind} ring={s.ring} headline={big} lines={lines}
      chip={<Chip signal={s.signal} breathe={c.status === 'connected'}>{s.label}</Chip>}
      badge={!c.described && <span className="rounded-full border border-runway/40 px-1.5 text-[10px] font-normal text-[#fcd34d]" title="Found on the VM; not described in the dashboard's registry yet">new</span>}
      footer={<>
        <UsedBy ids={c.usedBy} none={c.id === 'drive' ? 'the VM itself (nightly)' : undefined} />
        {c.status === 'connected' || c.status === 'off'
          ? <p className="flex items-center gap-1.5 text-2xs text-ink-faint" title={`${c.secret} (where the secret lives; its value is never shown)`}><KeyRound className="size-3 shrink-0" /><span className="num truncate">{c.secret}</span></p>
          : <p className="flex items-center gap-1.5 text-2xs text-[#fcd34d]" title={c.fix}><Wrench className="size-3 shrink-0" /><span className="truncate">{c.fix}</span></p>}
        {extra}
      </>} />
  )
}

/** The Azure credit: a student plan has no API, so it is the figure from the portal (the Runway counts down from it). */
function AzureCard() {
  const settings = useSettings((s) => s.settings)
  const save = useSettings((s) => s.save)
  const [open, setOpen] = useState(false)
  const [v, setV] = useState({ balance: '', asOf: '' })
  const cr = settings?.credit
  const input = 'rounded-lg border border-line bg-white/[0.02] px-2.5 py-1.5 text-[12px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'
  return (
    <Frame title="Azure (the VM)" kind="student credit · no balance API" chip={<Chip signal="idle">from the portal</Chip>}
      headline={cr ? <span className="num text-[24px] leading-none font-semibold tracking-tight text-ink">{money(cr.balance)}<span className="ml-1.5 text-[12px] font-normal text-ink-faint">on {cr.as_of}</span></span> : <span className="text-ink-faint">not typed in yet</span>}
      lines={open ? [] : [`burns about ${cr ? money(cr.burn_per_day) : '$1.20'} a day`, 'the Runway counts down from this figure']}
      footer={open ? (
        <div className="flex flex-wrap items-center gap-2">
          <input className={cn(input, 'num w-20')} inputMode="decimal" placeholder={cr ? String(cr.balance) : '100'} value={v.balance}
            onChange={(e) => setV({ ...v, balance: e.target.value.replace(/[^0-9.]/g, '') })} aria-label="Credit left in dollars" />
          <input className={cn(input, 'num w-34')} type="date" value={v.asOf} onChange={(e) => setV({ ...v, asOf: e.target.value })} aria-label="Date of the figure" />
          <ConfirmButton label="Save" confirmLabel="Save it" tone="memory" size="sm" disabled={!v.balance || !v.asOf}
            onConfirm={async () => { await save({ credit: { balance: Number(v.balance), as_of: v.asOf, burn_per_day: cr?.burn_per_day ?? 1.2, start: cr?.start ?? 100 } }); setV({ balance: '', asOf: '' }); setOpen(false); play('confirm') }} />
          <Button size="sm" tone="ghost" onClick={() => setOpen(false)}>Cancel</Button>
        </div>
      ) : (
        <>
          <UsedBy ids={[]} none="the VM itself" />
          <button type="button" onClick={() => setOpen(true)} className="press text-2xs text-memory hover:underline">Type today’s figure from portal.azure.com</button>
        </>
      )} />
  )
}

function SuggestionCard({ s, onAdded }: { s: Suggestion; onAdded: () => Promise<void> }) {
  const mode = useMode((m) => m.mode)
  const [done, setDone] = useState<string | null>(null)
  const roster = useRoster((r) => r.list)
  const who = s.agents.map((a) => agentName(a)).join(' and ')
  const login = s.auth === 'oauth' ? `then sign in once, on the VM: sudo -u hermes -i hermes -p ${s.for[0]} mcp login ${s.catalog}` : ''
  return (
    <Frame title={s.name} kind={s.description || 'from Hermes’ catalog'} chip={<Chip signal="memory">{s.cost.split(' · ')[0] || 'free'}</Chip>}
      headline={<span className="line-clamp-2 text-[13px] leading-snug text-ink" title={s.why}>{s.why}</span>}
      lines={[s.cost.includes('·') ? s.cost.split(' · ').slice(1).join(' · ') : s.auth === 'oauth' ? 'one sign-in' : 'no sign-in, no key']}
      footer={<>
        <UsedBy ids={s.agents} none="any agent" />
        {done ? <p className="text-2xs text-[#6ee7b7]" title={done}>{done}</p> : s.oneClick ? (
          <ConfirmButton label={`Add to ${who}`} confirmLabel={`Yes, add ${s.name}`} tone="memory" size="sm" icon={<Plus className="size-3.5" />}
            onConfirm={async () => {
              const out = await mcp.add({ source: 'catalog', name: s.catalog, entry: s.catalog, profiles: s.for })
              setDone(`Added to ${out.added.map((p) => roster.find((a) => a.profile === p)?.name ?? agentName(p)).join(', ') || 'nobody'}. ${mode === 'live' ? 'It loads after a quiet restart (the yellow bar)' : 'Demo only'}${login ? `; ${login}` : '.'}`)
              play('confirm'); await onAdded()
            }} />
        ) : <p className="text-2xs text-ink-faint">needs installing on the VM: ask Claude to add it</p>}
      </>} />
  )
}

function Section({ title, aside, children, open: start = true }: { title: string; aside?: React.ReactNode; children: React.ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(start)
  return (
    <section className="mt-6">
      <div className="mb-2.5 flex items-center gap-2">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="press flex items-center gap-1.5 text-[13px] font-semibold text-ink">
          <ChevronDown className={cn('size-4 text-ink-faint transition-transform', !open && '-rotate-90')} />{title}
        </button>
        <span className="min-w-0 flex-1 truncate text-2xs text-ink-faint">{aside}</span>
      </div>
      {open && children}
    </section>
  )
}

const GRID = 'grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-2 xl:grid-cols-3'

/** Integrations: every outside service the agents sign in to, whether it still works, the balances, the optional add-ons,
 *  what is on the VM but nobody described, and what could be added next. */
export default function IntegrationsView() {
  const mode = useMode((s) => s.mode)
  const [hub, setHub] = useState<Hub | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useNow(60_000)
  useEffect(() => {
    let stop = false
    const read = () => integrationsApi.get(false).then((h) => { if (!stop) { setHub(h); setBusy(false) } })
      .catch((e: unknown) => { if (!stop) { setError(e instanceof Error ? e.message : 'Could not read the integrations'); setBusy(false) } })
    void read()
    const id = window.setInterval(read, 60_000)          // what Claude or an agent adds on the VM shows within a minute
    return () => { stop = true; window.clearInterval(id) }
  }, [mode])
  const refresh = async () => {
    setBusy(true); setError(null)
    try { setHub(await integrationsApi.get(true)); play('tick') } catch (e) { setError(e instanceof Error ? e.message : 'Could not check') } finally { setBusy(false) }
  }
  const all = hub?.cards ?? []
  const live = all.filter((c) => c.inUse).sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
  const addons = all.filter((c) => !c.inUse && c.addon)
  const off = all.filter((c) => !c.inUse && !c.addon)
  const count = (s: IntegrationStatus) => live.filter((c) => c.status === s).length
  const newCards = live.filter((c) => !c.described).length
  const reset = all.find((c) => c.id === 'elevenlabs')?.balance?.resetAt
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] p-3 md:p-6">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <p className="min-w-0 flex-1 text-[13px] text-ink-dim">Every outside service the agents sign in to: whether it still works, and what is left on the paid ones. Checked from the VM at most once an hour; anything new on the VM shows up here by itself.</p>
          {hub && (
            <span className="flex flex-wrap items-center gap-2 text-2xs">
              <Chip signal="ok">{count('connected')} connected</Chip>
              {count('expiring') > 0 && <Chip signal="warn">{count('expiring')} expiring</Chip>}
              {count('attention') > 0 && <Chip signal="alarm">{count('attention')} need attention</Chip>}
              {count('unknown') > 0 && <Chip signal="idle">{count('unknown')} not checked</Chip>}
            </span>
          )}
          <Button size="sm" tone="ghost" icon={<RefreshCw className={cn('size-3.5', busy && 'animate-spin')} />} disabled={busy} onClick={refresh}>
            {busy ? 'Checking…' : hub?.checkedAt ? `checked ${ago(hub.checkedAt)}` : 'Check now'}
          </Button>
        </div>
        {error && <p role="alert" className="mb-3 text-[12px] text-[#fca5a5]">{error}</p>}
        {!hub && !error ? <div className="glass h-64 animate-pulse" /> : (
          <>
            <div className={GRID}>
              {live.map((c) => <Card key={c.id} c={c} />)}
              <AzureCard />
            </div>

            {hub && (hub.found.length > 0 || newCards > 0) && (
              <Section title="Found on the VM, not described yet" aside="so nothing added outside the dashboard goes unseen">
                <div className="glass border border-runway/30 p-4 text-[12px] text-ink-dim">
                  <p>These are on the VM but the dashboard's registry (<span className="num">dashboard/bridge/registry.json</span>) does not say what they are{newCards ? `; the cards marked “new” above too` : ''}. Ask Claude: “describe these in the dashboard registry”.</p>
                  {hub.found.length > 0 && (
                    <ul className="mt-3 grid gap-x-6 gap-y-1 sm:grid-cols-2">
                      {hub.found.map((k) => (
                        <li key={k.key} className="flex items-center gap-2"><KeyRound className="size-3 shrink-0 text-ink-faint" /><span className="num text-ink">{k.key}</span><span className="truncate text-2xs text-ink-faint">{k.where.join(', ')}</span></li>
                      ))}
                    </ul>
                  )}
                </div>
              </Section>
            )}

            {hub && hub.suggestions.length > 0 && (
              <Section title="Suggested for you" aside={<><Sparkles className="mr-1 inline size-3" />from Hermes’ own catalog, picked for study, fitness and everyday admin; all free</>}>
                <div className={GRID}>
                  {hub.suggestions.map((s) => <SuggestionCard key={s.catalog} s={s} onAdded={async () => setHub(await integrationsApi.get(false))} />)}
                </div>
              </Section>
            )}

            {addons.length > 0 && (
              <Section title={`Add-ons not switched on · ${addons.length}`} aside="optional; the kit’s add-on commands switch them on, and they show up here by themselves">
                <div className={GRID}>{addons.map((c) => <Card key={c.id} c={c} />)}</div>
              </Section>
            )}

            {off.length > 0 && (
              <Section title={`Not in use · ${off.length}`} aside="old keys still stored on the VM; nothing reads them" open={false}>
                <div className={GRID}>{off.map((c) => <Card key={c.id} c={c} />)}</div>
              </Section>
            )}
          </>
        )}
        <Panel title="How this works" className="mt-6">
          <p className="flex items-start gap-2 text-[12px] text-ink-dim">
            <Cloud className="mt-0.5 size-3.5 shrink-0 text-ink-faint" />
            <span>The VM asks Telegram, Gemini, DeepSeek and (with their add-ons) Gmail, iCloud and ElevenLabs who it is, then signs out; nothing is read or changed.
              Moodle is judged by its keep-alive job, Google Drive by last night’s backup, Mem0 by its service, MCP servers by whether they are switched on.
              Every MCP server and every secret name on the VM is listed, described or not. Only the paths of the files that hold secrets are shown, never the secrets.
              {mode === 'demo' ? ' Demo figures.' : ''}{reset ? ` ElevenLabs resets ${dateShort(reset)}.` : ''}</span>
          </p>
        </Panel>
      </div>
    </div>
  )
}
