import { editSharedBoard } from '@/telemetry/demo/board'
import { reloadFeed } from '@/telemetry/feed'
import { boardFeed } from '@/telemetry/hooks/feeds'
import { live } from '@/telemetry/live/actions'
import { useMode } from '@/telemetry/mode'

const isLive = () => useMode.getState().mode === 'live'

export async function createCard(card: { title: string; body?: string; assignee?: string; assigneeId?: string; priority: number }) {
  if (isLive()) {
    const out = await live.createCard({ title: card.title, body: card.body, assignee: card.assignee, priority: card.priority })
    await reloadFeed(boardFeed)
    return out
  }
  const now = Date.now()
  const id = `t_demo${now.toString(36)}`
  boardFeed.setState({ data: editSharedBoard((b) => ({ ...b, at: now, cards: [{ id, title: card.title, status: card.assigneeId ? 'todo' : 'triage',
    assignee: card.assigneeId ?? null, assigneeProfile: null, createdBy: 'owner', priority: card.priority, createdAt: now, startedAt: null,
    completedAt: null, parents: [], summary: null, comments: card.body ? [{ author: 'owner', body: card.body, at: now }] : [] }, ...b.cards] })), at: now })
  return { id }
}

export async function answerCard(id: string, text: string) {
  if (isLive()) {
    await live.answerCard(id, text)
    await reloadFeed(boardFeed)
    return
  }
  const now = Date.now()
  boardFeed.setState({ data: editSharedBoard((b) => ({ ...b, at: now, cards: b.cards.map((c) => c.id !== id ? c : {
    ...c, status: 'ready', comments: [...c.comments, { author: 'owner', body: text, at: now }] }) })), at: now })
}
