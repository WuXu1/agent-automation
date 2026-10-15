import { create } from 'zustand'
import { BridgeError } from '@/telemetry/live/client'
import { live } from '@/telemetry/live/actions'
import { useMode } from '@/telemetry/mode'
import { teamNow } from '@/telemetry/team'

type Phase = 'compose' | 'waiting' | 'done' | 'error'

interface Brief {
  open: boolean
  text: string
  phase: Phase
  reply: string | null
  error: string | null
  show: (text?: string) => void
  setText: (text: string) => void
  close: () => void
  send: () => Promise<void>
}

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

/** The chief's name right now (from hermes.json). */
function chiefName(): string {
  const c = teamNow()
  return c.agents.find((a) => a.id === c.chief)?.name ?? 'the chief'
}

/** ⌘K "Brief <chief>": one message to the chief through the gateway; the reply shows here. */
export const useBrief = create<Brief>((set, get) => ({
  open: false,
  text: '',
  phase: 'compose',
  reply: null,
  error: null,
  show: (text = '') => set({ open: true, text, phase: 'compose', reply: null, error: null }),
  setText: (text) => set({ text: text.slice(0, 4000) }),
  close: () => set({ open: false }),
  send: async () => {
    const text = get().text.trim()
    if (!text) return
    set({ phase: 'waiting', reply: null, error: null })
    if (useMode.getState().mode !== 'live') {
      await sleep(1800)
      set({ phase: 'done', reply: `On it, ${teamNow().owner.name}. (Demo: ${chiefName()} did not really get this; switch to Live to send it.)` })
      return
    }
    try {
      const { runId } = await live.brief(text)
      for (let i = 0; i < 90; i++) {                      // the chief usually answers in 3 to 20 s; give up waiting after ~2 min
        await sleep(i < 10 ? 1200 : 2000)
        const run = await live.run(runId)
        if (run.status === 'completed') { set({ phase: 'done', reply: run.output ?? 'Done (no text reply).' }); return }
        if (['failed', 'cancelled', 'interrupted'].includes(run.status)) { set({ phase: 'error', error: `The run ${run.status}.` }); return }
        if (!get().open) return
      }
      set({ phase: 'done', reply: `${chiefName()} is still working on it. The answer will come on Telegram if there is one.` })
    } catch (err) {
      set({ phase: 'error', error: err instanceof BridgeError || err instanceof Error ? err.message : 'That did not work' })
    }
  },
}))
