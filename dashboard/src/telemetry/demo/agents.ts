import { hash, rng } from '@/lib/rng'
import { DEMO_CREW } from '../crew'
import type { AgentId, AgentMesh, AgentState, Board, Handoff, Talk } from '../types'
import { advanceSharedBoard, sharedBoard } from './board'

// Demo mode always shows the made-up crew (telemetry/crew.ts DEMO_CREW): Atlas the chief over Sage, Ivy and Rocky.
const CHIEF = DEMO_CREW.chief

const DESCRIPTION: Record<AgentId, string> = {
  atlas: 'Atlas: chief of staff. Briefings, reminders, the board, hands work to the team.',
  sage: 'Sage: tutor. Course pages, study blocks, reading and paper search.',
  ivy: 'Ivy: daily admin, research and planning. Calendar, email drafts, errands.',
  rocky: 'Rocky: coach. Training, meals, recovery and sleep.',
}

// MCP servers per agent in the demo; live mode reads each profile's config.yaml instead.
const MCP: Record<AgentId, Array<[string, boolean]>> = {
  atlas: [['moodle', true]],
  sage: [['moodle', true]],
  ivy: [['moodle', true]],
  rocky: [['weather-plus', true]],
}

function coreAgents(): AgentState[] {
  return DEMO_CREW.agents.map((a): AgentState => ({
    id: a.id, profile: a.profile, name: a.name, description: DESCRIPTION[a.id] ?? '', core: true, model: 'deepseek-flash',
    effort: 'medium', mcp: (MCP[a.id] ?? []).map(([name, enabled]) => ({ name, enabled })),
    reportsTo: a.id === CHIEF ? null : CHIEF,
    running: 0, queued: 0, blocked: 0, done7d: 0, lastActive: null,
  }))
}

/** The team at work in the demo: a 45 s loop where the chief hands a card to each specialist in turn. Live mode reads the
 * same thing from the board (bridge `feeds.talks`). */
const STAGES: Array<[string, string, string]> = [
  [CHIEF, 'sage', 'Plan revision for the statistics exam'],
  [CHIEF, 'ivy', 'Find a cheaper phone contract'],
  [CHIEF, 'rocky', 'A three-day training plan for this week'],
]
const STAGE_MS = 15_000

function crewAtWork(now: number): { talks: Talk[]; handoffs: Handoff[] } {
  const cycle = Math.floor(now / (STAGE_MS * STAGES.length))
  const i = Math.floor(now / STAGE_MS) % STAGES.length
  const start = Math.floor(now / STAGE_MS) * STAGE_MS
  const [from, to, title] = STAGES[i]!
  const handoffs: Handoff[] = []
  for (let k = 0; k <= i; k++) {
    const [f, t, ti] = STAGES[k]!
    const at = start - (i - k) * STAGE_MS
    handoffs.push({ at, from: f as AgentId, to: t as AgentId, kind: 'assign', title: ti, cardId: `demo-${cycle}-${k}` })
    if (k < i) handoffs.push({ at: at + STAGE_MS - 400, from: t as AgentId, to: f as AgentId, kind: 'done', title: ti, cardId: `demo-${cycle}-${k}` })
  }
  return { talks: [{ from: from as AgentId, to: to as AgentId, state: 'working', title, cardId: `demo-${cycle}-${i}`, since: start }], handoffs }
}

const RUN_TITLES: Record<string, string[]> = {
  atlas: ['Morning briefing', 'Sort the board', 'Weekly check-in', 'Evening wrap-up'],
  sage: ['Study plan', 'Course announcements', 'Reading list', 'Deadline reminders'],
  ivy: ['Inbox triage', 'Calendar clash', 'Grocery list', 'Morning briefing'],
  rocky: ['Training plan', 'Stretch reminder', 'Meal ideas', 'Sleep check-in'],
}

/** Demo heatmap: about 20 seeded runs per agent, mostly fine, now and then waiting or failed. */
function demoRuns(id: string, now: number): Pick<AgentState, 'runs' | 'reliability'> {
  const r = rng(hash(`runs:${id}`))
  const titles = RUN_TITLES[id] ?? ['A card from the chief', 'Scheduled job']
  const n = 12 + Math.floor(r() * 13)
  const runs = Array.from({ length: n }, (_, i) => {
    const x = r()
    const status = x < 0.06 ? 'error' : x < 0.14 ? 'waiting' : 'ok'
    const trigger = r() < 0.55 ? 'board' : 'cron'
    return { status, trigger, title: titles[Math.floor(r() * titles.length)]!, at: now - (n - i) * (2 + r() * 9) * 3_600_000,
      secs: Math.floor(20 + r() * 400) } as const
  })
  const ok = runs.filter((x) => x.status === 'ok').length
  const errors = runs.filter((x) => x.status === 'error').length
  return { runs: [...runs], reliability: { ok, errors, total: runs.length, pct: ok + errors ? Math.round(1000 * ok / (ok + errors)) / 10 : null } }
}

/** Loads from the board for each agent in `base` (the crew, or the list as it stands with demo edits). */
export function meshFromBoard(board: Board, now = Date.now(), base: AgentState[] = coreAgents()): AgentMesh {
  const week = now - 7 * 86_400_000
  const agents = base.map((a) => {
    const mine = board.cards.filter((c) => c.assignee === a.id)
    const last = Math.max(0, ...mine.map((c) => c.completedAt ?? c.startedAt ?? 0))
    return {
      ...a,
      running: mine.filter((c) => c.status === 'running').length,
      queued: mine.filter((c) => c.status === 'todo' || c.status === 'ready' || c.status === 'triage').length,
      blocked: mine.filter((c) => c.status === 'blocked' || c.status === 'review').length,
      done7d: mine.filter((c) => c.status === 'done' && (c.completedAt ?? 0) > week).length,
      lastActive: last || null,
      ...demoRuns(a.id, now),
    }
  })
  const handoffs: Handoff[] = []
  const ids = new Set(agents.map((a) => a.id))
  for (const c of board.cards) {
    if (!c.assignee || c.assignee === CHIEF) continue
    // as live: a card goes down from whoever made it, and its question or result goes back to them
    const boss = c.createdBy && c.createdBy !== c.assignee && (c.createdBy === 'owner' || ids.has(c.createdBy)) ? c.createdBy : CHIEF
    handoffs.push({ at: c.createdAt, from: boss, to: c.assignee, kind: 'assign', title: c.title, cardId: c.id })
    if (c.status === 'blocked') handoffs.push({ at: (c.startedAt ?? c.createdAt) + 600_000, from: c.assignee, to: boss, kind: 'question', title: c.title, cardId: c.id })
    if (c.completedAt) handoffs.push({ at: c.completedAt, from: c.assignee, to: boss, kind: 'done', title: c.title, cardId: c.id })
  }
  const crew = crewAtWork(now)
  handoffs.push(...crew.handoffs)
  handoffs.sort((x, y) => y.at - x.at)
  const talks: Talk[] = [...crew.talks]
  for (const c of board.cards) {
    if (!c.assignee || c.assignee === CHIEF) continue
    const boss = c.createdBy && c.createdBy !== c.assignee && (c.createdBy === 'owner' || ids.has(c.createdBy)) ? c.createdBy : CHIEF
    if (c.status === 'running') talks.push({ from: boss, to: c.assignee, state: 'working', title: c.title, cardId: c.id, since: c.startedAt ?? c.createdAt })
    if (c.status === 'blocked') talks.push({ from: c.assignee, to: boss, state: 'asking', title: c.title, cardId: c.id, since: c.startedAt ?? c.createdAt })
  }
  const busy = new Set(crew.talks.map((t) => t.to))
  const shown = agents.map((a) => (busy.has(a.id) ? { ...a, running: 1, lastActive: now } : a))
  return { at: now, gateway: { ok: true, version: '0.21.5' }, agents: shown, handoffs: handoffs.slice(0, 24), talks }
}

export function demoMesh(): AgentMesh {
  return meshFromBoard(sharedBoard())
}

export function tickMesh(prev: AgentMesh): AgentMesh {
  return meshFromBoard(advanceSharedBoard(), Date.now(), prev.agents)
}
