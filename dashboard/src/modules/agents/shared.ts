import type { Handoff } from '@/telemetry/types'

export const HELPERS = 3 // config.yaml `max_concurrent_children: 3`: helpers per agent

// The built-in tools and each MCP server's rule now come from the registry (src/telemetry/registry.ts, dashboard/bridge/registry.json).

export const MCP_ORDER = ['moodle', 'openalex']

export const KIND: Record<Handoff['kind'], { label: string; stroke: string; chip: 'agent' | 'warn' | 'ok' }> = {
  assign: { label: 'handed down', stroke: '#d946ef', chip: 'agent' },
  question: { label: 'asked', stroke: '#f59e0b', chip: 'warn' },
  done: { label: 'finished', stroke: '#10b981', chip: 'ok' },
  message: { label: 'wrote on the card', stroke: '#00f0ff', chip: 'agent' },
}

export const EFFORTS = ['low', 'medium', 'high'] as const
