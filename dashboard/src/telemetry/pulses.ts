// Transient "this memory was just touched" signals. Written by the stores, read every frame by the 3D scene.
// Kept outside React state on purpose: a pulse should never re-render the page.

export type PulseKind = 'read' | 'write' | 'hit'

const pulses = new Map<string, { at: number; kind: PulseKind }>()

export function pulse(ids: readonly string[], kind: PulseKind = 'read'): void {
  const at = performance.now()
  for (const id of ids) pulses.set(id, { at, kind })
}

/** 0..1 strength of the pulse on `id` right now (1 at the moment it fired, fading over `durMs`). */
export function pulseStrength(id: string, now: number, durMs = 1800): number {
  const p = pulses.get(id)
  if (!p) return 0
  const t = (now - p.at) / durMs
  if (t >= 1) {
    pulses.delete(id)
    return 0
  }
  return 1 - t
}

export function pulseKind(id: string): PulseKind | null {
  return pulses.get(id)?.kind ?? null
}
