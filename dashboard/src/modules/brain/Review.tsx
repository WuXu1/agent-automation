import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, CalendarX, Check, FolderInput, Merge, PenLine, RefreshCw, Tag, X } from 'lucide-react'
import { useEffect } from 'react'
import { cn } from '@/lib/cn'
import { drawer, fade } from '@/lib/motion'
import { play } from '@/lib/sound'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { authorLabel } from '@/telemetry/agents'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { useMode } from '@/telemetry/mode'
import { useReview, type ReviewItem, type ReviewKind } from '@/telemetry/review'
import { Button, IconButton } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { useBrainUi } from './store'

const KIND: Record<ReviewKind, { label: string; icon: React.ReactNode; yes: string }> = {
  merge: { label: 'Merge into one note', icon: <Merge className="size-3.5" />, yes: 'Merge them' },
  update: { label: 'Rewrite', icon: <PenLine className="size-3.5" />, yes: 'Use the new text' },
  expire: { label: 'Out of date', icon: <CalendarX className="size-3.5" />, yes: 'Delete it' },
  'section-merge': { label: 'Fold a section in', icon: <FolderInput className="size-3.5" />, yes: 'Fold it in' },
  'section-rename': { label: 'Rename a section', icon: <Tag className="size-3.5" />, yes: 'Rename it' },
}

/** Load the check-up once per mode, then every minute, and every few seconds while the AI is reading. */
export function useReviewSync() {
  const mode = useMode((s) => s.mode)
  const load = useReview((s) => s.load)
  const running = useReview((s) => s.view?.running ?? false)
  const notes = useBrain((s) => s.memories.length)          // demo suggestions are made from the notes once they are in
  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), running ? 4000 : 60_000)
    return () => window.clearInterval(id)
  }, [mode, running, notes, load])
}

function Note({ text, by, at, gone }: { text: string; by: string; at: string; gone?: boolean }) {
  return (
    <div className={cn('rounded-lg border border-line px-2.5 py-2', gone && 'opacity-70')}>
      <p className={cn('text-[12px] leading-snug text-ink-dim', gone && 'line-through decoration-ink-faint/60')}>{text}</p>
      <p className="mt-1 text-[10px] text-ink-faint">{authorLabel(by)} · {at}</p>
    </div>
  )
}

function Item({ item }: { item: ReviewItem }) {
  const apply = useReview((s) => s.apply)
  const dismiss = useReview((s) => s.dismiss)
  const select = useBrainUi((s) => s.select)
  const k = KIND[item.kind]
  return (
    <li className="rounded-xl border border-line bg-white/[0.015] p-3">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-memory">{k.icon}{k.label}</div>
      <p className="mt-1 text-[13px] text-ink">{item.why}</p>
      <div className="mt-2.5 space-y-1.5">
        {item.before?.map((n) => <Note key={n.id} text={n.text} by={n.by} at={n.at} gone />)}
        {item.text && (
          <>
            <div className="flex items-center gap-1 pl-1 text-[10px] text-ink-faint"><ArrowRight className="size-3" />becomes</div>
            <div className="rounded-lg border border-memory/40 bg-memory/[0.05] px-2.5 py-2 text-[12px] leading-snug text-ink">{item.text}</div>
          </>
        )}
        {item.kind === 'section-merge' && (
          <p className="text-[12px] text-ink-dim"><span className="text-ink">{item.label}</span> ({item.notes} note{item.notes === 1 ? '' : 's'}) moves into <span className="text-ink">{item.intoLabel}</span>; the notes stay as they are.</p>
        )}
        {item.kind === 'section-rename' && (
          <p className="text-[12px] text-ink-dim"><span className="text-ink">{item.label}</span> becomes <span className="text-ink">{item.newLabel}</span>{item.blurb ? ` · ${item.blurb}` : ''}</p>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <ConfirmButton label="Apply" confirmLabel={k.yes} tone={item.kind === 'expire' ? 'danger' : 'memory'} size="sm" icon={<Check className="size-3.5" />}
          onConfirm={async () => { await apply(item); play('confirm') }} />
        <Button size="sm" tone="ghost" onClick={() => { void dismiss(item); play('tick') }}>No, leave it</Button>
        {item.ids?.[0] && <button type="button" onClick={() => select(item.ids![0]!)} className="ml-auto text-2xs text-ink-faint hover:text-ink">open the note</button>}
      </div>
    </li>
  )
}

function Panel() {
  const view = useReview((s) => s.view)
  const busy = useReview((s) => s.busy)
  const error = useReview((s) => s.error)
  const check = useReview((s) => s.check)
  const setOpen = useReview((s) => s.setOpen)
  const mode = useMode((s) => s.mode)
  const now = useNow(30_000).getTime()
  const running = view?.running || busy
  const items = view?.items ?? []
  return (
    <>
      <div className="flex items-center gap-2 px-5 pt-4">
        <h2 className="flex-1 text-[13px] font-semibold">Weekly check-up</h2>
        <IconButton label="Close" onClick={() => setOpen(false)}><X className="size-4" /></IconButton>
      </div>
      <div className="flex items-center gap-2 px-5 pt-1 pb-3 text-2xs text-ink-faint">
        <span className="flex-1">
          {running ? 'The AI is reading every note…' : view?.at ? `Checked ${ago(view.at)}${view.nextAt ? `; next by itself ${view.nextAt > now ? `in ${Math.ceil((view.nextAt - now) / 86_400_000)} days` : 'when you next open this'}` : ''}` : 'Not checked yet'}
        </span>
        <Button size="sm" tone="ghost" icon={<RefreshCw className={cn('size-3.5', running && 'animate-spin')} />} disabled={running} onClick={() => void check()}>
          {running ? 'Checking' : 'Check now'}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">
        {error && <p role="alert" className="mb-2 text-[12px] text-[#fca5a5]">{error}</p>}
        {!running && items.length === 0 && (
          <div className="rounded-xl border border-line p-4 text-center">
            <p className="text-[13px] text-ink">Nothing to fix.</p>
            <p className="mt-1 text-2xs text-ink-faint">No duplicates, contradictions or out-of-date notes found{view?.at ? ' in the last check' : ''}.</p>
          </div>
        )}
        <ul className="space-y-2.5">{items.map((i) => <Item key={i.id} item={i} />)}</ul>
      </div>
      <footer className="border-t border-line px-5 py-3 text-2xs text-ink-faint">
        {mode === 'live'
          ? 'Nothing changes until you press Apply. Pinned notes are never suggested. The old text of any note you change is kept on the VM (hermes-dash/archive), so every change can be undone.'
          : 'Demo: suggestions are made from the demo notes and changes stay in this tab.'}
      </footer>
    </>
  )
}

/** The check-up drawer: same place as the note inspector, shown when nothing is selected. */
export function Review() {
  const open = useReview((s) => s.open)
  const busyElsewhere = useBrainUi((s) => Boolean(s.selectedId) || s.composing)
  const reduced = useReducedMotion()
  const narrow = typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches
  const hidden = reduced ? { opacity: 0 } : { opacity: 1, transform: narrow ? 'translateY(100%)' : 'translateX(calc(100% + 24px))' }
  return (
    <AnimatePresence>
      {open && !busyElsewhere && (
        <motion.aside key="review" aria-label="Weekly check-up" initial={hidden} animate={{ opacity: 1, transform: 'translate(0px, 0px)' }} exit={hidden}
          transition={reduced ? fade : drawer}
          className={cn('pointer-events-auto glass absolute z-30 flex flex-col overflow-hidden bg-glass-strong shadow-[0_24px_64px_-16px_rgb(0_0_0/0.75)]',
            'inset-x-2 bottom-2 max-h-[72%] md:inset-x-auto md:top-4 md:right-4 md:bottom-4 md:max-h-none md:w-[420px]')}>
          <Panel />
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
