import type { AgentId, Board, Card, CardStatus } from '../types'
import { rng } from '@/lib/rng'
import { DEMO_TEAM } from '../team'

// Invented cards in the board's real shape, for the demo team. Titles are the kind of work the team does, not real tasks.
const CHIEF = DEMO_TEAM.chief
const SEED: Array<[string, AgentId, CardStatus, number, AgentId?]> = [
  ['Draft this week’s study plan around the two lab deadlines', 'sage', 'running', 9],
  ['Find the open-access version of the statistics reading', 'sage', 'todo', 5],
  ['Summarise the course announcements since Monday', 'sage', 'done', 0],
  ['Book a swimming lane if Friday’s forecast is wet', 'rocky', 'blocked', 10],
  ['Weekly training plan, with a rest day after the long run', 'rocky', 'done', 0],
  ['Sort the inbox and draft replies for the three that need one', 'ivy', 'running', 8],
  ['Grocery list for Sunday, grouped by aisle', 'ivy', 'todo', 2],
  ['Remind about the dentist the day before', 'ivy', 'done', 0],
  ['Compare three phone contracts under £10 a month', 'ivy', 'review', 20],
  ['Check the library opening hours for reading week', 'sage', 'todo', 9],
  ['Plan meals around the late lab on Wednesday', 'rocky', 'done', 0],
  ['Cancel the unused streaming trial (needs your yes)', 'ivy', 'blocked', 25],
  ['Morning briefing for Tuesday', CHIEF, 'done', 0],
  ['Check what is still waiting on you', CHIEF, 'triage', 0],
  // a specialist handing part of a job to another
  ['Find two cheap healthy lunches near campus', 'rocky', 'todo', 7, 'ivy'],
]

const HOUR = 3_600_000

export function demoCards(now = Date.now()): Card[] {
  return SEED.map(([title, assignee, status, priority, by], i) => {
    const r = rng(1000 + i)
    const created = now - Math.floor((status === 'running' ? 0.8 : 2 + r() * 70) * HOUR)
    const started = status === 'todo' || status === 'triage' ? null
      : status === 'running' ? now - Math.floor((5 + r() * 35) * 60_000)
        : created + Math.floor(r() * 2 * HOUR)
    const completed = status === 'done' ? (started ?? created) + Math.floor((0.2 + r() * 3) * HOUR) : null
    return {
      id: `t_demo${String(i).padStart(3, '0')}`,
      title,
      status,
      assignee,
      assigneeProfile: null,
      createdBy: by ?? (assignee === CHIEF ? 'owner' : CHIEF),
      priority,
      createdAt: created,
      startedAt: started,
      completedAt: completed,
      parents: i === 11 ? ['t_demo009'] : [],
      summary: status === 'done' ? 'Finished and reported back.' : status === 'blocked' ? 'Waiting for your answer.' : null,
      comments: status === 'blocked' ? [{ author: assignee, body: i === 3 ? 'Friday looks wet after 18:00. A lane at 19:30 (£4) or move to Saturday morning?' : 'The trial ends on Sunday and then costs £8.99 a month. OK to cancel it?', at: now - 50 * 60_000 }] : [],
    }
  })
}

export function demoBoard(): Board {
  const now = Date.now()
  return { at: now, cards: demoCards(now) }
}

/** Demo: now and then a queued card starts, a running one finishes (never more than two running, like the real dispatcher). */
export function tickBoard(prev: Board): Board {
  const now = Date.now()
  const cards = prev.cards.map((c) => ({ ...c }))
  const running = cards.filter((c) => c.status === 'running')
  if (Math.random() < 0.5 && running.length) {
    const c = running[Math.floor(Math.random() * running.length)]!
    c.status = 'done'
    c.completedAt = now
    c.summary = 'Finished and reported back.'
  } else {
    const next = cards.filter((c) => c.status === 'todo').sort((a, b) => b.priority - a.priority)[0]
    if (next && running.length < 2) {
      next.status = 'running'
      next.startedAt = now
    } else {
      const done = cards.filter((c) => c.status === 'done')
      const back = done[Math.floor(Math.random() * done.length)]
      if (back) { back.status = 'todo'; back.startedAt = null; back.completedAt = null; back.summary = null; back.createdAt = now }
    }
  }
  return { ...prev, at: now, cards }
}

// One demo board shared by the Board and Agent Studio views, so both tell the same story.
let shared: Board | null = null

export function sharedBoard(): Board {
  shared ??= demoBoard()
  return shared
}

export function advanceSharedBoard(): Board {
  shared = tickBoard(sharedBoard())
  return shared
}

/** Demo writes (new card, answer): change the shared board so the Board and Agent Studio both see it. */
export function editSharedBoard(fn: (b: Board) => Board): Board {
  shared = fn(sharedBoard())
  return shared
}
