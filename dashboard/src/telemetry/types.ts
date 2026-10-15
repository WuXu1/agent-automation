// The data contract between the page and the bridge (`bridge/` serves exactly these shapes under /api).
// Demo mode produces the same shapes, so every view renders the same way in both modes.

/** The team's ids from hermes.json (e.g. 'atlas'); an agent added later is known by its profile id. */
export type AgentId = string

export interface Agent {
  id: AgentId
  name: string
  profile: string
  role: string
}

/** A Second Brain section: the eight built in ('uni', 'admin', 'health', 'fitness', 'software', 'people', 'rules', 'interests') and any the AI starts. */
export type ClusterId = string

/** One Mem0 note. `author` is Mem0's agent_id: an agent, an import, or the dashboard. */
export interface Memory {
  id: string
  text: string
  author: AgentId | 'import' | 'dashboard' | 'unknown'
  /** metadata.source: 'dashboard', an import's name, … or null when an agent stored it */
  source: string | null
  category: string | null
  createdAt: number
  updatedAt: number | null
  metadata: Record<string, unknown>
}

export interface SearchHit {
  id: string
  score: number
}

/** Something that happened to a memory, for the pulses and the activity feed. */
export interface MemoryEvent {
  at: number
  kind: 'search' | 'read' | 'add' | 'update' | 'delete'
  memoryIds: string[]
  agent: AgentId | 'dashboard' | null
  note?: string
}

export type Mode = 'demo' | 'live'

export type LoadState = 'idle' | 'loading' | 'ready' | 'error'

// -- B. Agent Studio (GET /api/agents) ------------------------------------------------------------------------------------

export interface McpServer {
  name: string
  enabled: boolean
}

export interface AgentState {
  id: AgentId
  profile: string
  name: string
  /** What the chief reads when deciding who gets a card (profile.yaml `description`). */
  description: string
  /** One of the team from hermes.json. */
  core: boolean
  /** Its lead (an agent id); null for the chief, who reports to the owner. */
  reportsTo: AgentId | null
  model: string | null
  effort: string | null
  mcp: McpServer[]
  /** Cards on the board by state, for this agent's profile. */
  running: number
  queued: number
  blocked: number
  done7d: number
  lastActive: number | null
  /** Its recent AI runs, oldest first (board cards and its cron jobs), for the heatmap strip. */
  runs?: AgentRun[]
  /** Last 30 days: ok / (ok + error). */
  reliability?: { ok: number; errors: number; total: number; pct: number | null }
}

export interface AgentRun {
  status: 'ok' | 'waiting' | 'error' | 'running'
  trigger: 'board' | 'cron'
  title: string
  at: number
  secs: number | null
}

/** Something moving between agents on the board: the chief hands a card down, a worker asks a question or finishes.
 * 'owner' is the person the team works for. */
export interface Handoff {
  at: number
  from: AgentId | 'owner' | 'helper'
  to: AgentId | 'owner'
  kind: 'assign' | 'question' | 'done' | 'message'
  title: string
  cardId: string
}

/** Two agents working together right now (an open card): the lead waits on its worker's card, or the worker waits on an answer. */
export interface Talk {
  from: AgentId | 'owner'
  to: AgentId | 'owner'
  state: 'working' | 'asking'
  title: string
  cardId: string
  since: number
}

export interface AgentMesh {
  at: number
  gateway: { ok: boolean; version: string | null }
  agents: AgentState[]
  handoffs: Handoff[]
  /** Open cards between two agents right now (bridge `feeds.talks`); older bridges leave it out. */
  talks?: Talk[]
}

// -- C. Runway (GET /api/infra) ---------------------------------------------------------------------------------------------

export type ServiceState = 'active' | 'inactive' | 'failed' | 'activating' | 'unknown'

export interface Service {
  unit: string
  state: ServiceState
  since: number | null
  memBytes: number | null
  /** From the registry (dashboard/bridge/registry.json); `described: false` = installed on the VM, not described yet. */
  label?: string
  port?: number | null
  described?: boolean
}

export interface Infra {
  at: number
  vm: {
    cpuPct: number
    memUsed: number
    memTotal: number
    diskUsed: number
    diskTotal: number
    load: [number, number, number]
    uptimeSecs: number
  }
  services: Service[]
  backup: { lastRunAt: number | null; ok: boolean | null; nextRunAt: number | null }
  /** A dated snapshot: a student subscription has no API for the balance. */
  credit: { balance: number; asOf: string; burnPerDay: number; start: number }
  cleanable: Array<{ path: string; bytes: number | null }>
}

// -- D. Board (GET /api/board) ----------------------------------------------------------------------------------------------

export type CardStatus = 'triage' | 'todo' | 'ready' | 'scheduled' | 'running' | 'blocked' | 'review' | 'done' | 'archived'

export interface Card {
  id: string
  title: string
  status: CardStatus
  assignee: AgentId | null
  /** The raw Hermes profile when it is not a known agent (e.g. a researcher helper). */
  assigneeProfile: string | null
  createdBy: AgentId | 'owner' | 'helper' | null
  priority: number
  createdAt: number
  startedAt: number | null
  completedAt: number | null
  parents: string[]
  summary: string | null
  /** Open cards only: the last few comments (a blocked card's question is usually the last one). */
  comments: Array<{ author: string; body: string; at: number }>
}

export interface Board {
  at: number
  cards: Card[]
}

// -- writes (bridge actions.py) ---------------------------------------------------------------------------------------------

export interface AgentDetail {
  profile: string
  name: string
  description: string
  soul: string
  model: string | null
  effort: string | null
  telegram: boolean
  core: boolean
  /** Its lead's profile id; null for the chief. */
  reportsTo: string | null
}

export interface RestartState {
  /** What is waiting for a gateway restart (an MCP change, a new agent), oldest first. */
  needed: string[]
  requested: boolean
  last: { at: number; state: 'running' | 'done' | 'refused' | 'failed'; message: string } | null
}
