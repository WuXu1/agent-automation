import { RotateCw } from 'lucide-react'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useMode } from '@/telemetry/mode'
import type { FeedState } from '@/telemetry/feed'
import { Chip } from './Chip'

/** Where a view's numbers come from and how old they are; the error stays visible while older data is shown. */
export function FeedStatus({ feed, source }: { feed: FeedState<unknown>; source: string }) {
  useNow(10_000)
  const mode = useMode((s) => s.mode)
  if (mode === 'demo') return <Chip signal="warn">Demo data</Chip>
  if (feed.status === 'loading' || feed.status === 'idle') return <Chip signal="memory" breathe>Reading {source}…</Chip>
  if (feed.error) {
    return (
      <span className="inline-flex items-center gap-2">
        <Chip signal="alarm">{feed.data ? 'Last read failed' : 'Cannot read'}</Chip>
        <span className="hidden max-w-[320px] truncate text-2xs text-ink-faint sm:inline" title={feed.error}>{feed.error}</span>
      </span>
    )
  }
  return (
    <Chip signal="ok" breathe>
      Live <span className="text-ink-faint">· {feed.at ? ago(feed.at) : ''}</span>
    </Chip>
  )
}

/** Shown in place of a view when live mode has nothing at all to show. */
export function FeedError({ error, onDemo }: { error: string | null; onDemo: () => void }) {
  return (
    <div className="glass mx-auto mt-12 max-w-md p-5">
      <h2 className="text-[15px] font-semibold">This view could not be read</h2>
      <p className="mt-1.5 text-[13px] text-ink-dim">{error ?? 'No answer from the bridge.'} It tries again on its own every few seconds.</p>
      <button type="button" onClick={onDemo} className="press mt-4 inline-flex h-9 items-center gap-1.5 rounded-lg border border-line-strong px-3.5 text-[13px] hover:bg-white/[0.06]">
        <RotateCw className="size-3.5" /> Show demo data instead
      </button>
    </div>
  )
}
