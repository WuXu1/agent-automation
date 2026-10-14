import { api } from './live/client'

// Agent Studio's terminal window (bridge/terminal.py): one agent's run, step by step, from its own session log on the VM (read only).

export type StepKind = 'in' | 'say' | 'cmd' | 'read' | 'write' | 'board' | 'tool' | 'out'

export interface Step {
  id: number
  at: number
  kind: StepKind
  text: string
  /** The output or message was longer than shown. */
  more?: boolean
  callId?: string | null
  tool?: string | null
  exit?: number | null
}

export interface RunInfo {
  id: string
  source?: string
  title?: string | null
  model?: string | null
  startedAt?: number
  endedAt?: number | null
  lastAt?: number | null
  steps?: number
  tools?: number
}

export interface TerminalView {
  profile: string
  sessions: RunInfo[]
  session: RunInfo | null
  steps: Step[]
  live: boolean
  card: { id: string; title: string; startedAt: number | null } | null
  cursor: number
}

export const terminalLive = {
  view: (agentId: string, session?: string | null, after = 0) =>
    api<TerminalView>(`/agents/${agentId}/terminal?${new URLSearchParams({ ...(session ? { session } : {}), after: String(after) })}`, { timeoutMs: 15_000 }),
}

// -- demo: an invented run that types itself out, so the window can be tried without the VM ------------------------------------------

type Script = Array<[StepKind, string, number?]>

const SCRIPTS: Record<string, { title: string; model: string; steps: Script }> = {
  tutor: { title: 'Plan revision for the statistics exam', model: 'deepseek-flash', steps: [
    ['in', 'work kanban task t_demo_study'],
    ['board', 'show t_demo_study'],
    ['out', '{"task": {"id": "t_demo_study", "title": "Plan revision for the statistics exam", "status": "running"}}'],
    ['tool', 'openalex_search {"query": "introductory statistics hypothesis testing", "open_access": true}'],
    ['out', '[{"title": "A gentle introduction to hypothesis tests", "year": 2021, "oa": true}, {"title": "Confidence intervals explained", "year": 2019, "oa": true}]'],
    ['cmd', 'python3 /data/workspace/study/free_slots.py --days 10'],
    ['out', 'Mon 09:00-11:00\nTue 09:00-10:30\nThu 14:00-16:00\nSat 10:00-12:00', 0],
    ['read', '/data/workspace/study/statistics-topics.md'],
    ['say', 'Four blocks over ten days: tests, intervals, regression, then a past paper. Two free readings attached.'],
    ['board', 'complete {"status":"ok","blocks":4}'],
  ] },
  default: { title: 'Morning briefing', model: 'deepseek-flash', steps: [
    ['in', 'Morning, what does today look like?'],
    ['tool', 'weather_forecast {"days": 1}'],
    ['out', '{"today": "light rain from 16:00", "high": 13}'],
    ['cmd', 'python3 /data/workspace/calendar_today.py --json'],
    ['out', '[{"time": "10:00", "title": "Statistics lecture"}, {"time": "18:30", "title": "Swimming"}]', 0],
    ['say', 'Morning. Lecture at 10, lab 2 is due tomorrow at noon, rain from 4pm, swimming at 6:30. Want me to block two hours for the lab this afternoon?'],
  ] },
}

function script(agentId: string) {
  return SCRIPTS[agentId] ?? { title: 'A card from its lead', model: 'deepseek-flash', steps: [
    ['in', `work kanban task t_demo_${agentId}`], ['board', `show t_demo_${agentId}`], ['out', '{"task": {"status": "running"}}'],
    ['cmd', 'ls -la /data/workspace'], ['out', 'total 12\ndrwxr-xr-x 2 hermes hermes 4096 notes\n-rw-r--r-- 1 hermes hermes  812 plan.md', 0],
    ['read', '/data/workspace/plan.md'], ['say', 'Plan read; nothing else needed from me right now.'], ['board', 'complete {"status":"ok"}'],
  ] as Script }
}

const LOOP_MS = 40_000
const STEP_MS = 3_200

/** Demo: the run restarts every 40 s and reveals one step about every 3 s, so the window types itself out like a live agent. */
export function demoTerminal(agentId: string, session?: string | null, now = Date.now()): TerminalView {
  const s = script(agentId)
  const start = Math.floor(now / LOOP_MS) * LOOP_MS
  const runId = `demo-${agentId}-${start}`
  const older: RunInfo = { id: `demo-${agentId}-earlier`, title: `${s.title} (earlier)`, model: s.model, startedAt: start - 3 * 3_600_000, endedAt: start - 3 * 3_600_000 + 60_000,
    lastAt: start - 3 * 3_600_000 + 60_000, steps: s.steps.length }
  const all: Step[] = s.steps.map(([kind, text, exit], i) => ({ id: i + 1, at: start + i * STEP_MS, kind, text, exit: exit ?? null, more: false }))
  if (session === older.id) {
    return { profile: agentId, sessions: [], session: older, steps: all.map((x, i) => ({ ...x, at: older.startedAt! + i * 4000 })), live: false, card: null, cursor: all.length }
  }
  const shown = all.filter((x) => x.at <= now)
  const live = shown.length < all.length
  const current: RunInfo = { id: runId, title: s.title, model: s.model, startedAt: start, endedAt: live ? null : start + all.length * STEP_MS, lastAt: shown.at(-1)?.at ?? start,
    steps: shown.length, tools: shown.filter((x) => x.kind !== 'in' && x.kind !== 'say' && x.kind !== 'out').length }
  return { profile: agentId, sessions: [current, older], session: current, steps: shown, live, cursor: shown.at(-1)?.id ?? 0,
    card: live ? { id: `t_demo_${agentId}`, title: s.title, startedAt: start } : null }
}
