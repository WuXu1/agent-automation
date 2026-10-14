import { Loader2, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { useMode } from '@/telemetry/mode'
import { Kbd } from '@/ui/Kbd'
import { useBrainUi } from './store'

/** Search by meaning. Live: Mem0's vector search on the VM. Demo: word overlap, and it says so. */
export function SearchPanel({ className }: { className?: string }) {
  const mode = useMode((s) => s.mode)
  const search = useBrain((s) => s.search)
  const clear = useBrain((s) => s.clearSearch)
  const hits = useBrain((s) => s.hits)
  const searching = useBrain((s) => s.searching)
  const memories = useBrain((s) => s.memories)
  const graph = useBrain((s) => s.graph)
  const selectedId = useBrainUi((s) => s.selectedId)
  const select = useBrainUi((s) => s.select)
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)

  // "/" focuses search, as in most tools
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (e.key === '/' && !(t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable))) {
        e.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Live search waits for a pause in typing (each query embeds on the VM); demo answers at once.
  useEffect(() => {
    if (!text.trim()) { clear(); return }
    const id = window.setTimeout(() => void search(text), mode === 'live' ? 350 : 120)
    return () => window.clearTimeout(id)
  }, [text, mode, search, clear])

  const byId = new Map(memories.map((m) => [m.id, m]))

  return (
    <section className={cn('glass flex max-h-full min-h-0 flex-col overflow-hidden', className)} aria-label="Search memories">
      <form className="flex items-center gap-2 px-3" onSubmit={(e) => { e.preventDefault(); void search(text) }}>
        {searching ? <Loader2 className="size-4 shrink-0 animate-spin text-memory" /> : <Search className="size-4 shrink-0 text-ink-faint" />}
        <input
          ref={input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') { setText(''); input.current?.blur() } }}
          placeholder="Search memories by meaning…"
          aria-label="Search memories"
          className="h-11 min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none"
        />
        {text ? (
          <button type="button" onClick={() => setText('')} className="press grid size-7 place-items-center rounded-md text-ink-faint hover:text-ink" aria-label="Clear search">
            <X className="size-4" />
          </button>
        ) : <Kbd>/</Kbd>}
      </form>

      {hits !== null && (
        <div className="min-h-0 overflow-y-auto border-t border-line">
          <div className="flex items-center justify-between px-4 pt-2.5 pb-1 text-2xs text-ink-faint">
            <span>{hits.length ? `${hits.length} closest` : 'Nothing close enough'}</span>
            <span>{mode === 'live' ? 'Mem0 vector search' : 'Demo: word match'}</span>
          </div>
          <ol className="px-1.5 pb-1.5">
            {hits.map((h) => {
              const m = byId.get(h.id)
              if (!m) return null
              const c = graph.sectionById.get(graph.byId.get(h.id)?.cluster ?? 'rules')
              return (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => select(h.id)}
                    aria-current={selectedId === h.id}
                    aria-label={`${m.text} (match ${h.score.toFixed(2)})`}
                    className={cn('press flex w-full gap-3 rounded-lg px-2.5 py-2 text-left hover:bg-white/[0.05]', selectedId === h.id && 'bg-white/[0.06]')}
                  >
                    <span className="flex w-9 shrink-0 flex-col items-end gap-1 pt-0.5">
                      <span className="num text-[11px] text-memory">{h.score.toFixed(2)}</span>
                      <span className="h-0.5 w-full overflow-hidden rounded bg-white/10">
                        <span className="block h-full rounded bg-memory" style={{ width: `${Math.round(h.score * 100)}%` }} />
                      </span>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="line-clamp-2 text-[13px] leading-snug text-ink">{m.text}</span>
                      <span className="mt-0.5 block text-2xs" style={{ color: c?.color }}>{c?.label}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </section>
  )
}
