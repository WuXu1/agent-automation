import { Settings2 } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { ago } from '@/lib/time'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { useMode } from '@/telemetry/mode'
import { demoTerminal, terminalLive, type Step, type TerminalView } from '@/telemetry/terminal'
import { AgentBadge } from '@/ui/AgentBadge'
import { Drawer } from '@/ui/Drawer'

const LIVE_POLL = 2000
const IDLE_POLL = 10_000
/** Characters per second for a step that arrives while the window is open (the "typing"). */
const TYPE_RATE = 900

const hhmmss = (ms: number) => new Date(ms).toLocaleTimeString('en-GB', { hour12: false })

/** Reveals a new line a few characters at a time, like a terminal printing it; old lines and reduced motion show at once. */
function Typed({ text, animate, onGrow }: { text: string; animate: boolean; onGrow: () => void }) {
  const [n, setN] = useState(animate ? 0 : text.length)
  useEffect(() => {
    if (!animate) return
    let raf = 0
    const start = performance.now()
    const tick = (t: number) => {
      const k = Math.min(text.length, Math.ceil(((t - start) / 1000) * TYPE_RATE))
      setN(k)
      onGrow()
      if (k < text.length) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [animate, text, onGrow])
  return <>{text.slice(0, n)}</>
}

const PREFIX: Record<Step['kind'], { mark: string; cls: string }> = {
  in: { mark: '‹', cls: 'text-[#c4b5fd]' },
  say: { mark: '›', cls: 'text-ink' },
  cmd: { mark: '$', cls: 'text-ink' },
  read: { mark: 'read', cls: 'text-[#67e8f9]' },
  write: { mark: 'write', cls: 'text-[#fcd34d]' },
  board: { mark: 'board', cls: 'text-[#f0abfc]' },
  tool: { mark: 'tool', cls: 'text-[#93c5fd]' },
  out: { mark: '', cls: 'text-ink-dim' },
}

function Line({ s, fresh, tint, onGrow }: { s: Step; fresh: boolean; tint: string; onGrow: () => void }) {
  const p = PREFIX[s.kind]
  const failed = s.kind === 'out' && typeof s.exit === 'number' && s.exit !== 0
  return (
    <div className={cn('group grid grid-cols-[minmax(0,1fr)] gap-x-3 sm:grid-cols-[64px_minmax(0,1fr)]', s.kind === 'cmd' || s.kind === 'in' ? 'mt-2.5' : 'mt-0.5')}>
      <span className="num hidden pt-px text-[10px] text-ink-faint/70 sm:block">{s.kind === 'out' ? '' : hhmmss(s.at)}</span>
      <div className={cn('min-w-0 break-words whitespace-pre-wrap', p.cls, s.kind === 'out' && 'border-l border-white/10 pl-3 text-[11.5px]')}>
        {p.mark && <span className={cn('mr-2 select-none', s.kind === 'cmd' ? 'font-semibold' : 'text-[10.5px] uppercase tracking-wide opacity-80')} style={s.kind === 'cmd' ? { color: tint } : undefined}>{p.mark}</span>}
        <Typed text={s.text || (s.kind === 'out' ? '(no output)' : '')} animate={fresh} onGrow={onGrow} />
        {s.more && <span className="text-ink-faint"> …</span>}
        {failed && <span className="ml-2 rounded bg-alarm/20 px-1 text-[10px] text-[#fca5a5]">exit {s.exit}</span>}
      </div>
    </div>
  )
}

/**
 * One agent's work on the VM as a terminal: the task it was given, every command with the start of its output, the files it opened, its board actions and
 * what it said. Live while it is working (new steps type themselves in); otherwise its last run, and earlier ones from the menu. Read only.
 */
export function AgentTerminal({ agent, onClose, onSettings }: {
  agent: { id: string; profile: string; name: string; tint: string } | null
  onClose: () => void
  onSettings: (profile: string) => void
}) {
  const mode = useMode((s) => s.mode)
  const reduced = useReducedMotion()
  const [view, setView] = useState<TerminalView | null>(null)
  const [session, setSession] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [fresh, setFresh] = useState<Set<number>>(new Set())
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const cursor = useRef(0)
  const id = agent?.id ?? null

  // poll: the whole run once, then only the steps after the last one seen (live); the demo returns its whole run each time
  const shown = useRef<TerminalView | null>(null)
  useEffect(() => {
    if (!id) return
    let stop = false
    let timer = 0
    cursor.current = 0
    stick.current = true
    shown.current = null
    const key = (x: Step) => `${x.id}:${x.kind}:${x.callId ?? ''}`
    const load = async (first: boolean) => {
      try {
        const v = mode === 'live' ? await terminalLive.view(id, session, first ? 0 : cursor.current) : demoTerminal(id, session)
        if (stop) return
        const prev = shown.current
        let next = v
        let added: Step[] = []
        if (!first && prev && prev.session?.id === v.session?.id) {
          const seen = new Set(prev.steps.map(key))
          added = v.steps.filter((x) => !seen.has(key(x)))
          next = mode === 'live' ? { ...v, steps: [...prev.steps, ...added] } : v
        }
        shown.current = next
        cursor.current = Math.max(first ? 0 : cursor.current, v.cursor)
        setError(null)
        setView(next)
        setFresh(reduced ? new Set() : new Set(added.map((x) => x.id)))
        timer = window.setTimeout(() => void load(false), v.live ? LIVE_POLL : IDLE_POLL)
      } catch (e) {
        if (stop) return
        setError(e instanceof Error ? e.message : 'Could not read the log')
        timer = window.setTimeout(() => void load(false), IDLE_POLL)
      }
    }
    void load(true)
    return () => { stop = true; window.clearTimeout(timer) }
  }, [id, session, mode, reduced])

  const follow = () => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }
  useLayoutEffect(follow, [view])

  if (!agent) return <Drawer open={false} onClose={onClose} title="">{null}</Drawer>
  const run = view?.session
  const others = view?.sessions ?? []
  const steps = view?.steps ?? []
  const live = Boolean(view?.live)

  return (
    <Drawer open onClose={onClose} wide
      title={<span className="inline-flex items-center gap-2"><AgentBadge id={agent.id} />{agent.name}<span className="num text-2xs font-normal text-ink-faint">{agent.profile}@vm</span></span>}>
      <div className="-mx-1 flex h-full min-h-[60vh] flex-col overflow-hidden rounded-xl border border-white/10 bg-[#04060a] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
        {/* the window bar: status, what it is on, which run */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-white/10 bg-white/[0.03] px-3 py-2">
          <span className="flex gap-1.5" aria-hidden><span className="size-2.5 rounded-full bg-[#ff5f57]/80" /><span className="size-2.5 rounded-full bg-[#febc2e]/80" /><span className="size-2.5 rounded-full bg-[#28c840]/80" /></span>
          {live ? (
            <span className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-[#86efac]"><span className="size-1.5 animate-breathe rounded-full bg-[#22c55e] shadow-[0_0_8px_#22c55e]" />LIVE</span>
          ) : <span className="text-[11px] text-ink-faint">{run?.lastAt ? `idle · last step ${ago(run.lastAt)}` : 'no runs yet'}</span>}
          <span className="min-w-0 flex-1 truncate text-[12px] text-ink-dim" title={view?.card?.title ?? run?.title ?? undefined}>{view?.card?.title ?? run?.title ?? ''}</span>
          {others.length > 1 && (
            <select aria-label="Which run" value={session ?? run?.id ?? ''} onChange={(e) => setSession(e.target.value === others[0]?.id ? null : e.target.value)}
              className="max-w-[200px] rounded-md border border-white/10 bg-black/40 px-1.5 py-0.5 text-[11px] text-ink-dim outline-none">
              {others.map((s, i) => <option key={s.id} value={s.id}>{i === 0 ? 'Latest' : s.lastAt ? ago(s.lastAt) : s.id}{s.title ? ` · ${s.title.slice(0, 40)}` : ''}</option>)}
            </select>)}
          <button type="button" onClick={() => onSettings(agent.profile)} className="press inline-flex items-center gap-1 rounded-md border border-white/10 px-1.5 py-0.5 text-[11px] text-ink-faint hover:text-ink">
            <Settings2 className="size-3" />Settings
          </button>
        </div>
        <div ref={scroller} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48 }}
          className="min-h-0 flex-1 overflow-y-auto px-3 pt-1 pb-4 font-mono text-[12px] leading-[1.55]" role="log" aria-live="polite" aria-label={`${agent.name}'s steps`}>
          {error && <p className="mt-2 text-[#fca5a5]">{error}</p>}
          {!view && !error && <p className="mt-3 text-ink-faint">connecting to {agent.profile}@vm…</p>}
          {view && steps.length === 0 && <p className="mt-3 text-ink-faint">Nothing has run yet. When {agent.name} gets a card or a message, its steps appear here as they happen.</p>}
          {steps.map((s, i) => <Line key={`${s.id}-${s.kind}-${s.callId ?? ''}-${i}`} s={s} fresh={fresh.has(s.id)} tint={agent.tint} onGrow={follow} />)}
          {live && <div className="mt-2 sm:pl-[76px]"><span className="inline-block h-[14px] w-[7px] animate-[blink_1s_steps(1)_infinite] bg-[#86efac]/90 align-middle" aria-hidden /></div>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 border-t border-white/10 px-3 py-1.5 text-[10.5px] text-ink-faint">
          <span>{run?.model ?? ''}</span>
          {run?.steps ? <span className="num">{run.steps} steps · {run.tools ?? 0} tool calls</span> : null}
          {run?.startedAt ? <span className="num">started {hhmmss(run.startedAt)}</span> : null}
          <span className="ml-auto">read only · keys and phone numbers are blanked</span>
        </div>
      </div>
    </Drawer>
  )
}
