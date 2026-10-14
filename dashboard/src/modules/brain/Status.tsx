import { ListChecks, Plus, RotateCw } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { useMode } from '@/telemetry/mode'
import { Button } from '@/ui/Button'
import { Chip } from '@/ui/Chip'
import { useReview } from '@/telemetry/review'
import { useBrainUi } from './store'

/** Counts, freshness and the one add button. */
export function Status({ className }: { className?: string }) {
  const status = useBrain((s) => s.status)
  const graph = useBrain((s) => s.graph)
  const loadedAt = useBrain((s) => s.loadedAt)
  const error = useBrain((s) => s.error)
  const mode = useMode((s) => s.mode)
  const compose = useBrainUi((s) => s.compose)
  const sorting = useBrain((s) => s.sorting)
  const unsorted = useBrain((s) => s.unsorted)
  const review = useReview((s) => s.view)
  const openReview = useReview((s) => s.setOpen)
  useNow(20_000)

  return (
    <div className={cn('glass flex items-center gap-3 py-1.5 pr-1.5 pl-3', className)}>
      {status === 'loading' ? (
        <Chip signal="memory" breathe>Charting memories…</Chip>
      ) : error && status === 'ready' ? (
        <Chip signal="warn">Last refresh failed</Chip>
      ) : (
        <Chip signal={mode === 'live' ? 'ok' : 'warn'} breathe={mode === 'live'}>{mode === 'live' ? 'Mem0 live' : 'Demo data'}</Chip>
      )}
      {sorting && <Chip signal="memory" breathe>AI sorting {unsorted > 0 ? `${unsorted} new` : 'new'} notes</Chip>}
      <span className="num hidden text-[12px] text-ink-dim sm:inline">
        {graph.nodes.length} notes · {graph.edges.length} links
        {loadedAt && <span className="text-ink-faint"> · {mode === 'live' ? `read ${ago(loadedAt)}` : 'generated'}</span>}
      </span>
      <Button size="sm" tone="ghost" icon={<ListChecks className="size-3.5" />} onClick={() => openReview(true)}
        title="The weekly check-up: duplicates, contradictions and out-of-date notes, for you to approve">
        {review?.running ? 'Checking…' : review?.items.length ? `Review · ${review.items.length}` : 'Check-up'}
      </Button>
      <Button tone="memory" size="sm" icon={<Plus className="size-3.5" />} onClick={() => compose(true)}>Add</Button>
    </div>
  )
}

/** Live mode could not read Mem0: say why and offer the two ways on. */
export function LoadError() {
  const error = useBrain((s) => s.error)
  const load = useBrain((s) => s.load)
  const setMode = useMode((s) => s.setMode)
  return (
    <div className="pointer-events-auto glass absolute top-1/2 left-1/2 w-[min(420px,calc(100%-32px))] -translate-x-1/2 -translate-y-1/2 p-5">
      <h2 className="text-[15px] font-semibold">Mem0 could not be read</h2>
      <p className="mt-1.5 text-[13px] text-ink-dim">{error ?? 'No answer from the bridge.'} The memories themselves are untouched.</p>
      <div className="mt-4 flex gap-2">
        <Button tone="memory" icon={<RotateCw className="size-3.5" />} onClick={() => void load('live')}>Try again</Button>
        <Button onClick={() => setMode('demo')}>Show demo data</Button>
      </div>
    </div>
  )
}
