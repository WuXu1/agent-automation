import { create } from 'zustand'
import type { ClusterId } from '@/telemetry/types'

interface BrainUi {
  selectedId: string | null
  hoveredId: string | null
  focusCluster: ClusterId | null
  composing: boolean
  select: (id: string | null) => void
  hover: (id: string | null) => void
  focus: (cluster: ClusterId | null) => void
  compose: (open: boolean) => void
}

export const useBrainUi = create<BrainUi>((set) => ({
  selectedId: null,
  hoveredId: null,
  focusCluster: null,
  composing: false,
  select: (selectedId) => set({ selectedId, composing: false }),
  hover: (hoveredId) => set({ hoveredId }),
  focus: (focusCluster) => set({ focusCluster }),
  compose: (composing) => set({ composing, selectedId: null }),
}))
