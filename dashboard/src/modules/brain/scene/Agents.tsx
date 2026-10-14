import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { isAgentId, useRoster } from '@/telemetry/agents'
import type { MemoryGraph } from '@/telemetry/graph'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { useCrew } from '@/telemetry/crew'
import type { AgentId } from '@/telemetry/types'

/** The chief watches from the zenith; everyone else sits evenly on a halo above and outside the themes, however many there
 * are, so their names never sit on top of a theme's. */
export function stations(ids: readonly AgentId[], chief: AgentId): Map<AgentId, THREE.Vector3> {
  const out = new Map<AgentId, THREE.Vector3>([[chief, new THREE.Vector3(0, 9.6, -1)]])
  const ring = ids.filter((id) => id !== chief)
  const r = 12.5 + Math.max(0, ring.length - 8) * 0.35
  ring.forEach((id, i) => {
    const a = (i / Math.max(1, ring.length)) * Math.PI * 2 + Math.PI / 4
    out.set(id, new THREE.Vector3(Math.cos(a) * r, 6.4 + Math.sin(a * 2) * 0.5, Math.sin(a) * r * 0.62))
  })
  return out
}

const VIOLET = new THREE.Color('#d946ef')
const POOL = 24
const SEG = 40
const GROW_MS = 420
const LIFE_MS = 1900

interface Arc {
  line: THREE.Line
  born: number
}

/** Violet arcs from an agent to the memories it just read, drawn outwards then faded. A fixed pool, no allocation per event. */
function makeArc(): Arc {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array((SEG + 1) * 3), 3))
  g.setDrawRange(0, 0)
  const m = new THREE.LineBasicMaterial({ color: VIOLET, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false })
  const line = new THREE.Line(g, m)
  line.raycast = () => null
  return { line, born: -Infinity }
}

function useArcs(graph: MemoryGraph, where: Map<AgentId, THREE.Vector3>) {
  const group = useRef<THREE.Group>(null)
  const pool = useRef<Arc[]>([])
  const next = useRef(0)
  const graphRef = useRef(graph)
  const whereRef = useRef(where)

  useEffect(() => { graphRef.current = graph }, [graph])
  useEffect(() => { whereRef.current = where }, [where])

  useEffect(() => {
    const g = group.current
    if (!g) return
    const arcs = Array.from({ length: POOL }, makeArc)
    pool.current = arcs
    for (const a of arcs) g.add(a.line)
    return () => {
      for (const a of arcs) { g.remove(a.line); a.line.geometry.dispose(); (a.line.material as THREE.Material).dispose() }
      pool.current = []
    }
  }, [])

  useEffect(() => useBrain.subscribe((s, prev) => {
    const e = s.events[0]
    if (!e || e === prev.events[0] || !isAgentId(e.agent) || (e.kind !== 'read' && e.kind !== 'search')) return
    const from = whereRef.current.get(e.agent)
    if (!from) return
    const curve = new THREE.QuadraticBezierCurve3()
    for (const id of e.memoryIds) {
      const node = graphRef.current.byId.get(id)
      if (!node) continue
      const to = new THREE.Vector3(...node.position)
      const mid = from.clone().add(to).multiplyScalar(0.5)
      mid.y += 2.2
      curve.v0.copy(from); curve.v1.copy(mid); curve.v2.copy(to)
      const arc = pool.current[next.current++ % POOL]
      if (!arc) return
      const attr = arc.line.geometry.getAttribute('position') as THREE.BufferAttribute
      curve.getPoints(SEG).forEach((p, i) => attr.setXYZ(i, p.x, p.y, p.z))
      attr.needsUpdate = true
      arc.line.geometry.computeBoundingSphere()
      arc.born = performance.now()
    }
  }), [])

  // three.js objects are mutated per frame by design (React Three Fiber's model); the React lint rule cannot see that.
  useFrame(() => {
    const now = performance.now()
    for (const a of pool.current) {
      const age = now - a.born
      const m = a.line.material as THREE.LineBasicMaterial
      // oxlint-disable-next-line react/immutability
      if (age > LIFE_MS) { if (m.opacity !== 0) { m.opacity = 0; a.line.geometry.setDrawRange(0, 0) } continue }
      const grow = Math.min(1, age / GROW_MS)
      a.line.geometry.setDrawRange(0, Math.ceil((1 - (1 - grow) ** 3) * (SEG + 1)))
      m.opacity = age < GROW_MS ? 0.9 : 0.9 * (1 - (age - GROW_MS) / (LIFE_MS - GROW_MS))
    }
  })

  return group
}

export function Agents({ graph, labels }: { graph: MemoryGraph; labels: boolean }) {
  const roster = useRoster((s) => s.list)
  const chief = useCrew((s) => s.crew.chief)
  const where = useMemo(() => stations(roster.map((a) => a.id), chief), [roster, chief])
  const arcs = useArcs(graph, where)
  const halo = useRef<THREE.Group>(null)

  useFrame(({ clock }) => {
    halo.current?.children.forEach((c, i) => { c.rotation.y = clock.elapsedTime * 0.4 + i; c.rotation.x = clock.elapsedTime * 0.25 })
  })

  return (
    <>
      <group ref={arcs} />
      <group ref={halo}>
        {roster.map((a) => (
          <group key={a.id} position={where.get(a.id)}>
            <mesh scale={a.id === chief ? 0.34 : 0.24} raycast={() => null}>
              <torusGeometry args={[1, 0.035, 6, 48]} />
              <meshBasicMaterial color={VIOLET.clone().multiplyScalar(1.5)} toneMapped={false} transparent opacity={0.85} />
            </mesh>
          </group>
        ))}
      </group>
      {roster.map((a) => (
        <group key={a.id} position={where.get(a.id)}>
          <mesh scale={a.id === chief ? 0.085 : 0.06} raycast={() => null}>
            <sphereGeometry args={[1, 12, 12]} />
            <meshBasicMaterial color={VIOLET.clone().multiplyScalar(2.4)} toneMapped={false} />
          </mesh>
          <Html center position={[0, a.id === chief ? -0.62 : -0.48, 0]} style={{ pointerEvents: 'none' }} zIndexRange={[5, 0]}>
            <div className="text-center whitespace-nowrap transition-opacity duration-200 select-none" style={{ opacity: labels ? 0.85 : 0 }}>
              <div className="text-[10.5px] font-semibold tracking-[0.01em] text-[#f0abfc]">{a.name}</div>
              {a.id === chief && <div className="text-[9.5px] text-ink-faint">{a.role}</div>}
            </div>
          </Html>
        </group>
      ))}
    </>
  )
}
