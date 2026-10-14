import { useMode } from '@/telemetry/mode'
import { cn } from '@/lib/cn'
import type { Mode } from '@/telemetry/types'

/** Demo or live. Live needs the bridge; when it is down the button says why instead of failing silently. */
export function ModeSwitch() {
  const mode = useMode((s) => s.mode)
  const bridge = useMode((s) => s.bridge)
  const setMode = useMode((s) => s.setMode)
  const liveOff = bridge !== 'up'

  const item = (m: Mode, label: string, disabled = false, title?: string) => (
    <button
      type="button"
      aria-pressed={mode === m}
      disabled={disabled}
      title={title}
      onClick={() => setMode(m)}
      className={cn(
        'press h-7 rounded-md px-2.5 text-2xs font-semibold tracking-[0.04em] uppercase disabled:opacity-40',
        mode === m
          ? m === 'live' ? 'bg-ok/15 text-[#6ee7b7]' : 'bg-runway/15 text-[#fcd34d]'
          : 'text-ink-faint hover:text-ink-dim',
      )}
    >
      {label}
    </button>
  )

  return (
    <div aria-label="Data source" className="flex items-center gap-0.5 rounded-lg border border-line bg-white/[0.03] p-0.5">
      {item('demo', 'Demo', false, 'Generated data, works anywhere')}
      {item('live', 'Live', liveOff,
        bridge === 'unknown' ? 'Looking for the bridge…' : liveOff ? 'The bridge on the VM is not reachable from here' : 'Real data from the VM')}
    </div>
  )
}
