import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import type { MemoryGraph } from '@/telemetry/graph'
import type { ClusterId, SearchHit } from '@/telemetry/types'

const CYAN = new THREE.Color('#00f0ff')
const SEG = 14

/**
 * Links between related memories (shared words), drawn as gentle arcs and blended from each end's theme colour; additive so
 * crossings glow. Now and then a signal runs along a link (a bright bead, timed by the shader), so the web looks alive.
 * Links inside a theme are stronger than links across themes, which stay a faint haze.
 */
const vertex = /* glsl */ `
  attribute vec3 aColor;
  attribute vec2 aFlow;   // position along the link 0..1, the link's own phase
  varying vec3 vColor;
  varying vec2 vFlow;
  void main() {
    vColor = aColor;
    vFlow = aFlow;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`
const fragment = /* glsl */ `
  uniform float uTime;
  uniform float uSignal;
  varying vec3 vColor;
  varying vec2 vFlow;
  void main() {
    // one bead per link, travelling end to end every few seconds, resting in between
    float head = fract(uTime * 0.16 + vFlow.y) * 2.6 - 0.8;
    float bead = exp(-pow((vFlow.x - head) * 9.0, 2.0)) * uSignal;
    gl_FragColor = vec4(vColor * (1.0 + bead * 3.2), 1.0);
  }
`

/** Arc points for one link: lifted at the middle by a share of its length, so long cross-theme links bow over the sky. */
function arc(a: readonly number[], b: readonly number[], lift: number): THREE.Vector3[] {
  const va = new THREE.Vector3(a[0], a[1], a[2])
  const vb = new THREE.Vector3(b[0], b[1], b[2])
  const mid = va.clone().add(vb).multiplyScalar(0.5)
  mid.y += va.distanceTo(vb) * lift
  return new THREE.QuadraticBezierCurve3(va, mid, vb).getPoints(SEG)
}

function lineGeometry(pairs: Array<{ a: readonly number[]; b: readonly number[]; lift: number; phase: number }>) {
  const pos = new Float32Array(pairs.length * SEG * 6)
  const flow = new Float32Array(pairs.length * SEG * 4)
  pairs.forEach((p, i) => {
    const pts = arc(p.a, p.b, p.lift)
    for (let s = 0; s < SEG; s++) {
      const o = (i * SEG + s)
      pos.set([pts[s]!.x, pts[s]!.y, pts[s]!.z, pts[s + 1]!.x, pts[s + 1]!.y, pts[s + 1]!.z], o * 6)
      flow.set([s / SEG, p.phase, (s + 1) / SEG, p.phase], o * 4)
    }
  })
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  g.setAttribute('aColor', new THREE.BufferAttribute(new Float32Array(pairs.length * SEG * 6), 3))
  g.setAttribute('aFlow', new THREE.BufferAttribute(flow, 2))
  return g
}

function material() {
  return new THREE.ShaderMaterial({
    vertexShader: vertex, fragmentShader: fragment, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uSignal: { value: 1 } },
  })
}

interface Props {
  graph: MemoryGraph
  hits: SearchHit[] | null
  selectedId: string | null
  focusCluster: ClusterId | null
  reduced: boolean
}

export function Edges({ graph, hits, selectedId, focusCluster, reduced }: Props) {
  const geometry = useMemo(() => lineGeometry(graph.edges.map((e, i) => {
    const same = graph.nodes[e.a]!.cluster === graph.nodes[e.b]!.cluster
    return { a: graph.nodes[e.a]!.position, b: graph.nodes[e.b]!.position, lift: same ? 0.08 : 0.22, phase: (i * 0.618) % 1 }
  })), [graph])

  // Selected memory: arcs to its closest neighbours, drawn brighter on top, with their signals flowing out of it.
  const focusLinks = useMemo(() => {
    const from = selectedId ? graph.byId.get(selectedId) : undefined
    const list = from ? (graph.neighbours.get(from.id) ?? []) : []
    return list.flatMap((n, i) => { const to = graph.byId.get(n.id); return from && to ? [{ a: from.position, b: to.position, lift: 0.12, phase: i * 0.13, w: n.weight }] : [] })
  }, [graph, selectedId])
  const focus = useMemo(() => {
    const g = lineGeometry(focusLinks)
    const col = g.getAttribute('aColor') as THREE.BufferAttribute
    focusLinks.forEach((l, i) => {
      const c = CYAN.clone().multiplyScalar(0.6 + l.w * 1.6)
      for (let v = 0; v < SEG * 2; v++) col.setXYZ(i * SEG * 2 + v, c.r, c.g, c.b)
    })
    return g
  }, [focusLinks])

  const mats = useMemo(() => [material(), material()] as const, [])
  useEffect(() => () => mats.forEach((m) => m.dispose()), [mats])

  useEffect(() => {
    const attr = geometry.getAttribute('aColor') as THREE.BufferAttribute
    const hit = hits ? new Set(hits.map((h) => h.id)) : null
    const a = new THREE.Color()
    const b = new THREE.Color()
    const c = new THREE.Color()
    graph.edges.forEach((e, i) => {
      const na = graph.nodes[e.a]!
      const nb = graph.nodes[e.b]!
      const same = na.cluster === nb.cluster
      let k = (same ? 0.2 : 0.07) + e.weight * (same ? 0.5 : 0.22)
      if (focusCluster && na.cluster !== focusCluster && nb.cluster !== focusCluster) k *= 0.12
      if (hit && !(hit.has(na.id) && hit.has(nb.id))) k *= hit.has(na.id) || hit.has(nb.id) ? 0.4 : 0.06
      if (selectedId) k *= 0.4
      a.set(graph.sectionById.get(na.cluster)?.color ?? '#00f0ff').multiplyScalar(k)
      b.set(graph.sectionById.get(nb.cluster)?.color ?? '#00f0ff').multiplyScalar(k)
      for (let s = 0; s < SEG; s++) {
        c.copy(a).lerp(b, s / SEG)
        attr.setXYZ((i * SEG + s) * 2, c.r, c.g, c.b)
        c.copy(a).lerp(b, (s + 1) / SEG)
        attr.setXYZ((i * SEG + s) * 2 + 1, c.r, c.g, c.b)
      }
    })
    attr.needsUpdate = true
  }, [geometry, graph, hits, selectedId, focusCluster])

  useEffect(() => () => geometry.dispose(), [geometry])
  useEffect(() => () => focus.dispose(), [focus])

  useFrame((_, dt) => {
    // oxlint-disable-next-line react/immutability -- three.js uniforms are mutated per frame by design
    if (reduced) { mats[0].uniforms.uSignal!.value = 0; mats[1].uniforms.uSignal!.value = 0; return }
    mats[0].uniforms.uTime!.value += Math.min(dt, 0.1)
    mats[1].uniforms.uTime!.value += Math.min(dt, 0.1) * 2.2
  })

  return (
    <>
      <lineSegments geometry={geometry} material={mats[0]} raycast={() => null} frustumCulled={false} />
      <lineSegments geometry={focus} material={mats[1]} raycast={() => null} frustumCulled={false} />
    </>
  )
}
