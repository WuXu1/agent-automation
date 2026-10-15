import { useRegistry } from '@/telemetry/registry'
import type { Registry } from '@/telemetry/tools'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { agentName, coreAgents, roleFrom } from '@/telemetry/agents'
import { useTeam } from '@/telemetry/team'
import type { AgentMesh, AgentRun, AgentState, Handoff, Talk } from '@/telemetry/types'
import { AgentBadge } from '@/ui/AgentBadge'
import { Chip as StatusChip } from '@/ui/Chip'
import { HELPERS, KIND } from './shared'

/**
 * Agent Studio's team: the chief on top, then one lane per department from the registry (the kit ships one, the three
 * specialists), each with its lead and workers down a spine. Read-only: agents are added and moved through Claude. The
 * lines are live: a line runs while two agents work on an open card (bridge `talks`), turns amber while a worker waits on
 * an answer, and a spark travels the route for every new hand-off, comment or result on the board.
 */

/** Team tints: violet shifted in hue, so every line still reads as "agent" (DESIGN.md). */
const TINT: Record<string, string> = { specialists: '#c084fc' }
const PALETTE = ['#a78bfa', '#e879f9', '#93c5fd']
const AMBER = '#f59e0b'
const INDENT = 34
/** Hand-offs this recent still play when the page opens; after that only new ones do. */
const FRESH_MS = 3 * 60_000

type Planned = NonNullable<NonNullable<Registry['teams']>[number]['planned']>[number]
type Row = { kind: 'agent'; id: string; agent: AgentState; depth: number; parent: string; lead: number }
  | { kind: 'planned'; id: string; planned: Planned; depth: number; parent: string }
interface Lane { id: string; hub: string; label: string; note: string; tint: string; rows: Row[] }

interface Layout {
  lanes: Lane[]
  /** Each node's parent on the way up to the chief (a lane's members go through the lane's hub). */
  up: Map<string, string>
  tintOf: Map<string, string>
}

function layout(agents: AgentState[], teams: NonNullable<Registry['teams']>, roles: Record<string, string>, chief: string): Layout {
  const byId = new Map(agents.map((a) => [a.id, a]))
  const kids = new Map<string, AgentState[]>()
  for (const a of agents) {
    if (a.id === chief) continue
    const lead = a.reportsTo && byId.has(a.reportsTo) && a.reportsTo !== a.id ? a.reportsTo : chief
    kids.set(lead, [...(kids.get(lead) ?? []), a])
  }
  // the team first (hermes.json's order), then the registry's roles order
  const order = [...coreAgents().map((a) => a.id), ...Object.keys(roles)]
  const rank = (a: AgentState) => { const i = order.indexOf(a.id); return i < 0 ? 999 : i }
  for (const list of kids.values()) list.sort((x, y) => rank(x) - rank(y) || x.name.localeCompare(y.name))
  const below = (id: string): number => (kids.get(id) ?? []).reduce((n, k) => n + 1 + below(k.id), 0)

  const up = new Map<string, string>()
  const tintOf = new Map<string, string>()
  const top = kids.get(chief) ?? []
  const used = new Set<string>()
  const lanes: Lane[] = []
  const build = (id: string, label: string, note: string, tint: string, members: AgentState[], planned: Planned[]) => {
    const hub = `lane:${id}`
    up.set(hub, chief)
    const rows: Row[] = []
    const walk = (a: AgentState, depth: number, parent: string) => {
      used.add(a.id)
      up.set(a.id, parent)
      tintOf.set(a.id, tint)
      rows.push({ kind: 'agent', id: a.id, agent: a, depth, parent, lead: below(a.id) })
      for (const k of kids.get(a.id) ?? []) walk(k, depth + 1, a.id)
      for (const p of planned.filter((x) => x.reportsTo === a.id && !byId.has(x.id))) {
        up.set(p.id, a.id)
        rows.push({ kind: 'planned', id: p.id, planned: p, depth: depth + 1, parent: a.id })
      }
    }
    for (const m of members) walk(m, 0, hub)
    if (rows.length) { tintOf.set(hub, tint); lanes.push({ id, hub, label, note, tint, rows }) }
  }
  teams.forEach((t, i) => {
    const members = top.filter((a) => t.members.includes(a.id)).sort((x, y) => t.members.indexOf(x.id) - t.members.indexOf(y.id))
    build(t.id, t.label, t.note, TINT[t.id] ?? PALETTE[i % PALETTE.length]!, members, t.planned ?? [])
  })
  const loose = top.filter((a) => !used.has(a.id))
  if (loose.length) build('other', 'Other', 'agents not in a department yet', '#94a3b8', loose, [])
  return { lanes, up, tintOf }
}

// -- lines ---------------------------------------------------------------------------------------------------------------

/** One drawn link, from a node's parent (the chief, a lane hub or a lead) down to the node. */
interface Seg { d: string; tint: string; planned: boolean }

function useSegments(root: React.RefObject<HTMLDivElement | null>, els: Map<string, HTMLElement>, lay: Layout, key: string, chief: string) {
  const [segs, setSegs] = useState(new Map<string, Seg>())
  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const measure = () => {
      const r = el.getBoundingClientRect()
      const box = (id: string) => {
        const e = els.get(id)
        if (!e) return null
        const b = e.getBoundingClientRect()
        return { l: b.left - r.left, t: b.top - r.top, r: b.right - r.left, b: b.bottom - r.top, cx: b.left - r.left + b.width / 2, h: b.height }
      }
      const top = box(chief)
      const out = new Map<string, Seg>()
      if (!top) { setSegs(out); return }
      const firstLane = lay.lanes[0] ? box(lay.lanes[0].hub) : null
      for (const lane of lay.lanes) {
        const hub = box(lane.hub)
        if (!hub) continue
        const hx = hub.cx
        const hy = hub.t + hub.h / 2
        // stacked lanes (narrow screens): run down the left gutter instead of through the lanes above
        const stacked = firstLane && lane !== lay.lanes[0] && hub.t > firstLane.b + 40 && Math.abs(hub.cx - firstLane.cx) < 4
        let d: string
        if (stacked) {
          const gx = Math.max(2, hub.l - 14)
          d = `M ${top.cx} ${top.b} C ${top.cx} ${top.b + 30} ${gx} ${top.b + 10} ${gx} ${top.b + 44} V ${hy - 10} Q ${gx} ${hy} ${gx + 10} ${hy} H ${hub.l}`
        } else {
          const mid = (top.b + hub.t) / 2
          d = Math.abs(hx - top.cx) < 2 ? `M ${top.cx} ${top.b} V ${hub.t}` : `M ${top.cx} ${top.b} C ${top.cx} ${mid} ${hx} ${mid} ${hx} ${hub.t}`
        }
        out.set(lane.hub, { d, tint: lane.tint, planned: false })
        for (const row of lane.rows) {
          const p = row.parent === lane.hub ? hub : box(row.parent)
          const c = box(row.id)
          if (!p || !c) continue
          // the spine leaves the parent under its badge (or the hub's centre) and turns into the card at badge height
          const sx = row.parent === lane.hub ? hx : p.l + 15
          const sy = p.b
          const cy = c.t + Math.min(c.h / 2, 27)
          const rad = Math.min(10, Math.max(0, cy - sy))
          out.set(row.id, { d: `M ${sx} ${sy} V ${cy - rad} Q ${sx} ${cy} ${sx + rad} ${cy} H ${c.l}`, tint: lane.tint, planned: row.kind === 'planned' })
        }
      }
      setSegs(out)
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    void document.fonts?.ready.then(measure)
    return () => ro.disconnect()
  }, [root, els, lay, key, chief])
  return segs
}

/** The way between two agents: up from one to the lead they share, then down to the other ('owner' is drawn as the chief). */
function route(up: Map<string, string>, from: string, to: string, chief: string): Array<{ id: string; dir: 'up' | 'down' }> {
  const chain = (id: string) => { const out = [id]; let p = up.get(id); while (p) { out.push(p); p = up.get(p) } return out }
  const a = chain(from === 'owner' ? chief : from)
  const b = chain(to === 'owner' ? chief : to)
  const common = a.find((x) => b.includes(x))
  if (!common || a[0] === b[0]) return []
  return [...a.slice(0, a.indexOf(common)).map((id) => ({ id, dir: 'up' as const })),
    ...b.slice(0, b.indexOf(common)).reverse().map((id) => ({ id, dir: 'down' as const }))]
}

/** A spark that travels a route once (a new hand-off, comment or result), lighting each line as it passes. */
function Spark({ parts, color, delay, onDone }: { parts: Array<{ d: string; dir: 'up' | 'down' }>; color: string; delay: number; onDone: () => void }) {
  const paths = useRef<Array<SVGPathElement | null>>([])
  const dot = useRef<SVGCircleElement>(null)
  const done = useRef(onDone)
  const partsRef = useRef(parts)
  useEffect(() => { done.current = onDone; partsRef.current = parts })
  const route = parts.map((p) => `${p.dir}${p.d}`).join('|')
  useEffect(() => {
    const c = dot.current
    if (!c) return
    const lens = paths.current.map((p) => p?.getTotalLength() ?? 0)
    const total = lens.reduce((a, b) => a + b, 0)
    if (!total) { done.current(); return }
    const ms = Math.min(2600, 900 + total * 1.6)
    const start = performance.now() + delay
    let raf = 0
    const step = (t: number) => {
      const k = (t - start) / ms
      if (k < 0) { raf = requestAnimationFrame(step); return }
      if (k >= 1) { c.setAttribute('opacity', '0'); paths.current.forEach((p) => p?.setAttribute('stroke-opacity', '0')); done.current(); return }
      let at = (1 - (1 - k) ** 2) * total
      let i = 0
      while (i < lens.length - 1 && at > lens[i]!) { at -= lens[i]!; i++ }
      const p = paths.current[i]
      if (p) {
        const pt = p.getPointAtLength(partsRef.current[i]!.dir === 'up' ? lens[i]! - at : at)
        c.setAttribute('cx', String(pt.x))
        c.setAttribute('cy', String(pt.y))
      }
      const fade = k < 0.08 ? k / 0.08 : k > 0.8 ? (1 - k) / 0.2 : 1
      c.setAttribute('opacity', String(fade))
      paths.current.forEach((q, j) => q?.setAttribute('stroke-opacity', String(j <= i ? fade * 0.85 : 0)))
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // restarts only when the route itself changes, not on every re-render of the chart
  }, [route, delay])
  return (
    <g>
      {parts.map((p, i) => (
        <path key={i} ref={(el) => { paths.current[i] = el }} d={p.d} fill="none" stroke={color} strokeOpacity={0} strokeWidth={2.25}
          style={{ filter: `drop-shadow(0 0 5px ${color})` }} />
      ))}
      <circle ref={dot} r={4.5} fill={color} opacity={0} style={{ filter: `drop-shadow(0 0 7px ${color})` }} />
    </g>
  )
}

const handoffKey = (h: Handoff) => `${h.cardId}-${h.kind}-${h.at}-${h.from}`

/** New hand-offs since the page opened (and any from the last few minutes on opening), each played once. */
function useSparks(handoffs: Handoff[], reduced: boolean) {
  const seen = useRef<Set<string> | null>(null)
  const [sparks, setSparks] = useState<Array<{ key: string; h: Handoff; delay: number }>>([])
  useEffect(() => {
    const first = seen.current === null
    const known = seen.current ?? new Set<string>()
    seen.current = known
    const now = Date.now()
    const fresh = handoffs.filter((h) => h.from !== 'helper' && !known.has(handoffKey(h)) && (!first || now - h.at < FRESH_MS))
    for (const h of handoffs) known.add(handoffKey(h))
    if (reduced || !fresh.length) return
    // oldest first, one after another
    const add = fresh.slice(0, 6).reverse().map((h, i) => ({ key: `${handoffKey(h)}-${now}`, h, delay: i * 650 }))
    setSparks((s) => [...s, ...add])
  }, [handoffs, reduced])
  const drop = (key: string) => setSparks((s) => s.filter((x) => x.key !== key))
  return { sparks, drop }
}

// -- cards ---------------------------------------------------------------------------------------------------------------

const PILL: Record<AgentRun['status'], string> = { ok: 'bg-ok/80', waiting: 'bg-runway', error: 'bg-alarm', running: 'animate-breathe bg-agent' }
const PILL_WORD: Record<AgentRun['status'], string> = { ok: 'done', waiting: 'waiting on you', error: 'failed', running: 'running' }
const TRIGGER: Record<AgentRun['trigger'], string> = { board: 'a card on the board', cron: 'a scheduled job' }

function length(secs: number | null): string {
  if (secs === null) return ''
  return secs < 60 ? `${secs} s` : secs < 3600 ? `${Math.round(secs / 60)} min` : `${(secs / 3600).toFixed(1)} h`
}

/** The agent's recent AI runs as pills (green done, amber waiting on you, red failed), oldest left; hover one for what it was. */
function RunStrip({ agent }: { agent: AgentState }) {
  const [hover, setHover] = useState<number | null>(null)
  const runs = agent.runs ?? []
  const rel = agent.reliability
  const h = hover !== null ? runs[hover] : undefined
  return (
    <div className="relative mt-2.5 flex items-center gap-2" onMouseLeave={() => setHover(null)}>
      <span className="flex h-2.5 min-w-0 flex-1 items-end gap-[2px]" aria-label={`${runs.length} recent runs`}>
        {runs.length === 0 ? <span className="text-[10px] text-ink-faint">no runs yet</span> : runs.map((r, i) => (
          <span key={i} onMouseEnter={() => setHover(i)}
            className={cn('h-full max-w-[5px] min-w-[2px] flex-1 rounded-[2px] transition-transform duration-100', PILL[r.status], hover === i && 'scale-y-125')} />
        ))}
      </span>
      {rel && rel.pct !== null && (
        <span className={cn('num shrink-0 text-[10px]', rel.pct >= 95 ? 'text-[#6ee7b7]' : rel.pct >= 80 ? 'text-[#fcd34d]' : 'text-[#fca5a5]')}
          title={`${rel.ok} done, ${rel.errors} failed in the last 30 days (${rel.total} runs, scripts that skip the AI not counted)`}>{rel.pct}%</span>
      )}
      {h && (
        <span className="pointer-events-none absolute bottom-full left-0 z-20 mb-2 w-max max-w-[240px] rounded-lg border border-line-strong bg-deck px-2.5 py-1.5 text-left text-[11px] leading-snug shadow-xl">
          <span className="block font-medium text-ink">{h.title}</span>
          <span className="block text-ink-dim">{PILL_WORD[h.status]} · {TRIGGER[h.trigger]}{h.secs !== null ? ` · ${length(h.secs)}` : ''}</span>
          <span className="num block text-ink-faint">{ago(h.at)}</span>
        </span>
      )}
    </div>
  )
}

interface Ctx {
  els: Map<string, HTMLElement>
  talks: Talk[]
  gateway: AgentMesh['gateway']
  pendingFor: (profile: string) => boolean
  onOpen: (profile: string, tint?: string) => void
  roles: Record<string, string>
  chief: string
}

const register = (ctx: Ctx, id: string) => (el: HTMLElement | null) => { if (el) ctx.els.set(id, el); else ctx.els.delete(id) }

/** What an agent is doing with whom right now, in one line (from the open cards). */
function nowLine(ctx: Ctx, id: string): { text: string; amber: boolean } | null {
  const doing = ctx.talks.find((t) => t.to === id && t.state === 'working')
  if (doing) return { text: doing.title, amber: false }
  const asking = ctx.talks.find((t) => t.from === id && t.state === 'asking')
  if (asking) return { text: `asks ${asking.to === 'owner' ? 'you' : agentName(asking.to)}: ${asking.title}`, amber: true }
  const waiting = ctx.talks.filter((t) => t.from === id && t.state === 'working')
  if (waiting.length) return { text: `with ${waiting.map((t) => (t.to === 'owner' ? 'you' : agentName(t.to))).join(', ')}`, amber: false }
  return null
}

function AgentCard({ agent, ctx, tint, lead = 0 }: { agent: AgentState; ctx: Ctx; tint: string; lead?: number }) {
  const isChief = agent.id === ctx.chief
  const role = ctx.roles[agent.id] ?? roleFrom(agent.description)
  const pending = ctx.pendingFor(agent.profile)
  const now = nowLine(ctx, agent.id)
  const busy = agent.running > 0 || Boolean(now && !now.amber)
  const state = agent.blocked > 0 || now?.amber ? { word: agent.blocked > 1 ? `${agent.blocked} waiting` : 'waiting', color: AMBER }
    : busy ? { word: 'working', color: tint } : null
  return (
    <button
      ref={register(ctx, agent.id)}
      type="button"
      onClick={() => ctx.onOpen(agent.profile, tint)}
      title={`${agent.description}\n\nClick for ${agent.name}'s settings and live logs`}
      className={cn('press group/card relative block w-full rounded-xl border bg-glass-strong p-3 text-left transition-[border-color,box-shadow] duration-300',
        isChief ? 'max-w-[360px]' : '', pending ? 'border-runway/60' : 'border-line-strong hover:border-white/25')}
      style={{
        borderColor: isChief ? 'rgb(217 70 239 / 0.45)' : busy && !pending ? `${tint}99` : undefined,
        boxShadow: busy ? `0 0 0 1px ${tint}33, 0 0 22px -6px ${tint}` : undefined,
      }}
    >
      <div className="flex items-center gap-2.5">
        <AgentBadge id={agent.id} size="md" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold">{agent.name}</span>
            {lead > 0 && <span className="shrink-0 rounded px-1 py-px text-[9px] font-semibold tracking-wide uppercase" style={{ color: tint, background: `${tint}1f` }}>lead</span>}
          </div>
          <div className="truncate text-2xs text-ink-faint">{role}{isChief ? ' · talks to the leads' : lead > 0 ? ` · ${lead} under` : ''}</div>
        </div>
        {isChief ? <StatusChip signal={ctx.gateway.ok ? 'ok' : 'alarm'} breathe={ctx.gateway.ok}>{ctx.gateway.ok ? 'gateway up' : 'gateway down'}</StatusChip>
          : state ? (
            <span className="flex shrink-0 items-center gap-1.5 text-[10px] font-medium" style={{ color: state.color }}>
              <span className="size-1.5 animate-breathe rounded-full" style={{ background: state.color, boxShadow: `0 0 8px ${state.color}` }} />{state.word}
            </span>
          ) : <span className="shrink-0 text-[10px] text-ink-faint">{pending ? <span className="text-[#fcd34d]">restart</span> : agent.lastActive ? ago(agent.lastActive) : 'quiet'}</span>}
      </div>
      {now && <div className="mt-2 truncate text-[11px]" style={{ color: now.amber ? '#fcd34d' : tint }}>↳ {now.text}</div>}
      <div className="mt-2 flex items-center gap-2.5">
        {!isChief && (
          <span className="flex gap-1" title={`${agent.running} of ${HELPERS} helper slots busy`} aria-label={`${agent.running} of ${HELPERS} helpers busy`}>
            {Array.from({ length: HELPERS }, (_, i) => (
              <span key={i} className={cn('size-1.5 rounded-full', i < agent.running ? 'animate-breathe' : 'border border-line-strong')}
                style={i < agent.running ? { background: tint } : undefined} />
            ))}
          </span>
        )}
        <span className="num truncate text-[11px] text-ink-dim">{isChief ? `${agent.queued} new · ${agent.done7d} done this week` : `${agent.queued} queued · ${agent.done7d} done this week`}</span>
      </div>
      <RunStrip agent={agent} />
      <span className="pointer-events-none absolute right-2.5 bottom-1 font-mono text-[9px] text-ink-faint opacity-0 transition-opacity duration-150 group-hover/card:opacity-100" aria-hidden>settings</span>
    </button>
  )
}

function PlannedCard({ p, ctx }: { p: Planned; ctx: Ctx }) {
  return (
    <div ref={register(ctx, p.id)} className="rounded-xl border border-dashed border-line-strong px-3 py-2.5 opacity-60" title="Written, not installed yet">
      <div className="flex items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-full border border-dashed border-line-strong text-[12px] text-ink-faint">{p.name.slice(0, 2)}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-ink-dim">{p.name}</div>
          <div className="truncate text-2xs text-ink-faint">{p.role} · not installed, needs {p.waits}</div>
        </div>
      </div>
    </div>
  )
}

function LaneView({ lane, ctx, agents }: { lane: Lane; ctx: Ctx; agents: AgentState[] }) {
  const ids = new Set(lane.rows.map((r) => r.id))
  const active = ctx.talks.filter((t) => ids.has(t.to as string) || ids.has(t.from as string))
  const working = new Set(active.filter((t) => t.state === 'working').map((t) => t.to)).size
  const asking = active.filter((t) => t.state === 'asking').length
  const installed = lane.rows.filter((r) => r.kind === 'agent').length
  const done = agents.filter((a) => ids.has(a.id)).reduce((n, a) => n + a.done7d, 0)
  return (
    <section aria-label={lane.label} className="relative min-w-0 rounded-2xl border p-3 pt-0 md:p-4 md:pt-0"
      style={{ borderColor: `${lane.tint}2e`, background: `linear-gradient(180deg, ${lane.tint}12, transparent 140px)` }}>
      <header className="flex items-center gap-2.5 py-3">
        <span ref={register(ctx, lane.hub)} className="grid size-4 shrink-0 place-items-center rounded-full border-2"
          style={{ borderColor: lane.tint, boxShadow: active.length ? `0 0 12px ${lane.tint}` : undefined }}>
          <span className={cn('size-1.5 rounded-full', active.length > 0 && 'animate-breathe')} style={{ background: active.length ? lane.tint : 'transparent' }} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-[13px] font-semibold" style={{ color: lane.tint }}>{lane.label}</h3>
            <span className="num shrink-0 text-[10px] text-ink-faint">
              {installed} agent{installed === 1 ? '' : 's'} · {working || asking
                ? <span style={{ color: asking ? '#fcd34d' : lane.tint }}>{[working && `${working} working`, asking && `${asking} waiting`].filter(Boolean).join(' · ')}</span>
                : `${done} done this week`}
            </span>
          </div>
          <p className="line-clamp-1 text-2xs text-ink-faint" title={lane.note}>{lane.note}</p>
        </div>
      </header>
      <ol className="flex flex-col gap-2.5">
        {lane.rows.map((r) => (
          <li key={r.id} style={{ paddingLeft: 30 + r.depth * INDENT }}>
            {r.kind === 'agent' ? <AgentCard agent={r.agent} ctx={ctx} tint={lane.tint} lead={r.lead} /> : <PlannedCard p={r.planned} ctx={ctx} />}
          </li>
        ))}
      </ol>
    </section>
  )
}

/** Who is working with whom this minute, in words (the same open cards that light the lines). */
function RightNow({ talks }: { talks: Talk[] }) {
  useNow(30_000)
  const who = (x: Talk['from']) => (x === 'owner' ? 'You' : agentName(x))
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px]" aria-live="polite">
      <span className="text-2xs font-medium tracking-wide text-ink-faint uppercase">Right now</span>
      {talks.length === 0 ? <span className="text-ink-faint">Nobody is mid-task. Lines light up when agents hand work to each other.</span>
        : talks.slice(0, 4).map((t) => (
          <span key={`${t.cardId}-${t.state}`} className="flex min-w-0 items-center gap-1.5">
            <span className="size-1.5 shrink-0 animate-breathe rounded-full" style={{ background: t.state === 'asking' ? AMBER : '#c084fc' }} />
            <b className="font-semibold text-ink">{who(t.from)}</b>
            <span className="text-ink-faint">{t.state === 'asking' ? 'asks' : '→'}</span>
            <b className="font-semibold text-ink">{who(t.to)}</b>
            <span className="max-w-[260px] truncate text-ink-dim">{t.title}</span>
            <span className="num text-[10px] text-ink-faint">{ago(t.since)}</span>
          </span>
        ))}
    </div>
  )
}

export function TeamTree({ mesh, pendingFor, onOpen }: {
  mesh: AgentMesh
  pendingFor: (profile: string) => boolean
  onOpen: (profile: string, tint?: string) => void
}) {
  const reduced = useReducedMotion()
  const root = useRef<HTMLDivElement>(null)
  const [els] = useState(() => new Map<string, HTMLElement>())
  const roles = useRegistry((r) => r.reg.roles)
  const teams = useRegistry((r) => r.reg.teams)
  const chief = useTeam((s) => s.team.chief)
  const lay = useMemo(() => layout(mesh.agents, teams ?? [], roles, chief), [mesh.agents, teams, roles, chief])
  const talks = useMemo(() => mesh.talks ?? [], [mesh.talks])
  const segs = useSegments(root, els, lay, `${lay.lanes.map((l) => l.rows.map((r) => r.id).join(',')).join('|')}:${talks.map((t) => `${t.cardId}${t.state}`).join(',')}`, chief)
  const { sparks, drop } = useSparks(mesh.handoffs, reduced)
  const top = mesh.agents.find((a) => a.id === chief)
  if (!top) return null
  const ctx: Ctx = { els, talks, gateway: mesh.gateway, pendingFor, onOpen, roles, chief }

  // live lines: every segment on the route of an open card, dashes running towards whoever is doing the work
  const live = new Map<string, { dir: 'up' | 'down'; color: string }>()
  for (const t of talks) {
    for (const p of route(lay.up, t.from, t.to, chief)) {
      if (t.state === 'asking' || !live.has(p.id)) live.set(p.id, { dir: p.dir, color: t.state === 'asking' ? AMBER : lay.tintOf.get(p.id) ?? '#c084fc' })
    }
  }

  return (
    <div>
      <RightNow talks={talks} />
      <div ref={root} className="relative">
        <svg className="pointer-events-none absolute inset-0 size-full overflow-visible" aria-hidden>
          {[...segs].map(([id, s]) => (
            <path key={id} d={s.d} fill="none" stroke={s.tint} strokeOpacity={s.planned ? 0.22 : 0.32} strokeWidth={1.5}
              strokeDasharray={s.planned ? '3 5' : undefined} />
          ))}
          {[...live].map(([id, l]) => {
            const s = segs.get(id)
            return s ? (
              <g key={`live-${id}`}>
                <path d={s.d} fill="none" stroke={l.color} strokeOpacity={0.22} strokeWidth={6} style={{ filter: 'blur(3px)' }} />
                <path d={s.d} fill="none" stroke={l.color} strokeWidth={2} strokeDasharray="7 5" strokeLinecap="round"
                  className={l.dir === 'down' ? 'talk-flow' : 'talk-flow-up'} style={{ filter: `drop-shadow(0 0 4px ${l.color})` }} />
              </g>
            ) : null
          })}
          {sparks.map(({ key, h, delay }) => {
            const parts = route(lay.up, h.from, h.to, chief).flatMap((p) => { const s = segs.get(p.id); return s ? [{ d: s.d, dir: p.dir }] : [] })
            return parts.length ? <Spark key={key} parts={parts} color={KIND[h.kind].stroke} delay={delay} onDone={() => drop(key)} /> : null
          })}
        </svg>
        <div className="relative flex justify-center">
          <div className="w-full max-w-[360px]"><AgentCard agent={top} ctx={ctx} tint="#d946ef" /></div>
        </div>
        <div className="relative mt-12 grid gap-4 lg:grid-cols-[repeat(var(--lanes),minmax(0,1fr))]" style={{ '--lanes': lay.lanes.length } as React.CSSProperties}>
          {lay.lanes.map((l) => <LaneView key={l.id} lane={l} ctx={ctx} agents={mesh.agents} />)}
        </div>
      </div>
    </div>
  )
}
