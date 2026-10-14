import { create } from 'zustand'
import { setSound } from '@/lib/sound'
import { VIEW_BY_ID, type ViewId } from './views'

interface AppState {
  view: ViewId
  paletteOpen: boolean
  sound: boolean
  /** The left rail shrunk to icons (remembered per browser). */
  railCollapsed: boolean
  toggleRail: () => void
  go: (view: ViewId) => void
  setPalette: (open: boolean) => void
  toggleSound: () => void
}

function fromHash(): ViewId {
  const id = window.location.hash.replace(/^#\/?/, '') as ViewId
  return VIEW_BY_ID.has(id) ? id : 'brain'
}

/** The rail's width on a laptop, open and collapsed (the 3D sky centres itself on the rest of the page). */
export const RAIL_W = { open: 224, collapsed: 76 } as const

function storedRail(): boolean {
  try { return window.localStorage.getItem('hermes-dash:rail') === 'collapsed' } catch { return false }
}

export const useApp = create<AppState>((set, get) => ({
  view: fromHash(),
  paletteOpen: false,
  sound: false,
  railCollapsed: storedRail(),
  toggleRail: () => {
    const railCollapsed = !get().railCollapsed
    try { window.localStorage.setItem('hermes-dash:rail', railCollapsed ? 'collapsed' : 'open') } catch { /* only a convenience */ }
    set({ railCollapsed })
  },
  go: (view) => {
    if (get().view === view) return
    window.history.pushState(null, '', `#/${view}`)
    set({ view })
  },
  setPalette: (paletteOpen) => set({ paletteOpen }),
  toggleSound: () => {
    const sound = !get().sound
    setSound(sound)
    set({ sound })
  },
}))

window.addEventListener('popstate', () => useApp.setState({ view: fromHash() }))
