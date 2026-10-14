import { KeyRound, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useMode } from '@/telemetry/mode'
import { mcp, type AddServer as AddInput, type CatalogEntry } from '@/telemetry/tools'
import type { AgentState } from '@/telemetry/types'
import { AgentBadge } from '@/ui/AgentBadge'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Drawer } from '@/ui/Drawer'
import { refreshRestart } from './writes'

export interface AddServerPreset { profiles?: string[]; source?: AddInput['source']; server?: string; from?: string }

const input = 'w-full rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'
const AUTH: Record<CatalogEntry['auth'], string> = { none: 'no account', api_key: 'needs a key', oauth: 'sign in once' }
type Row = { name: string; value: string; secret: boolean }

function Rows({ rows, setRows, keyLabel, keyHint, upper }: { rows: Row[]; setRows: (r: Row[]) => void; keyLabel: string; keyHint: string; upper?: boolean }) {
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_1.4fr_auto_auto] items-center gap-1.5">
          <input className={cn(input, 'num py-1.5')} value={r.name} placeholder={keyHint} aria-label={keyLabel}
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, name: upper ? e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_') : e.target.value } : x)))} />
          <input className={cn(input, 'py-1.5')} type={r.secret ? 'password' : 'text'} autoComplete="off" value={r.value} placeholder="value" aria-label="Value"
            onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
          <button type="button" aria-pressed={r.secret} title={r.secret ? 'Secret: kept in the agent’s .env, never shown again' : 'Not secret: written into the config'}
            onClick={() => setRows(rows.map((x, j) => (j === i ? { ...x, secret: !x.secret } : x)))}
            className={cn('press grid size-8 place-items-center rounded-md border', r.secret ? 'border-runway/50 text-[#fcd34d]' : 'border-line text-ink-faint')}>
            <KeyRound className="size-3.5" />
          </button>
          <button type="button" aria-label="Remove row" onClick={() => setRows(rows.filter((_, j) => j !== i))} className="press grid size-8 place-items-center rounded-md text-ink-faint hover:text-ink">
            <Trash2 className="size-3.5" />
          </button>
        </div>
      ))}
      <button type="button" onClick={() => setRows([...rows, { name: '', value: '', secret: true }])} className="press inline-flex items-center gap-1 text-2xs text-memory hover:underline">
        <Plus className="size-3" />Add {keyLabel.toLowerCase()}
      </button>
    </div>
  )
}

/** Add an MCP server to one or more agents: from Hermes' catalog, one of your own, or copied from an agent that has it. */
export function AddServer({ preset, agents, onClose }: { preset: AddServerPreset | null; agents: AgentState[]; onClose: () => void }) {
  const mode = useMode((s) => s.mode)
  const [source, setSource] = useState<AddInput['source']>(preset?.source ?? 'catalog')
  const [targets, setTargets] = useState<string[]>(preset?.profiles ?? [])
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null)
  const [q, setQ] = useState('')
  const [entry, setEntry] = useState<CatalogEntry | null>(null)
  const [secrets, setSecrets] = useState<Record<string, string>>({})
  const [name, setName] = useState(preset?.server ?? '')
  const [transport, setTransport] = useState<'http' | 'stdio'>('http')
  const [url, setUrl] = useState('')
  const [oauth, setOauth] = useState(false)
  const [headers, setHeaders] = useState<Row[]>([])
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [envRows, setEnvRows] = useState<Row[]>([])
  const [from, setFrom] = useState(preset?.from ?? '')
  const [result, setResult] = useState<string | null>(null)

  useEffect(() => {
    if (!preset || source !== 'catalog' || catalog) return
    let stop = false
    mcp.catalog().then((c) => { if (!stop) setCatalog(c) }).catch(() => { if (!stop) setCatalog([]) })
    return () => { stop = true }
  }, [preset, source, catalog])

  const existing = useMemo(() => {
    const m = new Map<string, AgentState[]>()
    for (const a of agents) for (const s of a.mcp) m.set(s.name, [...(m.get(s.name) ?? []), a])
    return m
  }, [agents])
  const copyName = source === 'copy' ? name : ''
  const holders = existing.get(copyName) ?? []
  const fromProfile = from || holders[0]?.profile || ''
  const serverName = source === 'catalog' ? entry?.name ?? '' : name
  const has = (a: AgentState) => a.mcp.some((m) => m.name === serverName)
  const shownCatalog = (catalog ?? []).filter((c) => !q.trim() || `${c.name} ${c.description}`.toLowerCase().includes(q.trim().toLowerCase()))

  const body: AddInput | null = (() => {
    const profiles = targets.filter((t) => { const a = agents.find((x) => x.profile === t); return a && !has(a) })
    if (!profiles.length || !/^[a-z][a-z0-9_-]{1,39}$/.test(serverName)) return null
    if (source === 'catalog') {
      if (!entry || entry.needsInstall || entry.env.some((e) => e.required && !secrets[e.name]?.trim())) return null
      return { source, name: entry.name, entry: entry.name, profiles, secrets }
    }
    if (source === 'copy') return fromProfile ? { source, name, entry: name, from: fromProfile, profiles } : null
    if (transport === 'http') return /^https?:\/\/\S+$/.test(url) ? { source, name, profiles, transport, url, oauth, headers: headers.filter((h) => h.name && h.value) } : null
    return command.trim() ? { source, name, profiles, transport, command: command.trim(), args: args.split('\n').map((a) => a.trim()).filter(Boolean), env: envRows.filter((e) => e.name && e.value) } : null
  })()

  const add = async () => {
    if (!body) return
    const out = await mcp.add(body)
    await refreshRestart()
    play('confirm')
    const who = out.added.map((p) => agents.find((a) => a.profile === p)?.name ?? p).join(', ')
    setResult(`${serverName} added to ${who || 'nobody (they all had it)'}. ${mode === 'live' ? 'It loads after a quiet gateway restart (the yellow bar).' : ''}${out.note ? ` ${out.note}` : ''}`)
  }

  const footer = preset && (
    <div className="space-y-2">
      {result ? (
        <div className="flex items-start gap-2">
          <p className="flex-1 text-[12px] text-[#6ee7b7]">{result}</p>
          <Button size="sm" onClick={onClose}>Done</Button>
        </div>
      ) : (
        <ConfirmButton label={`Add ${serverName || 'server'}`} confirmLabel={`Add to ${body?.profiles.length ?? 0} agent${body?.profiles.length === 1 ? '' : 's'}`}
          tone="memory" icon={<Plus className="size-3.5" />} disabled={!body} onConfirm={add} />
      )}
      <p className="text-2xs text-ink-faint">{mode === 'live' ? 'Each agent’s config.yaml is backed up and checked before the change. Keys go only into that agent’s .env on the VM and never come back to this page.' : 'Demo: the server appears in this tab only.'}</p>
    </div>
  )

  return (
    <Drawer open={Boolean(preset)} onClose={onClose} wide footer={footer} title="Add an MCP server">
      <div className="space-y-4">
        <div className="flex gap-1 rounded-lg border border-line p-0.5 text-[12px]">
          {([['catalog', 'Hermes catalog'], ['custom', 'Your own'], ['copy', 'Copy from an agent']] as const).map(([k, label]) => (
            <button key={k} type="button" aria-pressed={source === k} onClick={() => { setSource(k); setResult(null) }}
              className={cn('press flex-1 rounded-md px-2.5 py-1.5', source === k ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{label}</button>
          ))}
        </div>

        {source === 'catalog' && (
          <div className="space-y-2">
            <input className={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${catalog?.length ?? ''} Nous-approved servers`} aria-label="Search the catalog" />
            {!catalog ? <div className="h-32 animate-pulse rounded-lg bg-white/[0.03]" /> : (
              <ul className="max-h-[260px] divide-y divide-line overflow-y-auto rounded-lg border border-line">
                {shownCatalog.map((c) => (
                  <li key={c.name}>
                    <button type="button" onClick={() => { setEntry(c); setSecrets({}) }} aria-pressed={entry?.name === c.name}
                      className={cn('press flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-white/[0.03]', entry?.name === c.name && 'bg-agent/10')}>
                      <span className="min-w-0 flex-1">
                        <span className="num block text-[12px] text-ink">{c.name}{existing.has(c.name) ? <span className="text-ink-faint"> · {existing.get(c.name)!.length} agent{existing.get(c.name)!.length > 1 ? 's' : ''} have it</span> : null}</span>
                        <span className="block text-2xs text-ink-faint">{c.description}</span>
                      </span>
                      <span className={cn('shrink-0 rounded-full border px-1.5 text-[10px]', c.needsInstall ? 'border-line text-ink-faint' : c.auth === 'none' ? 'border-memory/40 text-memory' : 'border-runway/40 text-[#fcd34d]')}>
                        {c.needsInstall ? 'install on the VM' : AUTH[c.auth]}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {entry && (
              <div className="rounded-lg border border-line bg-white/[0.02] px-3 py-2.5">
                <p className="text-[12px]"><span className="num text-ink">{entry.name}</span> <span className="text-ink-faint">· {entry.transport === 'http' ? entry.url : 'runs on the VM'}</span></p>
                {entry.needsInstall && <p className="mt-1 text-2xs text-[#fcd34d]">This one installs code on the VM first, so it is a job for the terminal: <span className="num">hermes -p &lt;agent&gt; mcp install {entry.name}</span>.</p>}
                {entry.auth === 'oauth' && <p className="mt-1 text-2xs text-ink-dim">After the restart it needs a one-time sign-in with your account on the VM (<span className="num">hermes -p &lt;agent&gt; mcp login {entry.name}</span>); until then it simply has no tools.</p>}
                {entry.env.map((e) => (
                  <label key={e.name} className="mt-2 block">
                    <span className="mb-1 block text-2xs text-ink-dim">{e.prompt || e.name}{e.required ? '' : ' (optional)'}</span>
                    <input className={cn(input, 'num')} type={e.secret ? 'password' : 'text'} autoComplete="off" value={secrets[e.name] ?? ''}
                      onChange={(ev) => setSecrets((s) => ({ ...s, [e.name]: ev.target.value }))} placeholder={e.name} />
                  </label>
                ))}
                {entry.postInstall && <p className="mt-2 text-2xs whitespace-pre-line text-ink-faint">{entry.postInstall}</p>}
              </div>
            )}
          </div>
        )}

        {source === 'custom' && (
          <div className="space-y-3">
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <label className="block"><span className="mb-1 block text-[12px] font-medium">Name</span>
                <input className={cn(input, 'num')} value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-'))} placeholder="weather" /></label>
              <div><span className="mb-1 block text-[12px] font-medium">Kind</span>
                <div className="flex h-[38px] gap-0.5 rounded-lg border border-line p-0.5">
                  {([['http', 'Web address'], ['stdio', 'Program']] as const).map(([k, l]) => (
                    <button key={k} type="button" aria-pressed={transport === k} onClick={() => setTransport(k)}
                      className={cn('press rounded-md px-2.5 text-[12px]', transport === k ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{l}</button>
                  ))}
                </div>
              </div>
            </div>
            {transport === 'http' ? (
              <>
                <label className="block"><span className="mb-1 block text-[12px] font-medium">Address</span>
                  <input className={cn(input, 'num')} value={url} onChange={(e) => setUrl(e.target.value.trim())} placeholder="https://mcp.example.com/mcp" /></label>
                <label className="flex items-center gap-2 text-[12px] text-ink-dim"><input type="checkbox" checked={oauth} onChange={(e) => setOauth(e.target.checked)} />It signs in with an account (OAuth)</label>
                <div><span className="mb-1 block text-[12px] font-medium">Headers <span className="font-normal text-ink-faint">· e.g. Authorization: Bearer …</span></span>
                  <Rows rows={headers} setRows={setHeaders} keyLabel="Header" keyHint="Authorization" /></div>
              </>
            ) : (
              <>
                <label className="block"><span className="mb-1 block text-[12px] font-medium">Program</span>
                  <input className={cn(input, 'num')} value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" /></label>
                <label className="block"><span className="mb-1 block text-[12px] font-medium">Arguments <span className="font-normal text-ink-faint">· one per line</span></span>
                  <textarea className={cn(input, 'num resize-y')} rows={3} value={args} onChange={(e) => setArgs(e.target.value)} placeholder={'-y\n@example/mcp-server'} /></label>
                <div><span className="mb-1 block text-[12px] font-medium">Variables</span>
                  <Rows rows={envRows} setRows={setEnvRows} keyLabel="Variable" keyHint="API_KEY" upper /></div>
              </>
            )}
          </div>
        )}

        {source === 'copy' && (
          <div className="space-y-2">
            <label className="block"><span className="mb-1 block text-[12px] font-medium">Server</span>
              <select className={input} value={name} onChange={(e) => { setName(e.target.value); setFrom('') }}>
                <option value="">Pick one</option>
                {[...existing.keys()].sort().map((n) => <option key={n} value={n}>{n} ({existing.get(n)!.map((a) => a.name).join(', ')})</option>)}
              </select></label>
            {holders.length > 1 && (
              <label className="block"><span className="mb-1 block text-[12px] font-medium">Copy the settings of</span>
                <select className={input} value={fromProfile} onChange={(e) => setFrom(e.target.value)}>
                  {holders.map((a) => <option key={a.profile} value={a.profile}>{a.name}</option>)}
                </select></label>
            )}
            <p className="text-2xs text-ink-faint">The same settings, and any key it uses, are copied on the VM; the key never comes to this page.</p>
          </div>
        )}

        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-[12px] font-medium">Give it to</span>
            <button type="button" className="text-2xs text-memory hover:underline"
              onClick={() => setTargets(targets.length === agents.length ? [] : agents.map((a) => a.profile))}>{targets.length === agents.length ? 'none' : 'everyone'}</button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((a) => {
              const already = Boolean(serverName) && has(a)
              const on = targets.includes(a.profile)
              return (
                <button key={a.profile} type="button" disabled={already} aria-pressed={on && !already}
                  onClick={() => setTargets(on ? targets.filter((t) => t !== a.profile) : [...targets, a.profile])}
                  title={already ? `${a.name} has ${serverName} already` : ''}
                  className={cn('press inline-flex items-center gap-1.5 rounded-full border py-0.5 pr-2.5 pl-0.5 text-[12px] disabled:opacity-40',
                    on && !already ? 'border-agent/60 bg-agent/15 text-ink' : 'border-line text-ink-dim hover:border-line-strong')}>
                  <AgentBadge id={a.id} />{a.name}{already ? ' ✓' : ''}
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </Drawer>
  )
}
