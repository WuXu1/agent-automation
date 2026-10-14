import { create } from 'zustand'
import { reloadFeed } from '@/telemetry/feed'
import { agentFeed } from '@/telemetry/hooks/feeds'
import { live, type AgentInput } from '@/telemetry/live/actions'
import { useMode } from '@/telemetry/mode'
import type { AgentDetail, AgentMesh, RestartState } from '@/telemetry/types'

// Agent writes in one place. Live: the bridge (confirmed, backed up, logged on the VM). Demo: the demo data changes in
// this tab only, so every control can be tried without a VM.

// The demo crew's SOULs (telemetry/crew.ts DEMO_CREW), keyed by Hermes profile.
const DEMO_SOULS: Record<string, string> = {
  default: 'You are Atlas, Sam’s chief of staff. You run the board, brief Sam each morning and speak for the team.',
  tutor: 'You are Sage, Sam’s tutor. You turn course deadlines into study blocks and explain things plainly.',
  assistant: 'You are Ivy, Sam’s assistant. You keep the calendar, draft emails for Sam’s yes, and plan the week.',
  coach: 'You are Rocky, Sam’s coach. Training, meals, sleep: short plans, honest check-ins.',
}

const live_ = () => useMode.getState().mode === 'live'

function patchDemo(fn: (m: AgentMesh) => AgentMesh) {
  const s = agentFeed.getState()
  if (s.data) agentFeed.setState({ data: fn(s.data), at: Date.now() })
}

interface RestartStore {
  state: RestartState
  set: (s: RestartState) => void
}

export const useRestart = create<RestartStore>((set) => ({
  state: { needed: [], requested: false, last: null },
  set: (state) => set({ state }),
}))

function demoNeedsRestart(reason: string) {
  const s = useRestart.getState().state
  useRestart.getState().set({ ...s, needed: [...s.needed.filter((r) => r !== reason), reason] })
}

export async function loadAgent(profile: string): Promise<AgentDetail> {
  if (live_()) return live.agent(profile)
  const a = agentFeed.getState().data?.agents.find((x) => x.profile === profile)
  if (!a) throw new Error('No such agent')
  const lead = agentFeed.getState().data?.agents.find((x) => x.id === a.reportsTo)
  return { profile, name: a.name, description: a.description, soul: DEMO_SOULS[profile] ?? '', model: a.model, effort: a.effort,
    telegram: a.core, core: a.core, reportsTo: lead?.profile ?? null }
}

export async function updateAgent(profile: string, patch: AgentInput) {
  if (live_()) {
    const out = await live.updateAgent(profile, patch)
    await reloadFeed(agentFeed)
    if (patch.mcp) await refreshRestart()
    return out
  }
  if (patch.soul !== undefined) DEMO_SOULS[profile] = patch.soul
  patchDemo((m) => ({ ...m, agents: m.agents.map((a) => a.profile !== profile ? a : {
    ...a,
    name: patch.name ?? a.name, description: patch.description ?? a.description, model: patch.model ?? a.model,
    effort: patch.effort ?? a.effort,
    mcp: patch.mcp ? a.mcp.map((s) => (s.name in patch.mcp! ? { ...s, enabled: patch.mcp![s.name]! } : s)) : a.mcp,
  }) }))
  if (patch.mcp) demoNeedsRestart(`MCP servers changed on ${profile}`)
  return loadAgent(profile)
}

export async function deleteAgent(profile: string, confirm: string) {
  if (live_()) {
    const out = await live.deleteAgent(profile, confirm)
    await reloadFeed(agentFeed)
    await refreshRestart()
    return out
  }
  if (confirm !== profile) throw new Error('Type the agent’s profile id to confirm')
  patchDemo((m) => {
    const gone = m.agents.find((a) => a.profile === profile)
    return { ...m, agents: m.agents.filter((a) => a.profile !== profile)
      .map((a) => (gone && a.reportsTo === gone.id ? { ...a, reportsTo: gone.reportsTo } : a)) }   // its team moves up
  })
  demoNeedsRestart(`agent ${profile} deleted`)
  return { ok: true as const, archive: `${profile}-demo.tar.gz` }
}

export async function refreshRestart() {
  if (!live_()) return
  try {
    useRestart.getState().set(await live.restart())
  } catch { /* the bar keeps its last state */ }
}

export async function requestRestart() {
  if (live_()) {
    await live.requestRestart()
    await refreshRestart()
    return
  }
  useRestart.getState().set({ needed: useRestart.getState().state.needed, requested: true, last: { at: Math.floor(Date.now() / 1000), state: 'running', message: 'Checking that nothing is in progress' } })
  window.setTimeout(() => useRestart.getState().set({ needed: [], requested: false,
    last: { at: Math.floor(Date.now() / 1000), state: 'done', message: 'gateway up and API answering after 70s (demo)' } }), 2500)
}
