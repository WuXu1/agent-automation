import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { studio, type Line, type StudioStatus } from '@/telemetry/studio'
import { Button } from '@/ui/Button'
import { Chip } from '@/ui/Chip'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { Panel } from '@/ui/Panel'
import { ErrorNote, useAct } from './shared'

function Row({ l }: { l: Line }) {
  const { busy, error, act, clear } = useAct()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(l.text)
  const set = (body: Record<string, unknown>, key: string) => act(key, () => studio.line(l.id, body), 'confirm')
  return (
    <li className="rounded-lg border border-line bg-white/[0.02] px-3 py-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex gap-1.5">
              <input value={text} onChange={(e) => setText(e.target.value)} maxLength={160} className="min-w-0 flex-1 rounded-md border border-line-strong bg-void px-2 py-1 text-[13px]" aria-label="Edit the line" />
              <Button size="sm" tone="memory" disabled={busy !== null || text.trim().length < 3} onClick={() => void set({ text }, 'text').then(() => setEditing(false))}>Save</Button>
              <Button size="sm" tone="ghost" onClick={() => { setText(l.text); setEditing(false) }}>Cancel</Button>
            </div>
          ) : <p className="text-[13px] leading-snug">{l.text}</p>}
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-ink-faint">
            {l.kind === 'cta' && <Chip signal="agent">book line</Chip>}
            <span>{l.source === 'owner' ? 'yours' : 'written by the Overlay Copywriter'}</span>
            {l.last_used && <span>last used {new Date(l.last_used).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</span>}
            {l.note && <span>{l.note}</span>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {l.status === 'suggested' && <>
            <Button size="sm" tone="memory" icon={<Check className="size-3.5" />} disabled={busy !== null} onClick={() => void set({ status: 'approved' }, 'ok')}>Keep</Button>
            <Button size="sm" tone="ghost" icon={<X className="size-3.5" />} disabled={busy !== null} onClick={() => void set({ status: 'retired' }, 'no')}>No</Button>
          </>}
          {l.status === 'approved' && !editing && <>
            <Button size="sm" tone="ghost" icon={<Pencil className="size-3.5" />} aria-label="Edit" onClick={() => setEditing(true)} />
            <Button size="sm" tone="ghost" disabled={busy !== null} onClick={() => void set({ kind: l.kind === 'cta' ? 'line' : 'cta' }, 'kind')} title="Book lines are the soft Sedona Method mentions">{l.kind === 'cta' ? 'Make plain' : 'Make book line'}</Button>
            <Button size="sm" tone="ghost" disabled={busy !== null} onClick={() => void set({ status: 'retired' }, 'ret')}>Retire</Button>
          </>}
          {l.status === 'retired' && <Button size="sm" tone="ghost" disabled={busy !== null} onClick={() => void set({ status: 'approved' }, 'back')}>Bring back</Button>}
          <ConfirmButton size="sm" tone="ghost" label="" ariaLabel="Delete the line" confirmLabel="Delete" confirmTone="danger" icon={<Trash2 className="size-3.5" />} onConfirm={() => studio.deleteLine(l.id)} />
        </div>
      </div>
      <ErrorNote error={error} onClose={clear} />
    </li>
  )
}

export function Lines({ s }: { s: StudioStatus }) {
  const lines = s.lines ?? []
  const { busy, error, act, clear } = useAct()
  const [box, setBox] = useState('')
  const [kind, setKind] = useState<'line' | 'cta'>('line')
  const [skipped, setSkipped] = useState<{ text: string; why: string }[]>([])
  const rows = box.split('\n').map((t) => t.trim()).filter(Boolean)
  const add = () => act('add', async () => {
    const out = await studio.addLines(rows, kind)
    setSkipped(out?.skipped ?? [])
    setBox('')
  }, 'confirm')
  const group = (title: string, hint: string, status: Line['status'], tone?: string) => {
    const list = lines.filter((l) => l.status === status)
    if (list.length === 0) return null
    return (
      <Panel title={<>{title} <span className={cn('num ml-1 font-normal', tone ?? 'text-ink-faint')}>{list.length}</span></>} aside={<span className="hidden text-2xs text-ink-faint sm:inline">{hint}</span>}>
        <ul className="space-y-1.5">{list.map((l) => <Row key={l.id} l={l} />)}</ul>
      </Panel>
    )
  }
  return (
    <div className="space-y-4">
      <Panel title="Add overlay lines" aside={<span className="text-2xs text-ink-faint">one per row; the words that sit over the scene</span>}>
        <textarea rows={4} value={box} onChange={(e) => setBox(e.target.value)} placeholder={'could you let go of this feeling holding you back\nwhat you want wants you'}
          className="w-full resize-y rounded-lg border border-line-strong bg-void px-3 py-2 text-[13px]" aria-label="New overlay lines, one per row" />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Button tone="memory" size="sm" icon={<Plus className="size-3.5" />} disabled={busy !== null || rows.length === 0} onClick={() => void add()}>Add {rows.length > 1 ? `${rows.length} lines` : 'line'}</Button>
          <label className="flex items-center gap-1.5 text-[12px] text-ink-dim"><input type="checkbox" checked={kind === 'cta'} onChange={(e) => setKind(e.target.checked ? 'cta' : 'line')} />These are book lines (a soft mention of The Sedona Method)</label>
        </div>
        {skipped.length > 0 && <p className="mt-2 text-2xs text-[#fcd34d]">Not added: {skipped.map((x) => `“${x.text}” (${x.why})`).join('; ')}</p>}
        <ErrorNote error={error} onClose={clear} />
        <p className="mt-2 text-2xs text-ink-faint">Lines you add are approved straight away. Lines the Overlay Copywriter writes wait below for your yes. A line rests for {s.settings?.line_rest_days ?? 60} days after it is used.</p>
      </Panel>
      {group('Suggested by the Overlay Copywriter', 'keep the ones that sound like you', 'suggested', 'text-[#fcd34d]')}
      {group('Your lines', 'the ones the planner may use', 'approved', 'text-ok')}
      {group('Retired', 'never used again unless you bring them back', 'retired')}
      {lines.length === 0 && <p className="text-[13px] text-ink-faint">No lines yet.</p>}
    </div>
  )
}
