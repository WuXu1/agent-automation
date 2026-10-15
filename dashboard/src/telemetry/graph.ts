import { BUILTIN_SECTIONS, classify, tokens, type Section } from './clusters'
import { teamNow } from './team'
import type { ClusterId, Memory } from './types'
import { hash, rng } from '@/lib/rng'

export interface GraphNode {
  id: string
  index: number
  cluster: ClusterId
  position: [number, number, number]
  size: number
}

export interface GraphEdge {
  a: number
  b: number
  weight: number
}

export interface Neighbour {
  id: string
  weight: number
}

export interface MemoryGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  byId: Map<string, GraphNode>
  neighbours: Map<string, Neighbour[]>
  centres: Map<ClusterId, [number, number, number]>
  sections: Section[]
  sectionById: Map<ClusterId, Section>
}

const STOP = new Set(('the a an and or of to in on at for with is are was be he his him she her s it that this as by from not ' +
  'when if has have had will can should into about than then there their they them who what which also only one').split(' '))

function contentWords(text: string): Set<string> {
  const owner = teamNow().owner.name.toLowerCase()            // notes are written about the owner: their name links nothing
  return new Set(tokens(text).filter((w) => w.length > 2 && !STOP.has(w) && w !== owner))
}

function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0
  let shared = 0
  for (const w of a) if (b.has(w)) shared++
  return shared / (a.size + b.size - shared)
}

/** Cluster centres sit on a tilted ring, alternately raised and lowered, like a constellation band across the sky. A brain
 * with more sections gets a wider ring, so they keep their distance. */
function centres(sections: readonly Section[]): Map<ClusterId, [number, number, number]> {
  const out = new Map<ClusterId, [number, number, number]>()
  sections.forEach((c, i) => {
    const t = (i / sections.length) * Math.PI * 2 + 0.35
    const r = 7.6 * Math.max(1, Math.sqrt(sections.length / 6))
    out.set(c.id, [Math.cos(t) * r, (i % 2 ? 1.5 : -1.3) + Math.sin(t) * 0.8, Math.sin(t) * r * 0.85])
  })
  return out
}

/** Positions are seeded by each memory's id, so a node keeps its place across reloads and edits. */
export function buildGraph(memories: readonly Memory[], sections: readonly Section[] = BUILTIN_SECTIONS,
                           assign: Readonly<Record<string, ClusterId>> = {}): MemoryGraph {
  const centre = centres(sections)
  const ids = new Set(sections.map((s) => s.id))
  const fallback = ids.has('rules') ? 'rules' : sections[0]?.id ?? 'rules'
  const counts = new Map<ClusterId, number>()
  // Where the AI sorted it (bridge/brain.py); a note it has not seen yet goes by keywords until it has.
  const clusterOf = memories.map((m) => {
    const a = assign[m.id]
    if (a && ids.has(a)) return a
    const k = classify(m)
    return ids.has(k) ? k : fallback
  })
  for (const c of clusterOf) counts.set(c, (counts.get(c) ?? 0) + 1)

  const newest = memories.reduce((max, m) => Math.max(max, m.updatedAt ?? m.createdAt), 0)
  const nodes: GraphNode[] = memories.map((m, index) => {
    const cluster = clusterOf[index] as ClusterId
    const [cx, cy, cz] = centre.get(cluster) as [number, number, number]
    const r = rng(hash(m.id))
    const spread = 1.1 + Math.sqrt(counts.get(cluster) ?? 1) * 0.28
    // Uniform direction, radius biased to the core so clusters read as dense centres with a halo.
    const u = r() * 2 - 1
    const phi = r() * Math.PI * 2
    const rad = spread * Math.cbrt(r()) * (0.55 + r() * 0.45)
    const s = Math.sqrt(1 - u * u)
    const ageDays = (newest - (m.updatedAt ?? m.createdAt)) / 86_400_000
    return {
      id: m.id,
      index,
      cluster,
      position: [cx + s * Math.cos(phi) * rad, cy + u * rad * 0.8, cz + s * Math.sin(phi) * rad],
      size: 0.075 + Math.min(m.text.length, 240) / 240 * 0.06 + (ageDays < 2 ? 0.03 : 0),
    }
  })

  const words = memories.map((m) => contentWords(m.text))
  const neighbours = new Map<string, Neighbour[]>()
  const seen = new Set<string>()
  const edges: GraphEdge[] = []
  for (let i = 0; i < nodes.length; i++) {
    const scored: Array<{ j: number; w: number }> = []
    for (let j = 0; j < nodes.length; j++) {
      if (i === j) continue
      let w = jaccard(words[i] as Set<string>, words[j] as Set<string>)
      if (nodes[i]?.cluster === nodes[j]?.cluster) w += 0.04
      if (w >= 0.06) scored.push({ j, w })
    }
    scored.sort((x, y) => y.w - x.w)
    const top = scored.slice(0, 5)
    neighbours.set(nodes[i]!.id, top.map(({ j, w }) => ({ id: nodes[j]!.id, weight: Math.min(1, w) })))
    for (const { j, w } of top.slice(0, 2)) {
      if (w < 0.1) continue
      const key = i < j ? `${i}:${j}` : `${j}:${i}`
      if (seen.has(key)) continue
      seen.add(key)
      edges.push({ a: i, b: j, weight: Math.min(1, w) })
    }
  }

  // Constellation lines: every note also joins its nearest neighbour in space within its theme.
  for (let i = 0; i < nodes.length; i++) {
    const a = nodes[i]!
    let best = -1
    let bestD = Infinity
    for (let j = 0; j < nodes.length; j++) {
      const b = nodes[j]!
      if (i === j || b.cluster !== a.cluster) continue
      const d = (a.position[0] - b.position[0]) ** 2 + (a.position[1] - b.position[1]) ** 2 + (a.position[2] - b.position[2]) ** 2
      if (d < bestD) { bestD = d; best = j }
    }
    if (best < 0) continue
    const key = i < best ? `${i}:${best}` : `${best}:${i}`
    if (seen.has(key)) continue
    seen.add(key)
    edges.push({ a: i, b: best, weight: 0.08 })
  }

  return { nodes, edges, byId: new Map(nodes.map((n) => [n.id, n])), neighbours, centres: centre,
    sections: [...sections], sectionById: new Map(sections.map((s) => [s.id, s])) }
}
