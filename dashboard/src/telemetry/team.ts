import { create } from 'zustand'
import { api } from './live/client'
import type { Mode } from './types'

// Who this install is for (bridge/team.py, GET /api/team): the owner, the four agents with the names chosen at install time,
// and the add-ons switched on. Nothing on the page hard-codes a name; demo mode uses the made-up team below.

export interface TeamAgent {
  /** The id the page and the board use (chosen at install, e.g. 'atlas'). */
  id: string
  /** The Hermes profile ('default' is the chief). */
  profile: string
  role: string
  name: string
  title: string
}
export interface Features { voice: boolean; gmail: boolean; moodle: boolean; icloud: boolean; backup: boolean; studio: boolean }
export interface Team {
  owner: { name: string; pronouns: string }
  timezone: string
  /** The chief's agent id. */
  chief: string
  agents: TeamAgent[]
  features: Features
}

/** Demo mode: invented people, every add-on on so each view has something to show. */
export const DEMO_TEAM: Team = {
  owner: { name: 'Sam', pronouns: 'they/them' },
  timezone: 'Europe/London',
  chief: 'atlas',
  agents: [
    { id: 'atlas', profile: 'default', role: 'chief', name: 'Atlas', title: 'Chief of Staff' },
    { id: 'sage', profile: 'tutor', role: 'tutor', name: 'Sage', title: 'Tutor' },
    { id: 'ivy', profile: 'assistant', role: 'assistant', name: 'Ivy', title: 'Assistant' },
    { id: 'rocky', profile: 'coach', role: 'coach', name: 'Rocky', title: 'Coach' },
  ],
  features: { voice: true, gmail: true, moodle: true, icloud: true, backup: true, studio: true },
}

/** Live mode before /api/team answers (or when it cannot): plain names, no add-ons. */
const PLAIN: Team = {
  owner: { name: 'You', pronouns: 'they/them' },
  timezone: 'Europe/London',
  chief: 'chief',
  agents: [
    { id: 'chief', profile: 'default', role: 'chief', name: 'Chief', title: 'Chief of Staff' },
    { id: 'tutor', profile: 'tutor', role: 'tutor', name: 'Tutor', title: 'Tutor' },
    { id: 'assistant', profile: 'assistant', role: 'assistant', name: 'Assistant', title: 'Assistant' },
    { id: 'coach', profile: 'coach', role: 'coach', name: 'Coach', title: 'Coach' },
  ],
  features: { voice: false, gmail: false, moodle: false, icloud: false, backup: false, studio: false },
}

interface TeamStore {
  team: Team
  load: (mode: Mode) => Promise<void>
}

export const useTeam = create<TeamStore>((set, get) => ({
  team: DEMO_TEAM,
  load: async (mode) => {
    if (mode !== 'live') { set({ team: DEMO_TEAM }); return }
    if (get().team === DEMO_TEAM) set({ team: PLAIN })            // never show the demo names on a real install
    try { set({ team: await api<Team>('/team') }) } catch { /* keep what we have */ }
  },
}))

export const teamNow = (): Team => useTeam.getState().team
export const chiefId = (): string => teamNow().chief
export const ownerName = (): string => teamNow().owner.name

/** The chief (the agent on profile 'default'). */
export function useChief(): TeamAgent {
  return useTeam((s) => s.team.agents.find((a) => a.id === s.team.chief) ?? s.team.agents[0]!)
}
export const useOwner = (): Team['owner'] => useTeam((s) => s.team.owner)
export const useFeature = (f: keyof Features): boolean => useTeam((s) => s.team.features[f])
/** A team agent's name by its Hermes profile, for text written about a role ("the tutor reads"). */
export function nameOfProfile(team: Team, profile: string): string {
  return team.agents.find((a) => a.profile === profile)?.name ?? profile
}
