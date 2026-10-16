import { ExternalLink, Music2, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { studio, type Sound, type StudioStatus } from '@/telemetry/studio'
import { Button } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'
import { ErrorNote, useAct } from './shared'

function Row({ x }: { x: Sound }) {
  const { busy, error, act, clear } = useAct()
  return (
    <li className={cn('rounded-lg border border-line bg-white/[0.02] px-3 py-2', x.disabled && 'opacity-60')}>
      <div className="flex items-center gap-3">
        <Music2 className="size-4 shrink-0 text-ink-faint" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px]">{x.title || 'Untitled sound'}{x.artist ? <span className="text-ink-faint"> · {x.artist}</span> : null}</div>
          <a href={x.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-2xs text-memory hover:underline">{x.url.replace(/^https:\/\/(www\.)?/, '')}<ExternalLink className="size-3 shrink-0" /></a>
        </div>
        <Button size="sm" tone="ghost" disabled={busy !== null} onClick={() => void act('toggle', () => studio.sound(x.id, { disabled: !x.disabled }))}>{x.disabled ? 'Use again' : 'Pause'}</Button>
        <ConfirmButton size="sm" tone="ghost" label="" ariaLabel="Delete the sound" confirmLabel="Delete" confirmTone="danger" icon={<Trash2 className="size-3.5" />} onConfirm={() => studio.deleteSound(x.id)} />
      </div>
      <ErrorNote error={error} onClose={clear} />
    </li>
  )
}

export function Sounds({ s }: { s: StudioStatus }) {
  const sounds = s.sounds ?? []
  const { busy, error, act, clear } = useAct()
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [artist, setArtist] = useState('')
  return (
    <Panel title={<>TikTok sounds <span className="num ml-1 font-normal text-ink-faint">{sounds.length}</span></>} aside={<span className="hidden text-2xs text-ink-faint sm:inline">the planner picks one for each post</span>}>
      <div className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr_auto]">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Paste a TikTok sound link" aria-label="TikTok sound link" className="rounded-lg border border-line-strong bg-void px-3 py-1.5 text-[13px]" />
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Name (Limerence)" aria-label="Sound name" className="rounded-lg border border-line-strong bg-void px-3 py-1.5 text-[13px]" />
        <input value={artist} onChange={(e) => setArtist(e.target.value)} placeholder="Artist" aria-label="Artist" className="rounded-lg border border-line-strong bg-void px-3 py-1.5 text-[13px]" />
        <Button tone="memory" icon={<Plus className="size-3.5" />} disabled={busy !== null || !url.trim()}
          onClick={() => void act('add', async () => { await studio.addSound(url.trim(), title.trim(), artist.trim()); setUrl(''); setTitle(''); setArtist('') }, 'confirm')}>Add</Button>
      </div>
      <ErrorNote error={error} onClose={clear} />
      <p className="mt-2 text-2xs text-ink-faint">In TikTok, open the sound, tap Share, then Copy link. TikTok does not let a program attach its library sounds, so the finished video comes with the sound&rsquo;s link and you add the sound when you post. A sound rests for {s.settings?.sound_rest_days ?? 7} days after it is used.</p>
      {sounds.length === 0 ? <p className="mt-3 text-[12px] text-ink-faint">No sounds yet.</p> : <ul className="mt-3 space-y-1.5">{sounds.map((x) => <Row key={x.id} x={x} />)}</ul>}
    </Panel>
  )
}
