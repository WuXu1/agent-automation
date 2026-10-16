import { Check, Film, Upload, X } from 'lucide-react'
import { useRef, useState, type DragEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { uploadStudioFile } from '@/telemetry/studio'
import { useMode } from '@/telemetry/mode'
import { Button } from '@/ui/Button'

/** Runs a write, keeps the reason it failed in plain words next to the control, and tells whether one is running. */
export function useAct() {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const act = async (key: string, fn: () => Promise<unknown>, tone: 'confirm' | 'none' = 'none') => {
    setBusy(key)
    setError(null)
    try { await fn(); if (tone === 'confirm') play('confirm') } catch (e) { setError(e instanceof Error ? e.message : 'That did not work') } finally { setBusy(null) }
  }
  return { busy, error, act, clear: () => setError(null) }
}

export function ErrorNote({ error, onClose }: { error: string | null; onClose?: () => void }) {
  if (!error) return null
  return (
    <p role="alert" className="mt-2 flex items-start gap-2 rounded-lg border border-alarm/40 bg-alarm/10 px-2.5 py-1.5 text-[12px] text-[#fca5a5]">
      <span className="min-w-0 flex-1">{error}</span>
      {onClose && <button type="button" aria-label="Dismiss" className="shrink-0 hover:text-ink" onClick={onClose}><X className="size-3.5" /></button>}
    </p>
  )
}

/** A picture from the server (a still or a clip's first frame); a gradient from the seed stands in when there is none (demo, or not made yet). */
export function Still({ src, seed, className, children }: { src?: string | null; seed: string; className?: string; children?: ReactNode }) {
  const live = useMode((s) => s.mode) === 'live'
  const [failed, setFailed] = useState(false)
  let h = 0
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) % 360
  return (
    <div className={cn('relative overflow-hidden bg-void', className)} style={{ backgroundImage: `linear-gradient(160deg, hsl(${h} 28% 22%), hsl(${(h + 40) % 360} 24% 10%))` }}>
      {live && src && !failed ? <img src={src} alt="" loading="lazy" className="absolute inset-0 size-full object-cover" onError={() => setFailed(true)} />
        : <Film aria-hidden className="absolute top-2 left-2 size-4 text-white/25" />}
      {children}
    </div>
  )
}

interface Job { id: number; name: string; sent: number; total: number; error: string | null; done: boolean; ctl: AbortController }

/** Drop files here or choose them; each goes up on its own with a progress bar and, if refused, the reason. */
export function UploadZone({ kind, accept, label, hint, multiple = true }: { kind: 'clips' | 'fonts'; accept: string; label: string; hint: string; multiple?: boolean }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const next = useRef(1)

  const start = async (files: File[]) => {
    for (const file of files) {
      const job: Job = { id: next.current++, name: file.name, sent: 0, total: file.size, error: null, done: false, ctl: new AbortController() }
      setJobs((j) => [...j, job])
      const patch = (p: Partial<Job>) => setJobs((j) => j.map((x) => (x.id === job.id ? { ...x, ...p } : x)))
      try {
        await uploadStudioFile(kind, file, (sent, total) => patch({ sent, total }), job.ctl.signal)
        patch({ done: true })
        play('confirm')
        window.setTimeout(() => setJobs((j) => j.filter((x) => x.id !== job.id)), 3000)
      } catch (err) {
        patch({ error: err instanceof DOMException && err.name === 'AbortError' ? 'Cancelled' : err instanceof Error ? err.message : 'The upload failed' })
      }
    }
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); const f = [...e.dataTransfer.files]; if (f.length) void start(multiple ? f : f.slice(0, 1)) }

  return (
    <div>
      <div onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={onDrop}
        className={cn('flex flex-wrap items-center gap-3 rounded-xl border border-dashed px-3 py-2.5 text-[12px] transition-colors', over ? 'border-memory/70 bg-memory/[0.07]' : 'border-line-strong bg-white/[0.02]')}>
        <Button size="sm" tone="memory" icon={<Upload className="size-3.5" />} onClick={() => input.current?.click()}>{label}</Button>
        <span className="text-ink-faint">{hint}</span>
        <input ref={input} type="file" accept={accept} multiple={multiple} hidden onChange={(e) => { const f = [...(e.target.files ?? [])]; e.target.value = ''; if (f.length) void start(f) }} />
      </div>
      {jobs.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {jobs.map((j) => (
            <li key={j.id} className="rounded-lg border border-line bg-white/[0.02] px-3 py-1.5 text-[12px]">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate">{j.name}</span>
                {j.error ? <span className="text-[#fca5a5]">{j.error}</span> : j.done ? <span className="inline-flex items-center gap-1 text-ok"><Check className="size-3.5" />sent; being watched next</span>
                  : <span className="num text-ink-faint">{Math.round((j.sent / Math.max(j.total, 1)) * 100)}%</span>}
                <button type="button" aria-label={j.error || j.done ? 'Dismiss' : 'Cancel upload'} className="text-ink-faint hover:text-ink"
                  onClick={() => (j.error || j.done ? setJobs((x) => x.filter((y) => y.id !== j.id)) : j.ctl.abort())}><X className="size-3.5" /></button>
              </div>
              {!j.error && !j.done && <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/[0.08]"><div className="h-full rounded-full bg-memory transition-[width] duration-200" style={{ width: `${(j.sent / Math.max(j.total, 1)) * 100}%` }} /></div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function dayLabel(iso: string | null): string {
  if (!iso) return 'no date'
  const d = new Date(`${iso}T12:00:00`)
  const t = new Date(); t.setHours(12, 0, 0, 0)
  const diff = Math.round((d.getTime() - t.getTime()) / 86_400_000)
  if (diff === 0) return 'today'
  if (diff === 1) return 'tomorrow'
  if (diff === -1) return 'yesterday'
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}
