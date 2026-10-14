import { Html } from '@react-three/drei'
import type { MemoryGraph } from '@/telemetry/graph'
import type { ClusterId, Memory } from '@/telemetry/types'

interface Props {
  visible: boolean
  graph: MemoryGraph
  memories: Memory[]
  hoveredId: string | null
  selectedId: string | null
  focusCluster: ClusterId | null
}

/** Theme names by each cluster (above and below in turn, so neighbouring themes never stack their names), and the hovered
 * memory's first line. DOM text, so it stays crisp. */
// drei's <Html> throws on unmount when its siblings unmount in the same commit (R3F 9), so labels stay mounted
// and hide with CSS; the hover tooltip is one permanent label that moves.
export function Labels({ visible, graph, memories, hoveredId, selectedId, focusCluster }: Props) {
  const counts = new Map<ClusterId, number>()
  const top = new Map<ClusterId, number>()
  const bottom = new Map<ClusterId, number>()
  for (const n of graph.nodes) {
    counts.set(n.cluster, (counts.get(n.cluster) ?? 0) + 1)
    top.set(n.cluster, Math.max(top.get(n.cluster) ?? -Infinity, n.position[1]))
    bottom.set(n.cluster, Math.min(bottom.get(n.cluster) ?? Infinity, n.position[1]))
  }
  const hovered = hoveredId && hoveredId !== selectedId ? graph.byId.get(hoveredId) : undefined
  const hoveredText = hovered ? memories[hovered.index]?.text : undefined

  return (
    <>
      {graph.sections.map((c, i) => {
        const at = graph.centres.get(c.id)
        const n = counts.get(c.id) ?? 0
        if (!at) return null
        const faded = (focusCluster && focusCluster !== c.id) || selectedId
        const opacity = !visible || n === 0 ? 0 : faded ? 0.25 : 1
        return (
          <Html key={c.id} center position={[at[0], i % 2 ? (bottom.get(c.id) ?? at[1]) - 0.8 : (top.get(c.id) ?? at[1]) + 0.9, at[2]]} style={{ pointerEvents: 'none' }} zIndexRange={[4, 0]}>
            <div className="flex items-center gap-1.5 rounded-full border border-white/[0.06] bg-[#05070a]/55 px-2.5 py-1 whitespace-nowrap backdrop-blur-sm transition-opacity duration-200 select-none" style={{ opacity }}>
              <span className="size-1.5 rounded-full" style={{ background: c.color, boxShadow: `0 0 8px ${c.color}` }} />
              <span className="text-[11px] font-medium tracking-[-0.005em] text-ink">{c.label}</span>
              <span className="num text-[10px] text-ink-faint">{n}</span>
            </div>
          </Html>
        )
      })}
      <Html position={hovered?.position ?? [0, 0, 0]} style={{ pointerEvents: 'none' }} zIndexRange={[6, 0]}>
        <div
          className="glass ml-3 -translate-y-1/2 px-3 py-2 text-[12px] leading-snug text-ink"
          style={{ width: 'max-content', maxWidth: 280, visibility: visible && hovered && hoveredText ? 'visible' : 'hidden' }}
        >
          <span className="line-clamp-3">{hoveredText}</span>
        </div>
      </Html>
    </>
  )
}
