import { Link2, MessageSquareReply, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import { cn } from '@/lib/cn'
import { ago, duration, stamp } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { agentName, useRoster } from '@/telemetry/agents'
import { chiefId, useChief } from '@/telemetry/crew'
import { useBoard } from '@/telemetry/hooks/feeds'
import { useMode } from '@/telemetry/mode'
import type { Card, CardStatus } from '@/telemetry/types'
import { AgentBadge } from '@/ui/AgentBadge'
import { Chip } from '@/ui/Chip'
import { Drawer } from '@/ui/Drawer'
import { FeedError, FeedStatus } from '@/ui/FeedStatus'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { play } from '@/lib/sound'
import { answerCard, createCard } from './writes'

const HIGH = 20
const WEEK = 7 * 86_400_000

const COLUMNS: Array<{ id: string; label: string; hint: string; has: CardStatus[] }> = [
  { id: 'todo', label: 'To do', hint: 'waiting for a free slot', has: ['triage', 'todo', 'ready', 'scheduled'] },
  { id: 'running', label: 'Running', hint: 'two at a time', has: ['running'] },
  { id: 'waiting', label: 'Waiting on someone', hint: 'a question or a review', has: ['blocked', 'review'] },
  { id: 'done', label: 'Done this week', hint: '', has: ['done'] },
]

const STATUS_LABEL: Record<CardStatus, string> = {
  triage: 'new, not sorted yet', todo: 'to do', ready: 'ready', scheduled: 'scheduled', running: 'running', blocked: 'blocked: has a question',
  review: 'waiting for review', done: 'done', archived: 'archived',
}

function who(c: Card): string {
  return c.assignee ? agentName(c.assignee) : (c.assigneeProfile ?? `${agentName(chiefId())} will sort it`)
}

function CardTile({ card, now, onOpen }: { card: Card; now: number; onOpen: () => void }) {
  const high = card.priority >= HIGH
  const time = card.completedAt ?? card.startedAt ?? card.createdAt
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={cn(
          'press w-full rounded-xl border bg-white/[0.025] p-3 text-left hover:border-line-strong hover:bg-white/[0.045]',
          high ? 'border-agent/35' : 'border-line',
        )}
      >
        <div className="flex items-start gap-2.5">
          <AgentBadge id={card.assignee} className="mt-px" />
          <span className="line-clamp-3 flex-1 text-[13px] leading-snug text-ink">{card.title}</span>
        </div>
        <div className="mt-2 flex items-center gap-2 pl-7 text-2xs text-ink-faint">
          <span>{who(card)}</span>
          <span aria-hidden>·</span>
          <span>{card.status === 'running' && card.startedAt ? `for ${duration((now - card.startedAt) / 1000)}` : ago(time)}</span>
          {card.parents.length > 0 && <Link2 className="size-3" aria-label="waits for another card" />}
          {high && <span className="ml-auto rounded-full bg-agent/15 px-1.5 py-px text-[10px] font-medium text-[#f0abfc]">high</span>}
        </div>
      </button>
    </li>
  )
}

function Columns({ cards, onOpen }: { cards: Card[]; onOpen: (id: string) => void }) {
  const now = useNow(30_000).getTime()
  const chief = useChief()
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-3 md:grid-cols-2 xl:grid-cols-4">
      {COLUMNS.map((col) => {
        let list = cards.filter((c) => col.has.includes(c.status))
        if (col.id === 'done') list = list.filter((c) => (c.completedAt ?? 0) > now - WEEK).sort((a, b) => (b.completedAt ?? 0) - (a.completedAt ?? 0))
        else list = list.sort((a, b) => b.priority - a.priority || a.createdAt - b.createdAt)
        const full = col.id === 'running' && list.length >= 2
        return (
          <section key={col.id} className="glass flex max-h-[min(70vh,640px)] min-h-[180px] flex-col" aria-label={col.label}>
            <header className="flex items-baseline justify-between px-4 pt-3.5 pb-2">
              <h2 className="text-[13px] font-semibold">{col.label} <span className="num ml-1 font-normal text-ink-faint">{list.length}</span></h2>
              <span className={cn('text-2xs', full ? 'text-[#fcd34d]' : 'text-ink-faint')}>{full ? 'both slots busy' : col.hint}</span>
            </header>
            {list.length === 0 ? (
              <p className="px-4 pb-4 text-[12px] text-ink-faint">
                {col.id === 'running' ? `Nothing running. ${chief.name} checks the board every minute.` : col.id === 'waiting' ? 'Nobody is waiting on anyone.' : col.id === 'todo' ? 'The queue is empty.' : 'Nothing finished in the last 7 days.'}
              </p>
            ) : (
              <ul className="min-h-0 space-y-2 overflow-y-auto px-3 pb-3">
                {list.map((c) => <CardTile key={c.id} card={c} now={now} onOpen={() => onOpen(c.id)} />)}
              </ul>
            )}
          </section>
        )
      })}
    </div>
  )
}

/** A blocked card waits on you: your answer unblocks it (`hermes kanban unblock --reason`) and goes back to the agent. */
function Answer({ card }: { card: Card }) {
  const [text, setText] = useState('')
  const mode = useMode((s) => s.mode)
  return (
    <div className="mt-4 rounded-lg border border-runway/40 bg-runway/[0.06] p-3">
      <label htmlFor="answer" className="mb-1.5 block text-[12px] font-semibold text-[#fcd34d]">This card is waiting for your answer</label>
      <textarea id="answer" value={text} onChange={(e) => setText(e.target.value.slice(0, 2000))} rows={3} placeholder="Your answer…"
        className="w-full resize-y rounded-lg border border-line bg-void/50 px-3 py-2 text-[13px] text-ink outline-none focus:border-line-strong" />
      <div className="mt-2 flex items-center gap-2">
        <ConfirmButton label="Answer and unblock" confirmLabel={`Send to ${card.assignee ? agentName(card.assignee) : 'the agent'}`} tone="memory"
          icon={<MessageSquareReply className="size-3.5" />} disabled={!text.trim()}
          onConfirm={async () => { await answerCard(card.id, text.trim()); setText(''); play('confirm') }} />
        <span className="text-2xs text-ink-faint">{mode === 'live' ? 'Recorded on the card as your answer.' : 'Demo: this tab only.'}</span>
      </div>
    </div>
  )
}

const PRIORITY = [{ label: 'Normal', value: 0 }, { label: 'Soon', value: 10 }, { label: 'High', value: 25 }]

/** A new card for the board. Without a name the chief sorts it on the next look (every minute). */
function NewCard({ onDone }: { onDone: (id: string | null) => void }) {
  const roster = useRoster((s) => s.list)
  const chief = useChief()
  const mode = useMode((s) => s.mode)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [who, setWho] = useState('')
  const [priority, setPriority] = useState(0)
  const field = 'w-full rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[13px] text-ink outline-none placeholder:text-ink-faint focus:border-line-strong'
  const agent = roster.find((a) => a.id === who)
  return (
    <div className="space-y-4">
      <label className="block"><span className="mb-1 block text-[12px] font-medium">What needs doing</span>
        <input className={field} value={title} onChange={(e) => setTitle(e.target.value.slice(0, 200))} placeholder="e.g. Find three readable papers on sleep and memory for the essay" />
      </label>
      <label className="block"><span className="mb-1 block text-[12px] font-medium">Details <span className="font-normal text-ink-faint">· the goal, facts, what done looks like</span></span>
        <textarea className={`${field} resize-y leading-relaxed`} rows={6} value={body} onChange={(e) => setBody(e.target.value.slice(0, 4000))} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="block"><span className="mb-1 block text-[12px] font-medium">For</span>
          <select className={field} value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">Let {chief.name} decide</option>
            {roster.filter((a) => a.id !== chief.id).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
        <div><span className="mb-1 block text-[12px] font-medium">Priority</span>
          <div className="flex h-[38px] gap-0.5 rounded-lg border border-line p-0.5">
            {PRIORITY.map((p) => (
              <button key={p.value} type="button" aria-pressed={priority === p.value} onClick={() => setPriority(p.value)}
                className={cn('press flex-1 rounded-md text-[12px]', priority === p.value ? 'bg-white/[0.08] text-ink' : 'text-ink-faint hover:text-ink-dim')}>{p.label}</button>
            ))}
          </div>
        </div>
      </div>
      <ConfirmButton label="Add to the board" confirmLabel={`Add it${agent ? ` for ${agent.name}` : ''}`} tone="memory" icon={<Plus className="size-3.5" />}
        disabled={!title.trim()}
        onConfirm={async () => { const out = await createCard({ title: title.trim(), body: body.trim() || undefined, assignee: agent?.profile, assigneeId: agent?.id, priority }); play('confirm'); onDone(out.id) }} />
      <p className="text-2xs text-ink-faint">{mode === 'live' ? 'Runs hermes kanban create. A card picks up within a minute when a slot is free (two run at once).' : 'Demo: this tab only.'}</p>
    </div>
  )
}

function CardDetail({ card, cards }: { card: Card; cards: Card[] }) {
  const parents = card.parents.map((p) => cards.find((c) => c.id === p)).filter(Boolean) as Card[]
  const row = (k: string, v: React.ReactNode) => (
    <div className="flex justify-between gap-4 py-1.5"><dt className="text-2xs text-ink-faint">{k}</dt><dd className="text-right text-[12px] text-ink-dim">{v}</dd></div>
  )
  return (
    <>
      <p className="text-[16px] leading-relaxed tracking-[-0.01em]">{card.title}</p>
      <dl className="mt-4 divide-y divide-line border-y border-line">
        {row('State', STATUS_LABEL[card.status])}
        {row('With', <span className="inline-flex items-center gap-1.5"><AgentBadge id={card.assignee} />{who(card)}</span>)}
        {card.createdBy && row('Asked by', card.createdBy === 'owner' ? 'you' : card.createdBy === 'helper' ? 'a helper' : agentName(card.createdBy))}
        {row('Priority', <span className="num">{card.priority}{card.priority >= HIGH ? ' (high)' : ''}</span>)}
        {row('Created', stamp(card.createdAt))}
        {card.startedAt && row('Started', stamp(card.startedAt))}
        {card.completedAt && row('Finished', `${stamp(card.completedAt)}${card.startedAt ? ` · took ${duration((card.completedAt - card.startedAt) / 1000)}` : ''}`)}
        {row('Card', <span className="num">{card.id}</span>)}
      </dl>
      {parents.length > 0 && (
        <>
          <h3 className="mt-4 mb-1 text-[12px] font-semibold">Waits for</h3>
          <ul className="space-y-1 text-[12px] text-ink-dim">{parents.map((p) => <li key={p.id}>{p.title} <span className="text-ink-faint">({STATUS_LABEL[p.status]})</span></li>)}</ul>
        </>
      )}
      {card.comments.length > 0 && (
        <>
          <h3 className="mt-4 mb-1.5 text-[12px] font-semibold">Latest on the card</h3>
          <ol className="space-y-2">
            {card.comments.map((c) => (
              <li key={`${c.at}-${c.author}`} className="rounded-lg border border-line bg-white/[0.02] px-3 py-2">
                <div className="mb-0.5 flex justify-between text-2xs"><span className={c.author === 'owner' ? 'text-memory' : 'text-[#f0abfc]'}>{c.author === 'owner' ? 'You' : agentName(c.author)}</span><span className="num text-ink-faint">{stamp(c.at)}</span></div>
                <p className="text-[12px] leading-relaxed whitespace-pre-line text-ink-dim">{c.body}</p>
              </li>
            ))}
          </ol>
        </>
      )}
      {card.status === 'blocked' && <Answer card={card} />}
      <h3 className="mt-4 mb-1 text-[12px] font-semibold">Last result</h3>
      <p className="text-[13px] leading-relaxed whitespace-pre-line text-ink-dim">{card.summary ?? 'Nothing reported yet.'}</p>
      <p className="mt-5 text-2xs text-ink-faint">To change or cancel a card, ask {agentName(chiefId())}.</p>
    </>
  )
}

/** The kanban board the chief runs: cards, who has them, and the ones waiting on you. */
export default function BoardView() {
  const feed = useBoard()
  const chief = useChief()
  const setMode = useMode((s) => s.setMode)
  const [openId, setOpenId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const board = feed.data
  const card = useMemo(() => board?.cards.find((c) => c.id === openId) ?? null, [board, openId])
  const waiting = board?.cards.filter((c) => c.status === 'blocked').length ?? 0

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] p-3 md:p-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-ink-dim">
            {chief.name} hands cards to the team; at most two run at once.{waiting > 0 && <span className="text-[#fcd34d]"> {waiting} card{waiting > 1 ? 's are' : ' is'} waiting for an answer.</span>}
          </p>
          <div className="flex items-center gap-2">
            <FeedStatus feed={feed} source="the board" />
            <Button tone="memory" size="sm" icon={<Plus className="size-3.5" />} onClick={() => { setOpenId(null); setCreating(true) }} disabled={!board}>New card</Button>
          </div>
        </div>
        {!board ? (
          feed.status === 'error' ? <FeedError error={feed.error} onDemo={() => setMode('demo')} /> : <div className="glass h-64 animate-pulse" />
        ) : (
          <Columns cards={board.cards} onOpen={setOpenId} />
        )}
      </div>
      <Drawer open={creating} onClose={() => setCreating(false)} title="New card">
        <NewCard onDone={(id) => { setCreating(false); if (id) setOpenId(id) }} />
      </Drawer>
      <Drawer open={Boolean(card) && !creating} onClose={() => setOpenId(null)} title={card ? <span className="inline-flex items-center gap-2">Card {card.priority >= HIGH && <Chip signal="agent">high priority</Chip>}</span> : ''}>
        {card && board ? <CardDetail card={card} cards={board.cards} /> : null}
      </Drawer>
    </div>
  )
}
