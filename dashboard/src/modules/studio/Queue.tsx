import { Check, Download, ExternalLink, Music2, Play, RotateCcw, SkipForward, Undo2, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { studio, type Line, type Post, type PostStatus, type Sound, type StudioStatus } from '@/telemetry/studio'
import { useMode } from '@/telemetry/mode'
import { Button } from '@/ui/Button'
import { Chip, type Signal } from '@/ui/Chip'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'
import { ErrorNote, Still, dayLabel, useAct } from './shared'

const LABEL: Record<PostStatus, [string, Signal]> = {
  proposed: ['Video being made', 'memory'], ready: ['Waiting for your OK', 'warn'], approved: ['Approved: post it', 'ok'], delivered: ['Sent to you: post it', 'ok'], posted: ['Posted', 'idle'], skipped: ['Skipped', 'idle'],
}

function Preview({ p }: { p: Post }) {
  const [playing, setPlaying] = useState(false)
  const live = useMode((s) => s.mode) === 'live'
  const r = p.render
  return (
    <div className="relative aspect-[9/16] w-full overflow-hidden rounded-xl border border-line bg-void">
      {playing && r && live ? <video className="size-full object-cover" controls autoPlay playsInline src={r.video} onEnded={() => setPlaying(false)}><track kind="captions" /></video>
        : (
          <button type="button" disabled={!r} onClick={() => setPlaying(true)} aria-label={r ? 'Play the finished video' : 'The video is not made yet'} className="group relative block size-full">
            <Still src={r?.still ?? p.clip?.thumb} seed={p.clip?.id ?? p.id} className="size-full">
              {p.line && <span className="absolute inset-x-[10%] top-1/2 -translate-y-1/2 text-center text-[13px] leading-snug font-medium text-white [text-shadow:0_1px_6px_rgba(0,0,0,.7)]">{p.line.text}</span>}
              {r && <span className="absolute right-2 bottom-2 grid size-8 place-items-center rounded-full bg-black/55 opacity-90 group-hover:opacity-100"><Play className="size-3.5" /></span>}
              {!r && <span className="absolute inset-x-0 bottom-2 text-center text-2xs text-ink-faint">{p.making ? 'making the video…' : 'no video yet'}</span>}
            </Still>
          </button>
        )}
    </div>
  )
}

function PostCard({ p, lines, sounds, clips }: { p: Post; lines: Line[]; sounds: Sound[]; clips: StudioStatus['clips'] }) {
  const { busy, error, act, clear } = useAct()
  const [caption, setCaption] = useState(p.caption)
  const [edit, setEdit] = useState(false)
  const [label, signal] = LABEL[p.status]
  const locked = p.status === 'approved' || p.status === 'delivered' || p.status === 'posted'
  const open = p.status === 'proposed' || p.status === 'ready'
  const set = (body: Record<string, unknown>) => act('set', () => studio.post(p.id, body))
  const mv = (action: string, tone: 'confirm' | 'none' = 'none') => act(action, () => studio.post(p.id, { action }), tone)
  const problems = p.render?.problems ?? []

  return (
    <li className="glass flex flex-col gap-2.5 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium">{dayLabel(p.due)}</span>
        <span className="flex items-center gap-1.5">
          {p.kind === 'cta' && <Chip signal="agent">book line</Chip>}
          <Chip signal={signal} breathe={p.status === 'proposed' && p.making}>{label}</Chip>
        </span>
      </div>
      <div className="flex gap-3">
      <div className="w-[132px] shrink-0 sm:w-[150px]"><Preview p={p} /></div>

      <div className="min-w-0 flex-1 space-y-2 text-[12px]">
        {edit && open ? (
          <div className="space-y-2 rounded-lg border border-line bg-white/[0.02] p-2">
            <label className="block text-2xs text-ink-faint">Words on the video
              <select className="mt-0.5 w-full rounded-md border border-line-strong bg-void px-2 py-1 text-[12px] text-ink" value={p.line?.id ?? ''}
                onChange={(e) => void set({ action: 'set', line: e.target.value })}>
                {p.line && !lines.some((l) => l.id === p.line!.id) && <option value={p.line.id}>{p.line.text}</option>}
                {lines.filter((l) => l.status === 'approved').map((l) => <option key={l.id} value={l.id}>{l.kind === 'cta' ? '[book] ' : ''}{l.text}</option>)}
              </select>
            </label>
            <label className="block text-2xs text-ink-faint">Scene
              <select className="mt-0.5 w-full rounded-md border border-line-strong bg-void px-2 py-1 text-[12px] text-ink" value={p.clip?.id ?? ''}
                onChange={(e) => void set({ action: 'set', clip: e.target.value })}>
                {(clips ?? []).filter((c) => !c.disabled || c.id === p.clip?.id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label className="block text-2xs text-ink-faint">Sound
              <select className="mt-0.5 w-full rounded-md border border-line-strong bg-void px-2 py-1 text-[12px] text-ink" value={p.sound?.id ?? ''}
                onChange={(e) => void set({ action: 'set', sound: e.target.value })}>
                {sounds.filter((s) => !s.disabled || s.id === p.sound?.id).map((s) => <option key={s.id} value={s.id}>{s.title || s.url}{s.artist ? ` · ${s.artist}` : ''}</option>)}
              </select>
            </label>
            <p className="text-2xs text-ink-faint">Changing the words or the scene makes the video again (a minute or so).</p>
          </div>
        ) : (
          <div className="space-y-1">
            <p className="text-[13px] leading-snug">&ldquo;{p.line?.text ?? 'no words chosen'}&rdquo;</p>
            <p className="text-ink-faint">Scene: {p.clip?.name ?? 'none'}</p>
            {p.sound
              ? <p className="flex items-center gap-1 text-ink-dim"><Music2 className="size-3 shrink-0" /><span className="min-w-0 flex-1 truncate">{p.sound.title || 'Sound'}{p.sound.artist ? ` · ${p.sound.artist}` : ''}</span>
                <a href={p.sound.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-memory hover:underline">open in TikTok <ExternalLink className="size-3" /></a></p>
              : <p className="text-ink-faint">No sound chosen</p>}
          </div>
        )}

        <label className="block text-2xs text-ink-faint">Caption
          <textarea rows={2} disabled={locked} value={caption} onChange={(e) => setCaption(e.target.value)}
            onBlur={() => { if (caption !== p.caption && caption.trim()) void set({ action: 'set', caption }) }}
            className="mt-0.5 w-full resize-none rounded-md border border-line-strong bg-void px-2 py-1 text-[12px] text-ink disabled:opacity-60" />
        </label>
        {p.note && <p className="text-2xs text-ink-faint">Note: {p.note}</p>}
        {problems.length > 0 && <p className="rounded-md border border-runway/40 bg-runway/10 px-2 py-1 text-2xs text-[#fcd34d]">Check: {problems.join('; ')}</p>}
      </div>
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-1.5">
        {p.status === 'ready' && <Button size="sm" tone="memory" icon={<Check className="size-3.5" />} disabled={busy !== null} onClick={() => void mv('approve', 'confirm')}>Approve</Button>}
        {open && <Button size="sm" tone="ghost" icon={<Wand2 className="size-3.5" />} onClick={() => setEdit((e) => !e)}>{edit ? 'Done' : 'Change'}</Button>}
        {open && <Button size="sm" tone="ghost" icon={<RotateCcw className="size-3.5" />} disabled={busy !== null || p.making} onClick={() => void mv('render')} title="Make the video again">Remake</Button>}
        {(p.status === 'approved' || p.status === 'delivered') && <>
          <Button size="sm" tone="memory" icon={<Check className="size-3.5" />} disabled={busy !== null} onClick={() => void mv('posted', 'confirm')}>I posted it</Button>
          {p.render && <a href={`${p.render.video}?download`} className="press inline-flex h-7 items-center gap-1.5 rounded-lg border border-line-strong px-2.5 text-xs hover:bg-white/[0.06]"><Download className="size-3.5" />Download</a>}
          <Button size="sm" tone="ghost" icon={<Undo2 className="size-3.5" />} disabled={busy !== null} onClick={() => void mv('unapprove')}>Take back</Button>
        </>}
        {open && (
          <ConfirmButton size="sm" tone="ghost" label="Skip" confirmLabel="Skip this post" icon={<SkipForward className="size-3.5" />} onConfirm={() => studio.post(p.id, { action: 'skip' })} />
        )}
        {p.status === 'skipped' && <Button size="sm" tone="ghost" disabled={busy !== null} onClick={() => void mv('unskip')}>Put back</Button>}
      </div>
      <ErrorNote error={error} onClose={clear} />
    </li>
  )
}

export function Queue({ s }: { s: StudioStatus }) {
  const queue = s.queue ?? []
  const lines = s.lines ?? []
  const sounds = s.sounds ?? []
  const waiting = queue.filter((p) => p.status === 'ready')
  const todo = queue.filter((p) => p.status === 'approved' || p.status === 'delivered')
  const making = queue.filter((p) => p.status === 'proposed')
  const done = queue.filter((p) => p.status === 'posted' || p.status === 'skipped').sort((a, b) => (b.due ?? '').localeCompare(a.due ?? '')).slice(0, 12)
  const by = (a: Post, b: Post) => (a.due ?? '').localeCompare(b.due ?? '')
  const group = (title: string, hint: string, list: Post[], tone?: string) => list.length === 0 ? null : (
    <Panel key={title} title={<>{title} <span className={cn('num ml-1 font-normal', tone ?? 'text-ink-faint')}>{list.length}</span></>} aside={<span className="hidden text-2xs text-ink-faint sm:inline">{hint}</span>}>
      <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-3">{[...list].sort(by).map((p) => <PostCard key={p.id} p={p} lines={lines} sounds={sounds} clips={s.clips} />)}</ul>
    </Panel>
  )
  if (queue.length === 0) {
    return (
      <Panel title="Nothing planned yet">
        <p className="text-[13px] text-ink-dim">Add some scenes, a few overlay lines and a sound or two, then press <b>Plan posts</b>. Each planned post appears here as a finished 15-second video for you to approve.</p>
      </Panel>
    )
  }
  return (
    <div className="space-y-4">
      {group('Waiting for your OK', 'check the words, the scene and the sound, then approve', waiting, 'text-[#fcd34d]')}
      {group('Approved: ready to post', 'download the video, post it in TikTok with the sound, then press “I posted it”', todo, 'text-ok')}
      {group('Videos being made', 'ready in a minute or two', making)}
      {group('Recently posted or skipped', '', done)}
    </div>
  )
}
