import { Bot, Gauge, Inbox, KanbanSquare, Orbit, Plug, Settings, type LucideIcon } from 'lucide-react'
import { useTeam, type Features } from '@/telemetry/team'

export type ViewId = 'brain' | 'agents' | 'infra' | 'board' | 'inbox' | 'integrations' | 'settings'

/** The rail's groups: room for more tabs, each under a heading. */
export type SectionId = 'memory' | 'work' | 'comms' | 'system'
export const SECTIONS: ReadonlyArray<{ id: SectionId; label: string }> = [
  { id: 'memory', label: 'Memory' },
  { id: 'work', label: 'Agents & work' },
  { id: 'comms', label: 'Messages' },
  { id: 'system', label: 'System' },
]

export interface View {
  id: ViewId
  section: SectionId
  label: string
  short: string
  icon: LucideIcon
  hint: string
  /** Shown only when this add-on is switched on in hermes.json. */
  feature?: keyof Features
}

export const VIEWS: readonly View[] = [
  { id: 'brain', section: 'memory', label: 'Second Brain', short: 'Brain', icon: Orbit, hint: 'Mem0 memories as a constellation' },
  { id: 'agents', section: 'work', label: 'Agent Studio', short: 'Agents', icon: Bot, hint: 'The chief, the team and their tools' },
  { id: 'board', section: 'work', label: 'Board', short: 'Board', icon: KanbanSquare, hint: 'The cards the team hands each other' },
  { id: 'inbox', section: 'comms', label: 'Inbox', short: 'Inbox', icon: Inbox, hint: 'Gmail, read only, with an AI summary', feature: 'gmail' },
  { id: 'infra', section: 'system', label: 'Runway', short: 'Runway', icon: Gauge, hint: 'Azure credit, the VM, backups' },
  { id: 'integrations', section: 'system', label: 'Integrations', short: 'Links', icon: Plug, hint: 'Sign-ins, keys, add-ons and balances' },
]

/** The gear at the bottom of the rail. */
export const SETTINGS_VIEW: View = { id: 'settings', section: 'system', label: 'Settings', short: 'Settings', icon: Settings, hint: 'Dashboard AI model, balances, brain sections' }
export const ALL_VIEWS: readonly View[] = [...VIEWS, SETTINGS_VIEW]

export const VIEW_BY_ID = new Map<ViewId, View>(ALL_VIEWS.map((v) => [v.id, v]))

/** The view on screen: the one asked for, or the Second Brain when it belongs to an add-on that is switched off. */
export function useCurrentView(wanted: ViewId): ViewId {
  const features = useTeam((s) => s.team.features)
  const needs = VIEW_BY_ID.get(wanted)?.feature
  return needs && !features[needs] ? 'brain' : wanted
}

/** The views this install shows (an add-on's view only when hermes.json switches it on). */
export function useVisibleViews(): { views: View[]; all: View[] } {
  const features = useTeam((s) => s.team.features)
  const views = VIEWS.filter((v) => !v.feature || features[v.feature])
  return { views, all: [...views, SETTINGS_VIEW] }
}
