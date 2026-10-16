import { EyeOff, Eye, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { ago, bytes, duration } from '@/lib/time'
import { studio, type Clip, type StudioStatus } from '@/telemetry/studio'
import { Button } from '@/ui/Button'
import { Chip } from '@/ui/Chip'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'
import { ErrorNote, Still, UploadZone, useAct } from './shared'

function Tile({ c, waiting }: { c: Clip; waiting: boolean }) {
  const { busy, error, act, clear } = useAct()
  const [open, setOpen] = useState(false)
  const t = c.tags
  return (
    <li className={cn('overflow-hidden rounded-xl border border-line bg-white/[0.02]', c.disabled && 'opacity-60')}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={`Details of ${c.name}`} className="block w-full">
        <Still src={c.thumb} seed={c.id} className="aspect-[9/12] w-full">
          {c.duration != null && <span className="num absolute right-1.5 bottom-1.5 rounded bg-black/60 px-1.5 text-2xs">{duration(c.duration)}</span>}
          <span className="absolute top-1.5 left-1.5 flex gap-1">
            {c.disabled && <Chip signal="idle">off</Chip>}
            {!c.tagged && !c.disabled && <Chip signal="memory" breathe={waiting}>{waiting ? 'being watched' : 'not watched yet'}</Chip>}
          </span>
        </Still>
      </button>
      <div className="p-2">
        <div className="truncate text-[12px] font-medium" title={c.name}>{c.name}</div>
        <div className="num text-2xs text-ink-faint">{c.uses ? `used ${c.uses}×${c.lastUsed ? `, ${ago(Date.parse(c.lastUsed))}` : ''}` : 'not used yet'}{c.bytes ? ` · ${bytes(c.bytes)}` : ''}</div>
        {open && (
          <div className="mt-2 space-y-2 border-t border-line pt-2 text-[12px]">
            {t ? (
              <>
                <p className="text-ink-dim">{t.summary}</p>
                <p className="text-2xs text-ink-faint">{[t.mood, t.time_of_day, t.weather].filter(Boolean).join(' · ')}{t.calm != null ? ` · calm ${t.calm}/10` : ''}{t.has_people ? ' · has people' : ''}</p>
                {t.problems && t.problems.length > 0 && <p className="text-2xs text-[#fcd34d]">Problems: {t.problems.join(', ')}</p>}
              </>
            ) : <p className="text-ink-faint">The AI has not watched this one yet; it does that the next time posts are planned.</p>}
            {c.disabled && c.disabledReason && <p className="text-2xs text-ink-faint">Off because: {c.disabledReason}</p>}
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" tone="ghost" icon={c.disabled ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />} disabled={busy !== null}
                onClick={() => void act('toggle', () => studio.clip(c.id, { action: c.disabled ? 'enable' : 'disable' }))}>{c.disabled ? 'Use it again' : 'Do not use'}</Button>
              <Button size="sm" tone="ghost" icon={<RefreshCw className="size-3.5" />} disabled={busy !== null || waiting}
                onClick={() => void act('retag', () => studio.clip(c.id, { action: 'retag' }))}>Watch again</Button>
              <ConfirmButton size="sm" tone="ghost" label="Delete" confirmLabel="Delete this clip for good" confirmTone="danger" icon={<Trash2 className="size-3.5" />} onConfirm={() => studio.deleteClip(c.id)} />
            </div>
            <ErrorNote error={error} onClose={clear} />
          </div>
        )}
      </div>
    </li>
  )
}

export function Clips({ s }: { s: StudioStatus }) {
  const clips = s.clips ?? []
  const waiting = new Set((s.worker?.waiting ?? []).map((w) => w.clip).filter(Boolean))
  const uploading = (s.worker?.waiting ?? []).filter((w) => w.verb === 'ingest').length
  const n = s.needs
  return (
    <Panel title={<>Scenes <span className="num ml-1 font-normal text-ink-faint">{clips.length}</span></>}
      aside={<span className="hidden text-2xs text-ink-faint sm:inline">{n ? `${n.clips_free} ready to use now` : ''}{s.disk ? ` · ${s.disk.freeGB} GB free on the server` : ''}</span>}>
      <UploadZone kind="clips" accept="video/*,.mp4,.mov,.m4v,.mkv,.avi,.webm" label="Add scenes" hint="mp4 or mov, up to 2 GB each. Drop as many as you like: they go up one at a time and the AI watches each once." />
      {uploading > 0 && <p className="mt-2 text-2xs text-ink-faint">{uploading} scene{uploading > 1 ? 's are' : ' is'} being prepared on the server…</p>}
      {clips.length === 0 ? <p className="mt-3 text-[12px] text-ink-faint">No scenes yet.</p>
        : <ul className="mt-3 grid grid-cols-2 items-start gap-3 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">{clips.map((c) => <Tile key={c.id} c={c} waiting={waiting.has(c.id)} />)}</ul>}
    </Panel>
  )
}
