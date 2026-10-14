import { RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ago } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useMode } from '@/telemetry/mode'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { refreshRestart, requestRestart, useRestart } from './writes'

const LAST: Record<string, string> = { running: 'Restarting', done: 'Restarted', refused: 'Not restarted', failed: 'Restart failed' }

/** What waits for a gateway restart, and the button that asks for a quiet one (the VM decides whether now is quiet). */
export function RestartBar() {
  const mode = useMode((s) => s.mode)
  const state = useRestart((s) => s.state)
  const now = useNow(15_000).getTime()
  const [all, setAll] = useState(false)

  useEffect(() => {
    if (mode !== 'live') return
    void refreshRestart()
    const id = window.setInterval(() => void refreshRestart(), state.requested || state.last?.state === 'running' ? 3000 : 15000)
    return () => window.clearInterval(id)
  }, [mode, state.requested, state.last?.state])

  const busy = state.requested || state.last?.state === 'running'
  const recent = state.last && now / 1000 - state.last.at < 30 * 60 ? state.last : null
  if (!state.needed.length && !busy && !recent) return null

  return (
    <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-runway/40 bg-runway/[0.07] px-4 py-3" aria-live="polite">
      <RotateCw className={busy ? 'size-4 animate-spin text-[#fcd34d]' : 'size-4 text-[#fcd34d]'} />
      <div className="min-w-0 flex-1">
        {state.needed.length > 0 && (
          <div className="text-[13px] text-ink">
            {state.needed.length === 1 ? 'One change waits' : `${state.needed.length} changes wait`} for a gateway restart:{' '}
            <span className="text-ink-dim">{(all ? state.needed : state.needed.slice(0, 3)).join('; ')}</span>
            {state.needed.length > 3 && (
              <button type="button" onClick={() => setAll((v) => !v)} className="ml-1.5 text-[12px] text-memory hover:underline">
                {all ? 'show fewer' : `+ ${state.needed.length - 3} more`}
              </button>
            )}
          </div>
        )}
        {busy && <div className="text-[12px] text-[#fcd34d]">{state.last?.message ?? 'Asked; waiting for the VM to pick it up…'}</div>}
        {!busy && recent && (
          <div className={recent.state === 'done' ? 'text-[12px] text-[#6ee7b7]' : 'text-[12px] text-[#fcd34d]'}>
            {LAST[recent.state] ?? recent.state} {ago(recent.at * 1000)}: {recent.message}
          </div>
        )}
        <div className="text-2xs text-ink-faint">The VM restarts only when quiet: no phone call, no card running, no message in the last 5 minutes. About 70 s; the agents say they are back on Telegram.</div>
      </div>
      {state.needed.length > 0 && !busy && (
        <ConfirmButton label="Restart when quiet" confirmLabel="Ask the VM to restart" tone="memory" icon={<RotateCw className="size-3.5" />} onConfirm={requestRestart} />
      )}
    </div>
  )
}
