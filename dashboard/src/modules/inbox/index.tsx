import { ArrowLeft, Mail, Paperclip, RefreshCw, Search, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { ago, stamp } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useMode } from '@/telemetry/mode'
import { inboxApi, type Channel, type InboxState, type InboxSummary, type Message, type MessageBody } from '@/telemetry/tools'
import { Button } from '@/ui/Button'
import { Chip } from '@/ui/Chip'

// One channel so far (the Gmail add-on); a new one is a line here and a reader in bridge/inbox.py.
const CHANNELS: Record<Channel, { label: string; icon: typeof Mail }> = { gmail: { label: 'Gmail', icon: Mail } }
type When = 'today' | 'yesterday' | 'all'

function dayOf(ms: number | null): When | 'older' {
  if (!ms) return 'older'
  const d = new Date(ms)
  const today = new Date()
  const y = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'today'
  if (d.toDateString() === y.toDateString()) return 'yesterday'
  return 'older'
}

function short(ms: number | null): string {
  if (!ms) return ''
  const d = new Date(ms)
  return dayOf(ms) === 'today' ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

function Summary({ summary, busy, onRefresh, onOpen }: { summary: InboxSummary | null; busy: boolean; onRefresh: () => void; onOpen: (id: string) => void }) {
  useNow(60_000)
  return (
    <section className="glass mb-3 border border-agent/25 p-4" aria-label="AI summary">
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-agent/30 bg-agent/10 text-[#f0abfc]"><Sparkles className="size-4" /></span>
        <div className="min-w-0 flex-1">
          {summary ? (
            <>
              <p className="text-[14px] font-medium text-ink">{summary.headline}</p>
              {summary.points.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {summary.points.map((p, i) => (
                    <li key={i} className="flex items-start gap-2 text-[13px] text-ink-dim">
                      <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-agent" />
                      {p.id ? <button type="button" onClick={() => onOpen(p.id!)} className="press text-left hover:text-ink hover:underline">{p.text}</button> : <span>{p.text}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : <p className="text-[13px] text-ink-faint">{busy ? 'Reading your inbox…' : 'No summary yet.'}</p>}
        </div>
        <Button size="sm" tone="ghost" icon={<RefreshCw className={cn('size-3.5', busy && 'animate-spin')} />} disabled={busy} onClick={onRefresh}
          title="Sum up the inbox again (the dashboard's model, a fraction of a penny)">
          {busy ? 'Summing up…' : summary ? `summed up ${ago(summary.at)}` : 'Sum up'}
        </Button>
      </div>
    </section>
  )
}

function Row({ m, active, onOpen }: { m: Message; active: boolean; onOpen: () => void }) {
  const Icon = CHANNELS[m.channel].icon
  return (
    <li>
      <button type="button" onClick={onOpen} aria-current={active ? 'true' : undefined}
        className={cn('press flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors', active ? 'bg-white/[0.07]' : 'hover:bg-white/[0.03]')}>
        <span className="mt-1.5 flex w-2 shrink-0 justify-center">{m.unread && <span className="size-2 rounded-full bg-memory" aria-label="unread" />}</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className={cn('min-w-0 flex-1 truncate text-[13px]', m.unread ? 'font-semibold text-ink' : 'text-ink-dim')}>{m.draft ? `To ${m.to.replace(/<.*>/, '').trim() || 'someone'}` : m.from.name}</span>
            <span className="num shrink-0 text-[11px] text-ink-faint">{short(m.at)}</span>
          </span>
          <span className="flex items-center gap-1.5">
            {m.draft && <span className="rounded border border-runway/40 px-1 text-[10px] text-[#fcd34d]">draft</span>}
            <span className={cn('truncate text-[12px]', m.unread ? 'text-ink' : 'text-ink-dim')}>{m.subject}</span>
          </span>
          <span className="line-clamp-1 text-[11px] text-ink-faint">{m.snippet}</span>
        </span>
        <Icon className="mt-1 size-3.5 shrink-0 text-ink-faint" aria-label={CHANNELS[m.channel].label} />
      </button>
    </li>
  )
}

function Preview({ m, onBack }: { m: Message; onBack: () => void }) {
  const [body, setBody] = useState<MessageBody | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let stop = false
    inboxApi.read(m).then((b) => { if (!stop) setBody(b) }).catch((e: unknown) => { if (!stop) setError(e instanceof Error ? e.message : 'Could not open it') })
    return () => { stop = true }
  }, [m])
  return (
    <article className="flex min-h-0 flex-1 flex-col">
      <header className="border-b border-line px-5 py-4">
        <button type="button" onClick={onBack} className="press mb-2 inline-flex items-center gap-1 text-2xs text-ink-faint hover:text-ink md:hidden"><ArrowLeft className="size-3.5" />All messages</button>
        <h2 className="text-[16px] font-semibold text-ink">{m.subject}</h2>
        <p className="mt-1 text-[12px] text-ink-dim">{m.draft ? 'Your draft' : <><span className="text-ink">{m.from.name}</span> <span className="num text-ink-faint">{m.from.address}</span></>}</p>
        <p className="num text-2xs text-ink-faint">{body?.to ? `to ${body.to}` : ''}{body?.cc ? ` · cc ${body.cc}` : ''}{m.at ? ` · ${stamp(m.at)}` : ''}</p>
        {body && body.attachments.length > 0 && (
          <p className="mt-2 flex flex-wrap items-center gap-1.5 text-2xs text-ink-dim"><Paperclip className="size-3" />{body.attachments.map((a) => <span key={a} className="rounded border border-line px-1.5">{a}</span>)}</p>
        )}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {error ? <p role="alert" className="text-[12px] text-[#fca5a5]">{error}</p>
          : !body ? <div className="space-y-2">{[90, 75, 82, 40].map((w) => <div key={w} className="h-3 animate-pulse rounded bg-white/[0.04]" style={{ width: `${w}%` }} />)}</div>
            : <>
              {/* plain text only: mail is untrusted, so it is never rendered as HTML */}
              <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-ink-dim">{body.body}</p>
              {body.truncated && <p className="mt-3 text-2xs text-ink-faint">Long message: the rest is in Gmail.</p>}
            </>}
      </div>
    </article>
  )
}

/** Inbox: your mail, read only, when the Gmail add-on is switched on (hermes.json `features.gmail`). */
export default function InboxView() {
  const mode = useMode((s) => s.mode)
  const [state, setState] = useState<InboxState | null>(null)
  const [loading, setLoading] = useState(true)
  const [summing, setSumming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [channel, setChannel] = useState<Channel | 'all'>('all')
  const [when, setWhen] = useState<When>('all')
  const [unread, setUnread] = useState(false)
  const [drafts, setDrafts] = useState(false)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState<Message | null>(null)
  useNow(60_000)

  const summarise = async () => {
    setSumming(true)
    try { const s = await inboxApi.summarise(); setState((st) => (st ? { ...st, summary: s } : st)); play('tick') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not sum it up') } finally { setSumming(false) }
  }
  const load = async (refresh: boolean) => {
    setLoading(true); setError(null)
    try {
      const s = await inboxApi.get(refresh)
      setState(s)
      // a fresh summary whenever the list is newer than the last one (live; a fraction of a penny)
      if (mode === 'live' && s.list && (!s.summary || (s.summary.listAt ?? 0) < s.list.at)) void summarise()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not read the inbox') } finally { setLoading(false) }
  }
  useEffect(() => {
    let stop = false
    inboxApi.get(false).then((s) => {
      if (stop) return
      setState(s); setLoading(false)
      if (mode === 'live' && s.list && (!s.summary || (s.summary.listAt ?? 0) < s.list.at)) {
        setSumming(true)
        inboxApi.summarise().then((sum) => { if (!stop) setState((st) => (st ? { ...st, summary: sum } : st)) }).catch(() => {}).finally(() => { if (!stop) setSumming(false) })
      }
    }).catch((e: unknown) => { if (!stop) { setError(e instanceof Error ? e.message : 'Could not read the inbox'); setLoading(false) } })
    return () => { stop = true }
  }, [mode])

  const all = useMemo(() => state?.list?.messages ?? [], [state])
  const channels = [...new Set(all.map((m) => m.channel))]
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase()
    return all.filter((m) => (channel === 'all' || m.channel === channel) && (drafts ? m.draft : !m.draft) && (!unread || m.unread)
      && (when === 'all' || dayOf(m.at) === when)
      && (!t || `${m.from.name} ${m.from.address} ${m.subject} ${m.snippet}`.toLowerCase().includes(t)))
  }, [all, channel, when, unread, drafts, q])
  const unreadCount = all.filter((m) => m.unread).length
  const chip = (on: boolean) => cn('press rounded-full border px-2.5 py-1 text-[12px]', on ? 'border-memory/50 bg-memory/10 text-ink' : 'border-line text-ink-faint hover:text-ink-dim')

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="mx-auto flex min-h-0 w-full max-w-[1400px] flex-1 flex-col p-3 md:p-6">
        <Summary summary={state?.summary ?? null} busy={summing || (loading && !state)} onRefresh={() => void summarise()}
          onOpen={(id) => { const m = all.find((x) => x.id === id); if (m) setOpen(m) }} />
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button type="button" className={chip(channel === 'all')} onClick={() => setChannel('all')}>All</button>
          {(Object.keys(CHANNELS) as Channel[]).filter((c) => channels.includes(c) || mode === 'demo').map((c) => (
            <button key={c} type="button" className={chip(channel === c)} onClick={() => setChannel(c)}>{CHANNELS[c].label}</button>
          ))}
          <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
          {(['today', 'yesterday', 'all'] as When[]).map((w) => (
            <button key={w} type="button" className={chip(when === w)} onClick={() => setWhen(w)}>{w === 'all' ? 'Any day' : w[0]!.toUpperCase() + w.slice(1)}</button>
          ))}
          <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
          <button type="button" className={chip(unread)} onClick={() => setUnread(!unread)} aria-pressed={unread}>Unread{unreadCount ? ` · ${unreadCount}` : ''}</button>
          <button type="button" className={chip(drafts)} onClick={() => setDrafts(!drafts)} aria-pressed={drafts}>Drafts</button>
          <label className="relative ml-auto">
            <span className="sr-only">Search messages</span>
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-faint" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search"
              className="w-44 rounded-lg border border-line bg-white/[0.02] py-1.5 pr-3 pl-8 text-[12px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong" />
          </label>
          <Button size="sm" tone="ghost" icon={<RefreshCw className={cn('size-3.5', loading && 'animate-spin')} />} disabled={loading} onClick={() => void load(true)}>
            {state?.list ? `read ${ago(state.list.at)}` : 'Read'}
          </Button>
        </div>
        {error && <p role="alert" className="mb-2 text-[12px] text-[#fca5a5]">{error}</p>}
        <div className="glass flex min-h-[420px] flex-1 overflow-hidden">
          <div className={cn('flex min-h-0 w-full flex-col border-line md:w-[400px] md:shrink-0 md:border-r', open && 'max-md:hidden')}>
            {!state?.list && loading ? <div className="m-3 h-40 animate-pulse rounded-lg bg-white/[0.03]" />
              : shown.length === 0 ? <p className="p-4 text-[12px] text-ink-faint">Nothing here.</p>
                : <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">{shown.map((m) => <Row key={m.id} m={m} active={open?.id === m.id} onOpen={() => { play('tick'); setOpen(m) }} />)}</ul>}
          </div>
          <div className={cn('min-h-0 flex-1 flex-col', open ? 'flex' : 'hidden md:flex')}>
            {open ? <Preview key={open.id} m={open} onBack={() => setOpen(null)} /> : (
              <div className="grid flex-1 place-items-center p-6 text-center">
                <div>
                  <Mail className="mx-auto size-6 text-ink-faint" />
                  <p className="mt-2 text-[13px] text-ink-dim">Pick a message to read it here.</p>
                  <p className="mt-1 text-2xs text-ink-faint">Read only: nothing is sent, deleted or marked as read.</p>
                </div>
              </div>
            )}
          </div>
        </div>
        <p className="mt-2 flex items-center gap-2 text-2xs text-ink-faint">
          <Chip signal={mode === 'live' ? 'ok' : 'warn'}>{mode === 'live' ? 'Gmail live' : 'Demo messages'}</Chip>
          Read on the VM with the agents’ app password, read-only (mail stays unread); shown as plain text. More platforms can be added later.
        </p>
      </div>
    </div>
  )
}
