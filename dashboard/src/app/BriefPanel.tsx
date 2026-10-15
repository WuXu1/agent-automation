import { Loader2, Send, X } from 'lucide-react'
import { play } from '@/lib/sound'
import { useMode } from '@/telemetry/mode'
import { useChief } from '@/telemetry/team'
import { AgentBadge } from '@/ui/AgentBadge'
import { Button, IconButton } from '@/ui/Button'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { useBrief } from './brief'

/** A small panel over any view: write the directive, confirm, read the chief's reply. Not modal: the page stays usable. */
export function BriefPanel() {
  const b = useBrief()
  const mode = useMode((s) => s.mode)
  const chief = useChief()
  if (!b.open) return null
  return (
    <section aria-label={`Brief ${chief.name}`} className="glass fixed inset-x-2 bottom-[76px] z-40 mx-auto max-w-xl bg-glass-strong p-4 shadow-[0_24px_64px_-16px_rgb(0_0_0/0.75)] md:bottom-6">
      <header className="mb-2 flex items-center gap-2">
        <AgentBadge id={chief.id} />
        <h2 className="flex-1 text-[13px] font-semibold">Brief {chief.name}</h2>
        <IconButton label="Close" onClick={b.close}><X className="size-4" /></IconButton>
      </header>
      {b.phase === 'compose' || b.phase === 'error' ? (
        <>
          <label htmlFor="brief-text" className="sr-only">Message to {chief.name}</label>
          <textarea id="brief-text" value={b.text} onChange={(e) => b.setText(e.target.value)} rows={3} ref={(el) => { el?.focus() }}
            placeholder="e.g. Ask the tutor to plan revision for my next exam and put it in my calendar."
            className="w-full resize-y rounded-lg border border-line bg-void/50 px-3 py-2 text-[13px] leading-relaxed text-ink outline-none focus:border-line-strong" />
          {b.error && <p role="alert" className="mt-1 text-2xs text-[#fca5a5]">{b.error}</p>}
          <div className="mt-2 flex items-center gap-2">
            <ConfirmButton label={`Send to ${chief.name}`} confirmLabel="Send it" tone="memory" icon={<Send className="size-3.5" />} disabled={!b.text.trim()}
              onConfirm={async () => { play('open'); await b.send() }} />
            <span className="text-2xs text-ink-faint">{mode === 'live' ? `A real message to ${chief.name}, as if you had sent it on Telegram.` : 'Demo: nothing is sent.'}</span>
          </div>
        </>
      ) : (
        <>
          <p className="rounded-lg border border-line bg-white/[0.02] px-3 py-2 text-[12px] whitespace-pre-line text-ink-dim">{b.text}</p>
          {b.phase === 'waiting' ? (
            <p className="mt-3 flex items-center gap-2 text-[13px] text-ink-dim"><Loader2 className="size-4 animate-spin text-agent" /> {chief.name} is on it…</p>
          ) : (
            <div className="mt-3">
              <div className="mb-1 text-2xs text-[#f0abfc]">{chief.name}</div>
              <p className="max-h-60 overflow-y-auto text-[13px] leading-relaxed whitespace-pre-line text-ink">{b.reply}</p>
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={() => b.show('')}>Another</Button>
                <Button size="sm" tone="ghost" onClick={b.close}>Close</Button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
