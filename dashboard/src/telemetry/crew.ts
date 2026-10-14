import { create } from 'zustand'
import { api } from './live/client'
import type { Mode } from './types'

// Who this install is for (bridge/crew.py, GET /api/crew): the owner, the four agents with the names chosen at install time,
// and the add-ons switched on. Nothing on the page hard-codes a name; demo mode uses the made-up crew below.

export interface CrewAgent {
  /** The id the page and the board use (chosen at install, e.g. 'atlas'). */
  id: string
  /** The Hermes profile ('default' is the chief). */
  profile: string
  role: string
  name: string
  title: string
}
export interface Features { voice: boolean; gmail: boolean; moodle: boolean; icloud: boolean; backup: boolean }
export interface Crew {
  owner: { name: string; pronouns: string }
  timezone: string
  /** The chief's agent id. */
  chief: string
  agents: CrewAgent[]
  features: Features
}

/** Demo mode: invented people, every add-on on so each view has something to show. */
export const DEMO_CREW: Crew = {
  owner: { name: 'Sam', pronouns: 'they/them' },
  timezone: 'Europe/London',
  chief: 'atlas',
  agents: [
    { id: 'atlas', profile: 'default', role: 'chief', name: 'Atlas', title: 'Chief of Staff' },
    { id: 'sage', profile: 'tutor', role: 'tutor', name: 'Sage', title: 'Tutor' },
    { id: 'ivy', profile: 'assistant', role: 'assistant', name: 'Ivy', title: 'Assistant' },
    { id: 'rocky', profile: 'coach', role: 'coach', name: 'Rocky', title: 'Coach' },
  ],
  features: { voice: true, gmail: true, moodle: true, icloud: true, backup: true },
}

/** Live mode before /api/crew answers (or when it cannot): plain names, no add-ons. */
const PLAIN: Crew = {
  owner: { name: 'You', pronouns: 'they/them' },
  timezone: 'Europe/London',
  chief: 'chief',
  agents: [
    { id: 'chief', profile: 'default', role: 'chief', name: 'Chief', title: 'Chief of Staff' },
    { id: 'tutor', profile: 'tutor', role: 'tutor', name: 'Tutor', title: 'Tutor' },
    { id: 'assistant', profile: 'assistant', role: 'assistant', name: 'Assistant', title: 'Assistant' },
    { id: 'coach', profile: 'coach', role: 'coach', name: 'Coach', title: 'Coach' },
  ],
  features: { voice: false, gmail: false, moodle: false, icloud: false, backup: false },
}

interface CrewStore {
  crew: Crew
  load: (mode: Mode) => Promise<void>
}

export const useCrew = create<CrewStore>((set, get) => ({
  crew: DEMO_CREW,
  load: async (mode) => {
    if (mode !== 'live') { set({ crew: DEMO_CREW }); return }
    if (get().crew === DEMO_CREW) set({ crew: PLAIN })            // never show the demo names on a real install
    try { set({ crew: await api<Crew>('/crew') }) } catch { /* keep what we have */ }
  },
}))

export const crewNow = (): Crew => useCrew.getState().crew
export const chiefId = (): string => crewNow().chief
export const ownerName = (): string => crewNow().owner.name

/** The chief (the agent on profile 'default'). */
export function useChief(): CrewAgent {
  return useCrew((s) => s.crew.agents.find((a) => a.id === s.crew.chief) ?? s.crew.agents[0]!)
}
export const useOwner = (): Crew['owner'] => useCrew((s) => s.crew.owner)
export const useFeature = (f: keyof Features): boolean => useCrew((s) => s.crew.features[f])
/** A crew agent's name by its Hermes profile, for text written about a role ("the tutor reads"). */
export function nameOfProfile(crew: Crew, profile: string): string {
  return crew.agents.find((a) => a.profile === profile)?.name ?? profile
}
