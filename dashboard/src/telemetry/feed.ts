import { useEffect } from 'react'
import { create, type StoreApi, type UseBoundStore } from 'zustand'
import { BridgeError, api } from './live/client'
import { useMode } from './mode'
import type { LoadState, Mode } from './types'

export interface FeedState<T> {
  data: T | null
  mode: Mode | null
  status: LoadState
  error: string | null
  /** When the data was last read (live) or generated (demo). */
  at: number | null
}

export type Feed<T> = UseBoundStore<StoreApi<FeedState<T>>>

interface FeedSpec<T> {
  path: string
  /** Live poll interval. */
  everyMs: number
  /** Demo: the first value, then a step that evolves it (streaming updates). */
  demo: () => T
  tick?: (prev: T) => T
  tickMs?: number
}

const specs = new WeakMap<Feed<unknown>, FeedSpec<unknown>>()

/** One feed per bridge route (agents, infra, board), readable from any component. */
export function makeFeed<T>(spec: FeedSpec<T>): Feed<T> {
  const store = create<FeedState<T>>(() => ({ data: null, mode: null, status: 'idle', error: null, at: null }))
  specs.set(store as Feed<unknown>, spec as FeedSpec<unknown>)
  return store
}

function message(err: unknown): string {
  if (err instanceof BridgeError) return err.status === 0 ? err.message : `${err.message} (HTTP ${err.status})`
  return err instanceof Error ? err.message : 'Something went wrong'
}

/** Mount where the feed is shown: loads on mode change, then polls (live) or evolves (demo) while mounted. */
export function useFeed<T>(feed: Feed<T>): FeedState<T> {
  const mode = useMode((s) => s.mode)
  const bridge = useMode((s) => s.bridge)
  const state = feed()

  useEffect(() => {
    if (bridge === 'unknown') return
    const spec = specs.get(feed as Feed<unknown>) as FeedSpec<T> | undefined
    if (!spec) return
    let stopped = false
    const ctl = new AbortController()

    if (mode === 'demo') {
      const cur = feed.getState()
      if (cur.mode !== 'demo' || !cur.data) feed.setState({ data: spec.demo(), mode, status: 'ready', error: null, at: Date.now() })
      if (!spec.tick) return
      const id = window.setInterval(() => {
        const d = feed.getState().data
        if (d) feed.setState({ data: spec.tick!(d), at: Date.now() })
      }, spec.tickMs ?? 3000)
      return () => window.clearInterval(id)
    }

    const load = async () => {
      if (feed.getState().mode !== 'live') feed.setState({ data: null, mode, status: 'loading', error: null, at: null })
      try {
        const data = await api<T>(spec.path, { signal: ctl.signal })
        if (!stopped) feed.setState({ data, mode, status: 'ready', error: null, at: Date.now() })
      } catch (err) {
        if (stopped) return
        const keep = feed.getState().data
        feed.setState({ status: keep ? 'ready' : 'error', error: message(err) })
      }
    }
    void load()
    const id = window.setInterval(() => void load(), spec.everyMs)
    return () => { stopped = true; ctl.abort(); window.clearInterval(id) }
  }, [feed, mode, bridge])

  return state
}

/** Re-read a feed now (after a write), in live mode; demo feeds are changed in place by their callers. */
export async function reloadFeed<T>(feed: Feed<T>): Promise<void> {
  const spec = specs.get(feed as Feed<unknown>) as FeedSpec<T> | undefined
  if (!spec || feed.getState().mode !== 'live') return
  try {
    const data = await api<T>(spec.path)
    feed.setState({ data, status: 'ready', error: null, at: Date.now() })
  } catch (err) {
    feed.setState({ error: message(err) })
  }
}
