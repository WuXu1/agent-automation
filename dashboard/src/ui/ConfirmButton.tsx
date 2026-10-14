import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Button } from './Button'

type Phase = 'idle' | 'armed' | 'busy'

/**
 * A write behind one deliberate second click (every memory edit is confirmed).
 * First click arms it and names exactly what will happen; it disarms itself after 6 s or on Cancel.
 */
export function ConfirmButton({ label, confirmLabel, onConfirm, tone = 'plain', icon, disabled, size = 'md', ariaLabel, confirmTone }: {
  label: string
  confirmLabel: string
  onConfirm: () => Promise<unknown>
  tone?: 'plain' | 'memory' | 'danger' | 'ghost'
  /** The armed button's tone (defaults to `tone`, or memory for plain and ghost). */
  confirmTone?: 'memory' | 'danger'
  icon?: ReactNode
  disabled?: boolean
  size?: 'sm' | 'md'
  /** For an icon-only button (empty label): what it does, for screen readers and the tooltip. */
  ariaLabel?: string
}) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const confirmRef = useRef<HTMLButtonElement>(null)

  // Keyboard users land on the confirm button once it is armed.
  useEffect(() => { if (phase === 'armed') confirmRef.current?.focus() }, [phase])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const arm = () => {
    setError(null)
    setPhase('armed')
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setPhase((p) => (p === 'armed' ? 'idle' : p)), 6000)
  }

  const run = async () => {
    window.clearTimeout(timer.current)
    setPhase('busy')
    try {
      await onConfirm()
      setPhase('idle')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work')
      setPhase('idle')
    }
  }

  if (phase === 'idle') {
    return (
      <span className="inline-flex flex-col items-start gap-1">
        <Button tone={tone} icon={icon} onClick={arm} disabled={disabled} size={size} aria-label={ariaLabel} title={ariaLabel}
          className={label ? undefined : 'w-7 shrink-0 px-0!'}>{label}</Button>
        {error && <span role="alert" className="text-2xs text-[#fca5a5]">{error}</span>}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <Button ref={confirmRef} tone={confirmTone ?? (tone === 'plain' || tone === 'ghost' ? 'memory' : tone)} onClick={run} disabled={phase === 'busy'} size={size}>
        {phase === 'busy' ? 'Working…' : confirmLabel}
      </Button>
      <Button tone="ghost" onClick={() => setPhase('idle')} disabled={phase === 'busy'} size={size}>Cancel</Button>
    </span>
  )
}
