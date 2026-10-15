import { create } from 'zustand'
import { teamNow, useTeam, type Team } from './team'
import type { Agent, AgentId, AgentState } from './types'

// The team from hermes.json (telemetry/team.ts) is the starting roster; live mode adds any other profile found on the VM.
function fromTeam(team: Team): Agent[] {
  return team.agents.map((a) => ({ id: a.id, name: a.name, profile: a.profile, role: a.title }))
}

/** The team's agents right now (chief first). */
export const coreAgents = (): Agent[] => fromTeam(teamNow())

/** A short role from a profile description: "Rocky: training and swimming…" -> "Training and swimming". */
export function roleFrom(description: string, fallback = 'Specialist'): string {
  const text = description.replace(/^[^:]{1,24}:\s*/, '').split(/[.;,(]/)[0]?.trim() ?? ''
  if (!text) return fallback
  const short = text.length > 34 ? `${text.slice(0, 32).replace(/\s+\S*$/, '')}…` : text
  return short.charAt(0).toUpperCase() + short.slice(1)
}

interface Roster {
  list: Agent[]
  fromMesh: (agents: AgentState[]) => void
  reset: () => void
}

export const useRoster = create<Roster>((set) => ({
  list: coreAgents(),
  fromMesh: (agents) => set({
    list: agents.map((a) => {
      const core = coreAgents().find((c) => c.id === a.id)
      return { id: a.id, name: a.name || core?.name || a.id, profile: a.profile, role: core?.role ?? roleFrom(a.description) }
    }),
  }),
  reset: () => set({ list: coreAgents() }),
}))

// a new team (demo <-> live, or hermes.json changed): the roster follows until the agent feed brings the VM's list
useTeam.subscribe((s, prev) => { if (s.team !== prev.team) useRoster.getState().reset() })

export function findAgent(id: AgentId | null | undefined): Agent | undefined {
  return id ? useRoster.getState().list.find((a) => a.id === id) : undefined
}

export function agentName(id: AgentId): string {
  if (id === 'owner') return teamNow().owner.name
  return findAgent(id)?.name ?? id.charAt(0).toUpperCase() + id.slice(1)
}

export function isAgentId(value: unknown): value is AgentId {
  return typeof value === 'string' && Boolean(findAgent(value))
}

export function authorLabel(author: string): string {
  if (author === 'import') return 'Imported'
  if (author === 'dashboard') return 'You (dashboard)'
  if (author === 'unknown') return 'Unknown'
  if (author === 'claude-code') return 'Claude Code'
  if (author === 'claude-cloud') return 'Claude Code (cloud)'
  return agentName(author)
}
