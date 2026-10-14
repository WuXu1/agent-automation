import { api } from './client'
import type { AgentDetail, RestartState } from '../types'

// The bridge's write routes (bridge/actions.py). Each is called only from a confirmed control on the page.
// An agent is named by its crew id or its Hermes profile; the bridge accepts either.
export interface AgentInput {
  name?: string
  description?: string
  soul?: string
  model?: string
  effort?: string
  mcp?: Record<string, boolean>
}

export const live = {
  agent: (profile: string) => api<AgentDetail>(`/agents/${profile}`),
  updateAgent: (profile: string, patch: AgentInput) =>
    api<AgentDetail & { changed: string[] }>(`/agents/${profile}`, { method: 'PUT', body: patch, timeoutMs: 60_000 }),
  deleteAgent: (profile: string, confirm: string) =>
    api<{ ok: true; archive: string }>(`/agents/${profile}`, { method: 'DELETE', body: { confirm }, timeoutMs: 120_000 }),
  restart: () => api<RestartState>('/restart'),
  requestRestart: () => api<{ ok: true }>('/restart', { method: 'POST', body: {} }),
  brief: (text: string) => api<{ runId: string }>('/chief/brief', { method: 'POST', body: { text } }),
  run: (id: string) => api<{ status: string; output: string | null }>(`/chief/runs/${encodeURIComponent(id)}`),
  createCard: (card: { title: string; body?: string; assignee?: string; priority: number }) =>
    api<{ id: string | null }>('/board/cards', { method: 'POST', body: card, timeoutMs: 60_000 }),
  answerCard: (id: string, text: string) =>
    api<{ ok: true }>(`/board/cards/${encodeURIComponent(id)}/answer`, { method: 'POST', body: { text }, timeoutMs: 60_000 }),
}
