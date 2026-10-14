import { useEffect } from 'react'
import { create } from 'zustand'
import { coreAgents } from '../agents'
import { BUILTIN_SECTIONS, withColours, type Section } from '../clusters'
import { demoMemories } from '../demo/memories'
import { demoSearch } from '../demo/search'
import { buildGraph, type MemoryGraph } from '../graph'
import { BridgeError } from '../live/client'
import { mem0 } from '../live/mem0'
import { useMode } from '../mode'
import { pulse } from '../pulses'
import type { AgentId, ClusterId, LoadState, Memory, MemoryEvent, Mode, SearchHit } from '../types'

interface BrainState {
  mode: Mode | null
  status: LoadState
  error: string | null
  memories: Memory[]
  graph: MemoryGraph
  loadedAt: number | null
  events: MemoryEvent[]
  /** The brain's sections and where the AI put each note (bridge/brain.py); demo: the eight built in, by keywords. */
  sections: Section[]
  assign: Record<string, ClusterId>
  /** The AI is sorting new notes into sections right now; how many are still unsorted. */
  sorting: boolean
  unsorted: number

  query: string
  searching: boolean
  hits: SearchHit[] | null

  load: (mode: Mode) => Promise<void>
  refresh: () => Promise<void>
  search: (query: string) => Promise<void>
  clearSearch: () => void
  loadBrain: () => Promise<void>
  setBrain: (sections: Section[], assign?: Record<string, ClusterId>) => void
  add: (text: string, place?: { section?: ClusterId; newSection?: string }) => Promise<Memory>
  update: (id: string, text: string) => Promise<Memory>
  remove: (id: string) => Promise<void>
}

const EMPTY = buildGraph([])
const MAX_EVENTS = 40

function message(err: unknown): string {
  if (err instanceof BridgeError) return err.status === 0 ? err.message : `${err.message} (HTTP ${err.status})`
  return err instanceof Error ? err.message : 'Something went wrong'
}

let searchAbort: AbortController | null = null

export const useBrain = create<BrainState>((set, get) => {
  const setMemories = (memories: Memory[]) =>
    set({ memories, graph: buildGraph(memories, get().sections, get().assign), loadedAt: Date.now() })
  const log = (e: MemoryEvent) => set((s) => ({ events: [e, ...s.events].slice(0, MAX_EVENTS) }))

  return {
    mode: null,
    status: 'idle',
    error: null,
    memories: [],
    graph: EMPTY,
    loadedAt: null,
    events: [],
    sections: BUILTIN_SECTIONS,
    assign: {},
    sorting: false,
    unsorted: 0,
    query: '',
    searching: false,
    hits: null,

    loadBrain: async () => {
      if (get().mode !== 'live') return
      try {
        const b = await mem0.brain()
        set({ sections: withColours(b.sections), assign: b.assign, sorting: b.sorting, unsorted: b.unsorted ?? 0 })
        set((s) => ({ graph: buildGraph(s.memories, s.sections, s.assign) }))
      } catch { /* the keyword placement stays */ }
    },

    setBrain: (sections, assign) => {
      set((s) => ({ sections, assign: assign ?? s.assign }))
      set((s) => ({ graph: buildGraph(s.memories, s.sections, s.assign) }))
    },

    load: async (mode) => {
      set({ mode, status: 'loading', error: null, hits: null, query: '', events: [], sections: BUILTIN_SECTIONS, assign: {}, sorting: false, unsorted: 0 })
      if (mode === 'demo') {
        setMemories(demoMemories())
        set({ status: 'ready' })
        return
      }
      try {
        setMemories(await mem0.list())
        set({ status: 'ready' })
        void get().loadBrain()
      } catch (err) {
        set({ status: 'error', error: message(err), memories: [], graph: EMPTY })
      }
    },

    // Live only: notes that changed since the last look pulse once.
    refresh: async () => {
      if (get().mode !== 'live') return
      try {
        const before = new Map(get().memories.map((m) => [m.id, m.updatedAt ?? m.createdAt]))
        const next = await mem0.list()
        const changed = next.filter((m) => before.get(m.id) !== (m.updatedAt ?? m.createdAt)).map((m) => m.id)
        setMemories(next)
        set({ status: 'ready', error: null })
        void get().loadBrain()
        if (changed.length && before.size) {
          pulse(changed, 'write')
          log({ at: Date.now(), kind: 'update', memoryIds: changed, agent: null, note: `${changed.length} changed since the last look` })
        }
      } catch (err) {
        set({ error: message(err) })
      }
    },

    search: async (query) => {
      const q = query.trim()
      set({ query })
      if (!q) { get().clearSearch(); return }
      searchAbort?.abort()
      const ctl = new AbortController()
      searchAbort = ctl
      set({ searching: true })
      try {
        const hits = get().mode === 'live' ? await mem0.search(q, ctl.signal) : demoSearch(get().memories, q)
        if (ctl.signal.aborted) return
        set({ hits, searching: false })
        pulse(hits.map((h) => h.id), 'hit')
        log({ at: Date.now(), kind: 'search', memoryIds: hits.map((h) => h.id), agent: 'dashboard', note: q })
      } catch (err) {
        if (ctl.signal.aborted) return
        set({ searching: false, error: message(err) })
      }
    },

    clearSearch: () => {
      searchAbort?.abort()
      set({ query: '', hits: null, searching: false })
    },

    add: async (text, place = {}) => {
      const memory: Memory = get().mode === 'live'
        ? await mem0.add(text, place)
        : { id: `demo-new-${Date.now().toString(36)}`, text, author: 'dashboard', source: 'dashboard', category: null,
            createdAt: Date.now(), updatedAt: null, metadata: { source: 'dashboard' } }
      if (get().mode === 'live') {
        set({ memories: [...get().memories, memory] })
        await get().loadBrain()
      } else {
        // demo: the same placement the bridge would make, in this tab
        let sid = place.section
        if (place.newSection) {
          const label = place.newSection.trim()
          const found = get().sections.find((s) => s.label.toLowerCase() === label.toLowerCase())
          sid = found?.id ?? label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
          if (!found) set((s) => ({ sections: [...s.sections, ...withColours([{ id: sid!, label, blurb: 'Started by the AI', builtin: false }])] }))
        }
        if (sid) set((s) => ({ assign: { ...s.assign, [memory.id]: sid! } }))
        set({ memories: [...get().memories, memory] })
      }
      set((s) => ({ graph: buildGraph(s.memories, s.sections, s.assign), loadedAt: Date.now() }))
      pulse([memory.id], 'write')
      log({ at: Date.now(), kind: 'add', memoryIds: [memory.id], agent: 'dashboard' })
      return memory
    },

    update: async (id, text) => {
      const current = get().memories.find((m) => m.id === id)
      if (!current) throw new Error('That memory is no longer there')
      const memory = get().mode === 'live' ? await mem0.update(id, text) : { ...current, text, updatedAt: Date.now() }
      setMemories(get().memories.map((m) => (m.id === id ? memory : m)))
      pulse([id], 'write')
      log({ at: Date.now(), kind: 'update', memoryIds: [id], agent: 'dashboard' })
      return memory
    },

    remove: async (id) => {
      if (get().mode === 'live') await mem0.remove(id)
      setMemories(get().memories.filter((m) => m.id !== id))
      set((s) => ({ hits: s.hits?.filter((h) => h.id !== id) ?? null }))
      log({ at: Date.now(), kind: 'delete', memoryIds: [id], agent: 'dashboard' })
    },
  }
})

// Demo heartbeat: an agent looks something up every few seconds, the way the Mem0 plugin searches before each reply.
// Keyed by Hermes profile, so it works for any crew's names.
const DEMO_ASKS: Record<string, string[]> = {
  default: ['morning briefing', 'what is on the board', 'family calls', 'quiet hours'],
  tutor: ['deadline this week', 'study blocks', 'lab write-up', 'reading list'],
  assistant: ['weekly shop', 'calendar', 'budget', 'reminder'],
  coach: ['swim rain', 'protein', 'gym sessions', 'sleep'],
}

function useDemoHeartbeat(active: boolean) {
  useEffect(() => {
    if (!active) return
    const tick = () => {
      const s = useBrain.getState()
      if (s.status !== 'ready' || s.memories.length === 0) return
      const crew = coreAgents()
      const who = crew[Math.floor(Math.random() * crew.length)]!
      const agent: AgentId = who.id
      const asks = DEMO_ASKS[who.profile] ?? []
      const ask = asks[Math.floor(Math.random() * asks.length)]
      if (!ask) return
      const ids = demoSearch(s.memories, ask, 3).map((h) => h.id)
      if (!ids.length) return
      pulse(ids, 'read')
      useBrain.setState((st) => ({
        events: [{ at: Date.now(), kind: 'read' as const, memoryIds: ids, agent, note: ask }, ...st.events].slice(0, MAX_EVENTS),
      }))
    }
    const id = window.setInterval(tick, 2600)
    return () => window.clearInterval(id)
  }, [active])
}

/** Mem0 as a graph, in demo or live mode. Mount once (the Second Brain view); other views read `useBrain` directly. */
export function useMem0Graph() {
  const mode = useMode((s) => s.mode)
  const bridge = useMode((s) => s.bridge)
  const load = useBrain((s) => s.load)
  const refresh = useBrain((s) => s.refresh)

  useEffect(() => {
    if (bridge === 'unknown') return
    void load(mode)
  }, [mode, bridge, load])

  useEffect(() => {
    if (mode !== 'live') return
    const id = window.setInterval(() => void refresh(), 30_000)
    return () => window.clearInterval(id)
  }, [mode, refresh])

  // While the AI sorts new notes into sections, look again every few seconds so they move into place.
  const sorting = useBrain((s) => s.sorting)
  const loadBrain = useBrain((s) => s.loadBrain)
  useEffect(() => {
    if (mode !== 'live' || !sorting) return
    const id = window.setInterval(() => void loadBrain(), 4000)
    return () => window.clearInterval(id)
  }, [mode, sorting, loadBrain])

  useDemoHeartbeat(mode === 'demo')
}
