import { LoaderCircle, Sparkles, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { enhance, type EnhanceField } from '@/telemetry/tools'

/**
 * A text box with a small sparkles button in its bottom-right corner: it rewrites what you typed (keeps your facts, tidies
 * the wording) and puts the result in the box, with an Undo until you type again. Nothing is saved until you save the form.
 */
export function EnhanceArea({ value, onChange, field, name, about, className, ...rest }: {
  value: string
  onChange: (v: string) => void
  field: EnhanceField
  name?: string
  about?: string
} & Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange'>) {
  const [busy, setBusy] = useState(false)
  const [before, setBefore] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const out = await enhance(field, value, name, about)
      setBefore(value)
      onChange(out)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div>
      <div className="relative">
        <textarea {...rest} value={value} disabled={busy || rest.disabled} className={cn(className, 'pb-9')}
          onChange={(e) => { setBefore(null); onChange(e.target.value) }} />
        <div className="absolute right-2 bottom-2 flex items-center gap-1">
          {before !== null && !busy && (
            <button type="button" onClick={() => { onChange(before); setBefore(null) }} title="Put back what you had"
              className="press inline-flex h-7 items-center gap-1 rounded-md px-2 text-2xs text-ink-faint hover:bg-white/[0.06] hover:text-ink">
              <Undo2 className="size-3" />Undo
            </button>
          )}
          <button type="button" onClick={run} disabled={busy || !value.trim()}
            aria-label="Improve this with AI" title={value.trim() ? 'Improve what you wrote with AI (DeepSeek, a fraction of a penny)' : 'Type something first'}
            className="press grid size-7 place-items-center rounded-md border border-agent/30 bg-agent/10 text-[#f0abfc] hover:border-agent/60 hover:bg-agent/20 disabled:opacity-40">
            {busy ? <LoaderCircle className="size-3.5 animate-spin" /> : <Sparkles className="size-3.5" />}
          </button>
        </div>
      </div>
      {error && <p role="alert" className="mt-1 text-2xs text-[#fca5a5]">{error}</p>}
    </div>
  )
}
