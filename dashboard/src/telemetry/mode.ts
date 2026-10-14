import { create } from 'zustand'
import { api } from './live/client'
import type { Mode } from './types'

type Bridge = 'unknown' | 'up' | 'down'

interface ModeState {
  mode: Mode
  bridge: Bridge
  bridgeVersion: string | null
  setMode: (mode: Mode) => void
  probe: () => Promise<void>
}

const KEY = 'hermes-command.mode'

function remembered(): Mode | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'demo' || v === 'live' ? v : null
  } catch {
    return null
  }
}

export const useMode = create<ModeState>((set, get) => ({
  mode: 'demo',
  bridge: 'unknown',
  bridgeVersion: null,
  setMode: (mode) => {
    try { localStorage.setItem(KEY, mode) } catch { /* private window */ }
    set({ mode })
  },
  // Live by default when the bridge answers, unless demo was picked last time.
  probe: async () => {
    try {
      const h = await api<{ ok: boolean; version: string }>('/health', { timeoutMs: 2500 })
      set({ bridge: h.ok ? 'up' : 'down', bridgeVersion: h.version ?? null })
    } catch {
      set({ bridge: 'down' })
    }
    const wanted = remembered()
    const up = get().bridge === 'up'
    set({ mode: up && wanted !== 'demo' ? 'live' : 'demo' })
  },
}))
