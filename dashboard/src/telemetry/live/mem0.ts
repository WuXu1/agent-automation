import { api } from './client'
import type { ClusterId, Memory, SearchHit } from '../types'

export interface BrainState { sections: Array<{ id: ClusterId; label: string; blurb: string; builtin: boolean }>; assign: Record<string, ClusterId>; sorting: boolean; unsorted?: number }

export const mem0 = {
  list: () => api<{ memories: Memory[] }>('/memories').then((r) => r.memories),
  search: (query: string, signal?: AbortSignal) =>
    api<{ results: SearchHit[] }>('/memories/search', { method: 'POST', body: { query, top_k: 12 }, signal }).then((r) => r.results),
  add: (text: string, place: { section?: ClusterId; newSection?: string } = {}) =>
    api<{ memory: Memory }>('/memories', { method: 'POST', body: { text, ...place } }).then((r) => r.memory),
  brain: () => api<BrainState>('/brain', { timeoutMs: 20_000 }),
  update: (id: string, text: string) =>
    api<{ memory: Memory }>(`/memories/${encodeURIComponent(id)}`, { method: 'PUT', body: { text } }).then((r) => r.memory),
  remove: (id: string) => api<{ ok: true }>(`/memories/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}
