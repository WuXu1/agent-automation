import { CircleAlert, ListVideo, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { useMode } from '@/telemetry/mode'
import { studio, useStudio } from '@/telemetry/studio'
import { Button } from '@/ui/Button'
import { Chip } from '@/ui/Chip'
import { FeedError, FeedStatus } from '@/ui/FeedStatus'
import { Panel } from '@/ui/Panel'
import { ago } from '@/lib/time'
import { Clips } from './Clips'
import { Lines } from './Lines'
import { Queue } from './Queue'
import { Sounds } from './Sounds'
import { StyleTab } from './StyleTab'
import { ErrorNote, useAct } from './shared'

type Tab = 'queue' | 'clips' | 'lines' | 'sounds' | 'style'

/** The content studio: scenes, overlay lines and sounds go in; planned posts come out as finished videos for the owner to approve and post by hand. */
export default function StudioView() {
  const feed = useStudio()
  const setMode = useMode((s) => s.setMode)
  const [tab, setTab] = useState<Tab>('queue')
  const { busy, error, act, clear } = useAct()
  const [note, setNote] = useState<string | null>(null)
  const s = feed.data

  if (!s) return <div className="h-full overflow-y-auto"><div className="mx-auto max-w-[1400px] p-3 md:p-6">{feed.status === 'error' ? <FeedError error={feed.error} onDemo={() => setMode('demo')} /> : <div className="glass h-64 animate-pulse" />}</div></div>
  if (!s.installed) {
    return (
      <div className="h-full overflow-y-auto"><div className="mx-auto max-w-xl p-6">
        <Panel title="The content studio is not set up on this server yet"><p className="text-[13px] text-ink-dim">Run <code className="rounded bg-white/[0.06] px-1.5 py-0.5">sudo hermes-addon studio</code> on the server, then come back.</p></Panel>
      </div></div>
    )
  }

  const n = s.needs
  const waiting = n?.posts.ready ?? 0
  const tabs: Array<[Tab, string, number | null]> = [['queue', 'Posts', waiting || null], ['clips', 'Scenes', n?.clips ?? null], ['lines', 'Lines', n?.lines_suggested || null], ['sounds', 'Sounds', s.sounds?.length ?? null], ['style', 'Look & settings', null]]
  const busyNow = s.worker?.busy
  const failures = s.worker?.failures ?? []
  const crewMissing = s.crew.filter((c) => !c.installed)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] p-3 md:p-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-ink-dim">
            {n ? <>Planned <b className="text-ink">{n.days_planned_ahead}</b> day{n.days_planned_ahead === 1 ? '' : 's'} ahead.{waiting > 0 && <span className="text-[#fcd34d]"> {waiting} post{waiting > 1 ? 's are' : ' is'} waiting for your OK.</span>}</> : 'Your posts, scenes, lines and sounds.'}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <FeedStatus feed={feed} source="the studio" />
            <Button size="sm" icon={<ListVideo className="size-3.5" />} disabled={busy !== null} title="Free and instant: fills the queue from your scenes, lines and sounds by the rules, then makes the videos"
              onClick={() => void act('propose', async () => { const r = await studio.propose(); setNote(r ? (r.added ? `${r.added} post${r.added > 1 ? 's' : ''} added; the videos are being made.` : r.short.length ? `Nothing added: not enough ${r.short.join(', ')}.` : 'The queue is already planned that far ahead.') : 'Added (demo).') }, 'confirm')}>Plan posts</Button>
            <Button size="sm" tone="memory" icon={<Sparkles className="size-3.5" />} disabled={busy !== null} title="Asks the Content Director: the team watches new scenes, writes lines if you are short, checks every pairing. A few pence."
              onClick={() => void act('plan', async () => { const r = await studio.plan(); setNote(r?.card ? 'The Content Director has the job; you will see the posts appear here.' : 'Asked (demo).') }, 'confirm')}>Ask the team to plan</Button>
          </div>
        </div>
        {note && <p className="mb-3 rounded-lg border border-ok/30 bg-ok/10 px-3 py-1.5 text-[12px] text-[#6ee7b7]">{note}</p>}
        <ErrorNote error={error} onClose={clear} />

        {(crewMissing.length > 0 || failures.length > 0 || busyNow) && (
          <div className="mb-3 flex flex-wrap items-center gap-2 text-[12px]">
            {busyNow && <Chip signal="memory" breathe>Working: {busyNow.verb === 'render' ? 'making a video' : busyNow.verb === 'tag' ? 'watching a scene' : 'preparing an upload'} · {ago(Date.parse(busyNow.since))}</Chip>}
            {crewMissing.length > 0 && <Chip signal="warn">Not installed: {crewMissing.map((c) => c.name).join(', ')}</Chip>}
            {failures.length > 0 && (
              <span className="inline-flex flex-wrap items-center gap-2 text-[#fca5a5]"><CircleAlert className="size-3.5" />
                {failures.length} thing{failures.length > 1 ? 's' : ''} went wrong; latest: {failures[failures.length - 1]?.message}
                <button type="button" className="underline hover:text-ink" onClick={() => void studio.clearFailures()}>clear</button>
              </span>
            )}
          </div>
        )}

        <div role="tablist" aria-label="Content studio" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
          {tabs.map(([id, label, count]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
              className={cn('press -mb-px inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 px-3 text-[13px]', tab === id ? 'border-memory text-ink' : 'border-transparent text-ink-dim hover:text-ink')}>
              {label}{count ? <span className="num rounded-full bg-white/[0.08] px-1.5 text-2xs">{count}</span> : null}
            </button>
          ))}
        </div>

        {tab === 'queue' && <Queue s={s} />}
        {tab === 'clips' && <Clips s={s} />}
        {tab === 'lines' && <Lines s={s} />}
        {tab === 'sounds' && <Sounds s={s} />}
        {tab === 'style' && <StyleTab s={s} />}
        {n && tab === 'queue' && (n.clips_free === 0 || n.lines_approved_free === 0 || n.sounds_free === 0) && (
          <p className="mt-4 text-2xs text-ink-faint">Running low: {[n.clips_free === 0 && 'scenes', n.lines_approved_free === 0 && 'overlay lines', n.sounds_free === 0 && 'sounds'].filter(Boolean).join(', ')}. The planner can only use what has rested long enough.</p>
        )}
      </div>
    </div>
  )
}
