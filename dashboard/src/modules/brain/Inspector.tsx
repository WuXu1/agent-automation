import { AnimatePresence, motion } from 'motion/react'
import { Check, Pin, PinOff, Plus, Sparkles, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { drawer, fade } from '@/lib/motion'
import { play } from '@/lib/sound'
import { ago, stamp } from '@/lib/time'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { authorLabel } from '@/telemetry/agents'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { useMode } from '@/telemetry/mode'
import { classify } from '@/telemetry/clusters'
import { useSettings } from '@/telemetry/settings'
import { useReview } from '@/telemetry/review'
import { brainApi } from '@/telemetry/tools'
import type { Memory } from '@/telemetry/types'
import { Button, IconButton } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { useBrainUi } from './store'

const MAX_LEN = 600

function Meta({ label, children, mono }: { label: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className="shrink-0 text-2xs text-ink-faint">{label}</dt>
      <dd className={cn('min-w-0 truncate text-right text-[12px] text-ink-dim', mono && 'num')}>{children}</dd>
    </div>
  )
}

function SaveNote() {
  const mode = useMode((s) => s.mode)
  return (
    <p className="text-2xs text-ink-faint">
      {mode === 'live'
        ? 'Writes go straight to Mem0 on the VM and every agent sees them on its next turn. Last night’s backup can bring a note back.'
        : 'Demo data: changes stay in this tab and vanish on reload.'}
    </p>
  )
}

const CHANNEL: Record<string, string> = { telegram: 'Telegram', api: 'the API', cli: 'the terminal' }

/** Where a note came from, in words: who saved it, through which chat, and when it was first written. */
export function cameFrom(m: Memory): string {
  const channel = typeof m.metadata.channel === 'string' ? (CHANNEL[m.metadata.channel] ?? m.metadata.channel) : null
  const first = typeof m.metadata.originally_created === 'string' ? Date.parse(m.metadata.originally_created) : NaN
  if (m.author === 'import') {
    return `Imported from an earlier memory${Number.isNaN(first) ? '' : `; first saved ${stamp(first)}`}`
  }
  if (m.author === 'dashboard') return 'You, on the dashboard'
  if (m.author === 'claude-code' || m.author === 'claude-cloud') return `${authorLabel(m.author)} saved it from a coding session`
  return `${authorLabel(m.author)} saved it${channel ? ` from a ${channel} chat` : ' from a chat'}`
}

function Editor({ memory }: { memory: Memory }) {
  const update = useBrain((s) => s.update)
  const remove = useBrain((s) => s.remove)
  const graph = useBrain((s) => s.graph)
  const memories = useBrain((s) => s.memories)
  const select = useBrainUi((s) => s.select)
  const [text, setText] = useState(memory.text)

  const node = graph.byId.get(memory.id)
  const cluster = graph.sectionById.get(node?.cluster ?? 'rules')
  const neighbours = graph.neighbours.get(memory.id) ?? []
  const byId = new Map(memories.map((m) => [m.id, m]))
  const dirty = text.trim() !== memory.text.trim()
  const extra = Object.entries(memory.metadata).filter(([k]) => !['source', 'category', 'channel', 'originally_created'].includes(k)).slice(0, 4)
  const pinned = useReview((s) => s.view?.pins.includes(memory.id) ?? false)
  const pin = useReview((s) => s.pin)

  return (
    <>
      <div className="flex items-center gap-2 px-5 pt-4">
        <span className="size-2 rounded-full" style={{ background: cluster?.color }} aria-hidden />
        <span className="flex-1 text-[12px] font-medium" style={{ color: cluster?.color }}>{cluster?.label}</span>
        <button type="button" aria-pressed={pinned} onClick={() => { void pin(memory.id, !pinned); play('tick') }}
          title={pinned ? 'Always true: the weekly check-up never suggests changing it. Click to unpin.' : 'Pin as always true: the weekly check-up will never suggest changing it'}
          className={cn('press flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]', pinned ? 'border-memory/50 bg-memory/10 text-memory' : 'border-line text-ink-faint hover:text-ink')}>
          {pinned ? <Pin className="size-3" /> : <PinOff className="size-3" />}{pinned ? 'Always true' : 'Pin'}
        </button>
        <IconButton label="Close" onClick={() => select(null)}><X className="size-4" /></IconButton>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">
        <label className="sr-only" htmlFor="memory-text">Memory text</label>
        <textarea
          id="memory-text"
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_LEN))}
          rows={4}
          className="mt-2 w-full resize-none rounded-lg border border-transparent bg-transparent p-0 text-[17px] leading-relaxed tracking-[-0.01em] text-ink outline-none [field-sizing:content] hover:border-line focus:border-line-strong focus:bg-white/[0.02] focus:p-2"
        />
        <div className="flex h-5 items-center justify-between text-2xs text-ink-faint">
          <span>{dirty ? 'Edited, not saved' : 'Click the text to edit it'}</span>
          <span className="num">{text.length}/{MAX_LEN}</span>
        </div>

        <dl className="mt-4 divide-y divide-line border-y border-line">
          <div className="py-2 text-[12px] text-ink-dim"><span className="mb-0.5 block text-2xs text-ink-faint">Where it came from</span>{cameFrom(memory)}</div>
          {memory.category && <Meta label="Category">{memory.category}</Meta>}
          <Meta label="Created">{stamp(memory.createdAt)} · {ago(memory.createdAt)}</Meta>
          {memory.updatedAt && <Meta label="Updated">{stamp(memory.updatedAt)} · {ago(memory.updatedAt)}</Meta>}
          {extra.map(([k, v]) => <Meta key={k} label={k} mono>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</Meta>)}
          <Meta label="Id" mono>{memory.id}</Meta>
        </dl>

        <h3 className="mt-5 mb-1.5 flex items-baseline justify-between text-[12px] font-semibold text-ink">Related notes<span className="text-2xs font-normal text-ink-faint">words in common</span></h3>
        {neighbours.length === 0 ? (
          <p className="text-[12px] text-ink-faint">No other note shares enough words with this one.</p>
        ) : (
          <ul className="-mx-2">
            {neighbours.map((n) => {
              const m = byId.get(n.id)
              if (!m) return null
              return (
                <li key={n.id}>
                  <button type="button" onClick={() => select(n.id)} className="press flex w-full items-start gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-white/[0.05]">
                    <span className="num mt-0.5 w-8 shrink-0 text-right text-[11px] text-memory">{n.weight.toFixed(2)}</span>
                    <span className="line-clamp-2 text-[12px] leading-snug text-ink-dim">{m.text}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <footer className="space-y-3 border-t border-line px-5 py-4">
        <div className="flex flex-wrap items-start gap-2">
          <ConfirmButton
            label="Save change"
            confirmLabel="Replace this note"
            tone="memory"
            icon={<Check className="size-3.5" />}
            disabled={!dirty || !text.trim()}
            onConfirm={async () => { await update(memory.id, text.trim()); play('confirm') }}
          />
          <span className="flex-1" />
          <ConfirmButton
            label="Delete"
            confirmLabel="Delete for good"
            tone="danger"
            icon={<Trash2 className="size-3.5" />}
            onConfirm={async () => { await remove(memory.id); play('warn'); select(null) }}
          />
        </div>
        <SaveNote />
      </footer>
    </>
  )
}

const field = 'w-full rounded-lg border border-line bg-white/[0.02] text-ink outline-none focus:border-line-strong'

/**
 * A new note. With "Tidy" on (Settings sets the default), the dashboard's model rewrites it as one clear note and picks its
 * section, or names a new one; you see both and can change them before it is saved. With it off, the note is saved word
 * for word and the AI only sorts it into a section afterwards.
 */
function Composer() {
  const add = useBrain((s) => s.add)
  const sections = useBrain((s) => s.sections)
  const compose = useBrainUi((s) => s.compose)
  const select = useBrainUi((s) => s.select)
  const tidyDefault = useSettings((s) => s.settings?.tidyMemories ?? true)
  const [text, setText] = useState('')
  const [tidy, setTidy] = useState(tidyDefault)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<{ text: string; section: string; newLabel: string } | null>(null)

  const run = async () => {
    setBusy(true); setError(null)
    try {
      const out = await brainApi.tidy(text.trim(), (t) => classify({ text: t, category: null }))
      setDraft({ text: out.text, section: out.section ?? (out.new ? '__new' : ''), newLabel: out.new?.label ?? '' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The AI could not tidy it; you can still save it as typed')
    } finally { setBusy(false) }
  }
  const save = async (body: string, section: string, newLabel: string) => {
    const place = section === '__new' ? { newSection: newLabel.trim() } : section ? { section } : {}
    const m = await add(body.trim(), place)
    play('confirm')
    select(m.id)
  }
  const pick = (value: string, onChange: (v: string) => void, newLabel?: string) => (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Section" className={cn(field, 'px-2.5 py-2 text-[13px]')}>
      <option value="">Let the AI sort it</option>
      {sections.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
      <option value="__new">{newLabel ? `New section: ${newLabel}` : 'A new section…'}</option>
    </select>
  )

  return (
    <>
      <div className="flex items-center gap-2 px-5 pt-4">
        <Plus className="size-4 text-memory" />
        <h2 className="flex-1 text-[13px] font-semibold">New memory</h2>
        <IconButton label="Close" onClick={() => compose(false)}><X className="size-4" /></IconButton>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pt-3 pb-4">
        {!draft ? (
          <>
            <label className="sr-only" htmlFor="new-memory">New memory</label>
            <textarea id="new-memory" ref={(el) => { el?.focus() }} value={text} onChange={(e) => setText(e.target.value.slice(0, MAX_LEN))} rows={5}
              placeholder="Anything worth remembering, in your own words. For example: i like studying before 11 and hate evening labs"
              className={cn(field, 'resize-none p-3 text-[15px] leading-relaxed')} />
            <label className="flex items-start gap-2 text-[12px] text-ink-dim">
              <input type="checkbox" aria-label="Tidy it with AI" className="mt-0.5" checked={tidy} onChange={(e) => setTidy(e.target.checked)} />
              <span><span className="inline-flex items-center gap-1 text-ink"><Sparkles className="size-3.5 text-[#f0abfc]" />Tidy it with AI</span><br />
                <span className="text-2xs text-ink-faint">One short note an agent can read at a glance, and the section it fits (a new one if none does). You see it before it is saved.</span></span>
            </label>
            {error && <p role="alert" className="text-[12px] text-[#fca5a5]">{error}</p>}
          </>
        ) : (
          <>
            <div className="text-2xs text-ink-faint">You wrote: <span className="text-ink-dim">{text}</span></div>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium">Saved as</span>
              <textarea value={draft.text} onChange={(e) => setDraft({ ...draft, text: e.target.value.slice(0, MAX_LEN) })} rows={4}
                className={cn(field, 'resize-none p-3 text-[14px] leading-relaxed')} />
            </label>
            <div>
              <span className="mb-1 block text-[12px] font-medium">Section</span>
              {pick(draft.section, (v) => setDraft({ ...draft, section: v }), draft.newLabel)}
              {draft.section === '__new' && (
                <input value={draft.newLabel} onChange={(e) => setDraft({ ...draft, newLabel: e.target.value.slice(0, 32) })} placeholder="Name of the new section"
                  aria-label="New section name" className={cn(field, 'mt-1.5 px-3 py-2 text-[13px]')} />
              )}
            </div>
            <button type="button" onClick={() => setDraft(null)} className="text-2xs text-memory hover:underline">Back to what I wrote</button>
          </>
        )}
      </div>
      <footer className="space-y-3 border-t border-line px-5 py-4">
        {!draft && tidy ? (
          <Button tone="memory" icon={busy ? undefined : <Sparkles className="size-3.5" />} disabled={!text.trim() || busy} onClick={run}>
            {busy ? 'Tidying…' : 'Tidy and sort'}
          </Button>
        ) : (
          <ConfirmButton label="Add memory" confirmLabel="Add it to Mem0" tone="memory" icon={<Plus className="size-3.5" />}
            disabled={draft ? !draft.text.trim() || (draft.section === '__new' && !draft.newLabel.trim()) : !text.trim()}
            onConfirm={() => (draft ? save(draft.text, draft.section, draft.newLabel) : save(text, '', ''))} />
        )}
        {!draft && !tidy && <p className="text-2xs text-ink-faint">Saved word for word; the AI then sorts it into a section.</p>}
        <SaveNote />
      </footer>
    </>
  )
}

/** The frosted drawer: slides in from the right on a laptop, up from the bottom on a phone. */
export function Inspector() {
  const selectedId = useBrainUi((s) => s.selectedId)
  const composing = useBrainUi((s) => s.composing)
  const memory = useBrain((s) => (selectedId ? s.memories.find((m) => m.id === selectedId) : undefined))
  const reduced = useReducedMotion()
  const open = Boolean(memory) || composing
  const narrow = typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches
  const hidden = reduced ? { opacity: 0 } : { opacity: 1, transform: narrow ? 'translateY(100%)' : 'translateX(calc(100% + 24px))' }

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          key="inspector"
          aria-label={composing ? 'New memory' : 'Memory inspector'}
          initial={hidden}
          animate={{ opacity: 1, transform: 'translate(0px, 0px)' }}
          exit={hidden}
          transition={reduced ? fade : drawer}
          className={cn(
            'pointer-events-auto glass absolute z-30 flex flex-col overflow-hidden bg-glass-strong shadow-[0_24px_64px_-16px_rgb(0_0_0/0.75)]',
            'inset-x-2 bottom-2 max-h-[72%] md:inset-x-auto md:top-4 md:right-4 md:bottom-4 md:max-h-none md:w-[400px]',
          )}
        >
          {composing ? <Composer /> : memory ? <Editor key={`${memory.id}:${memory.updatedAt ?? 0}`} memory={memory} /> : null}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
