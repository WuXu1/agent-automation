import { useFrame, useThree, type ThreeEvent } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { MemoryGraph } from '@/telemetry/graph'
import { pulseKind, pulseStrength } from '@/telemetry/pulses'
import type { ClusterId, SearchHit } from '@/telemetry/types'

const pickGeometry = new THREE.IcosahedronGeometry(1, 1)
const pickMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false })
const dummy = new THREE.Object3D()
const tmp = new THREE.Color()
const WHITE = new THREE.Color('#ffffff')
const VIOLET = new THREE.Color('#d946ef')

/** A memory drawn as a star: a hot core, a soft halo and four faint spikes, all in one point sprite. */
const starVertex = /* glsl */ `
  attribute vec3 aColor;
  attribute float aSize;
  uniform float uScale;
  varying vec3 vColor;
  void main() {
    vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * uScale / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`
const starFragment = /* glsl */ `
  varying vec3 vColor;
  void main() {
    vec2 p = gl_PointCoord - 0.5;
    float d = length(p);
    if (d > 0.5) discard;
    float core = exp(-d * d * 260.0);
    float halo = exp(-d * d * 22.0) * 0.55;
    float spikes = (exp(-abs(p.x) * 70.0) + exp(-abs(p.y) * 70.0)) * exp(-d * 7.0) * 0.28;
    float a = core + halo + spikes;
    gl_FragColor = vec4(vColor * a + core * 0.35, a);
  }
`

interface Props {
  graph: MemoryGraph
  hits: SearchHit[] | null
  selectedId: string | null
  hoveredId: string | null
  focusCluster: ClusterId | null
  onHover: (id: string | null) => void
  onSelect: (id: string) => void
}

/**
 * Every memory as a star (a point sprite, additive, so neighbours glow together); colour above 1.0 is what the bloom picks up.
 * Picking uses an invisible instanced sphere per memory, a little larger than the star, so they are easy to click.
 */
export function Nodes({ graph, hits, selectedId, hoveredId, focusCluster, onHover, onSelect }: Props) {
  const pick = useRef<THREE.InstancedMesh>(null)
  const count = graph.nodes.length
  const dpr = useThree((s) => s.viewport.dpr)
  const height = useThree((s) => s.size.height)
  const base = useMemo(() => graph.nodes.map((n) => new THREE.Color(graph.sectionById.get(n.cluster)?.color ?? '#00f0ff')), [graph])
  const hitScore = useMemo(() => new Map(hits?.map((h) => [h.id, h.score]) ?? []), [hits])
  const neighbours = useMemo(
    () => new Set(selectedId ? (graph.neighbours.get(selectedId) ?? []).map((n) => n.id) : []),
    [graph, selectedId],
  )

  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    const pos = new Float32Array(count * 3)
    graph.nodes.forEach((n, i) => pos.set(n.position, i * 3))
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('aColor', new THREE.BufferAttribute(new Float32Array(count * 3), 3))
    g.setAttribute('aSize', new THREE.BufferAttribute(new Float32Array(count), 1))
    return g
  }, [graph, count])
  useEffect(() => () => geometry.dispose(), [geometry])

  const material = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: starVertex, fragmentShader: starFragment, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, uniforms: { uScale: { value: 1 } },
  }), [])
  useEffect(() => () => material.dispose(), [material])
  // point sizes are in pixels: scale with the canvas height (the camera's vertical view) and the pixel ratio
  // oxlint-disable-next-line react/immutability -- three.js uniforms are mutated per frame by design
  useEffect(() => { material.uniforms.uScale!.value = height * dpr * 0.92 }, [material, height, dpr])

  useEffect(() => {
    const m = pick.current
    if (!m) return
    graph.nodes.forEach((n, i) => {
      dummy.position.set(...n.position)
      dummy.scale.setScalar(Math.max(0.16, n.size * 1.8))
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
    })
    m.instanceMatrix.needsUpdate = true
    m.computeBoundingSphere()
  }, [graph])

  useFrame(({ clock }) => {
    if (count === 0) return
    const col = geometry.getAttribute('aColor') as THREE.BufferAttribute
    const size = geometry.getAttribute('aSize') as THREE.BufferAttribute
    const now = performance.now()
    const t = clock.elapsedTime
    for (let i = 0; i < count; i++) {
      const n = graph.nodes[i]!
      const p = pulseStrength(n.id, now)
      const selected = n.id === selectedId
      const hovered = n.id === hoveredId
      const score = hitScore.get(n.id)

      // Dim what is not in play: other clusters when one is focused, non-hits while a search is shown.
      let dim = 1
      if (focusCluster && n.cluster !== focusCluster) dim = 0.14
      if (hits) dim = score === undefined ? 0.1 : 0.5 + score
      if (selectedId && !selected && !neighbours.has(n.id)) dim = Math.min(dim, 0.3)

      const glow = selected ? 2.4 : hovered ? 2.1 : neighbours.has(n.id) ? 1.5 : 1.05 + p * 1.6
      // each star breathes on its own clock, so the sky is never still
      const twinkle = 1 + Math.sin(t * (0.9 + (i % 7) * 0.13) + i * 1.7) * 0.12
      tmp.copy(base[i] as THREE.Color).multiplyScalar(dim * glow * twinkle)
      if (p > 0) tmp.lerp(pulseKind(n.id) === 'read' ? VIOLET : WHITE, p * 0.45)
      col.setXYZ(i, tmp.r, tmp.g, tmp.b)
      const s = n.size * 7.2 * (selected ? 1.7 : hovered ? 1.5 : 1) * (1 + p * 0.8) * (score !== undefined ? 1 + score * 0.6 : 1)
      size.setX(i, s * (0.94 + twinkle * 0.06))
    }
    col.needsUpdate = true
    size.needsUpdate = true
  })

  if (count === 0) return null

  const idAt = (e: ThreeEvent<PointerEvent | MouseEvent>) =>
    e.instanceId === undefined ? null : (graph.nodes[e.instanceId]?.id ?? null)

  return (
    <>
      <points geometry={geometry} material={material} raycast={() => null} frustumCulled={false} />
      <instancedMesh
        key={count}
        ref={pick}
        args={[pickGeometry, pickMaterial, count]}
        onPointerMove={(e) => { e.stopPropagation(); onHover(idAt(e)) }}
        onPointerOut={() => onHover(null)}
        onClick={(e) => { e.stopPropagation(); const id = idAt(e); if (id) onSelect(id) }}
      />
    </>
  )
}
