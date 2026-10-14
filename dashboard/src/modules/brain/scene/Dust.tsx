import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { hash, rng } from '@/lib/rng'
import type { MemoryGraph } from '@/telemetry/graph'
import type { ClusterId } from '@/telemetry/types'
import { glow } from './Backdrop'

/**
 * The nebula: a cloud of fine dust around every theme, in its colour, turning slowly about the theme's centre (inner dust
 * faster than outer, like a small galaxy), plus loose motes drifting through the whole sky. All motion is in the vertex
 * shader, so thousands of particles cost one draw call each and nothing per frame on the CPU.
 */

const vertex = /* glsl */ `
  attribute vec3 aCentre;
  attribute vec3 aColor;
  attribute vec4 aOrbit;   // radius, start angle, height, speed
  attribute float aSize;
  uniform float uTime;
  uniform float uScale;
  varying vec3 vColor;
  varying float vFade;
  void main() {
    float a = aOrbit.y + uTime * aOrbit.w;
    float bob = sin(uTime * 0.4 + aOrbit.y * 3.0) * 0.12;
    vec3 p = aCentre + vec3(cos(a) * aOrbit.x, aOrbit.z + bob, sin(a) * aOrbit.x * 0.85);
    vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    // fade out far away and right in front of the camera (no big blurry blobs when zoomed in)
    vFade = smoothstep(70.0, 18.0, -mv.z) * smoothstep(1.5, 5.0, -mv.z);
    gl_PointSize = min(aSize * uScale / -mv.z, 7.0 * uScale / 900.0);
    gl_Position = projectionMatrix * mv;
  }
`
const fragment = /* glsl */ `
  uniform float uDim;
  varying vec3 vColor;
  varying float vFade;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float a = exp(-d * d * 18.0) * vFade * uDim;
    gl_FragColor = vec4(vColor * a, a);
  }
`

function makeMaterial() {
  return new THREE.ShaderMaterial({
    vertexShader: vertex, fragmentShader: fragment, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uScale: { value: 1 }, uDim: { value: 1 } },
  })
}

interface Cloud { geometry: THREE.BufferGeometry; cluster: ClusterId | null }

function build(n: number, fill: (i: number, set: (centre: number[], color: THREE.Color, orbit: number[], size: number) => void) => void) {
  const centre = new Float32Array(n * 3)
  const color = new Float32Array(n * 3)
  const orbit = new Float32Array(n * 4)
  const size = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    fill(i, (c, col, o, s) => {
      centre.set(c, i * 3)
      color.set([col.r, col.g, col.b], i * 3)
      orbit.set(o, i * 4)
      size[i] = s
    })
  }
  const g = new THREE.BufferGeometry()
  // position is unused by the shader but three needs it to know how many points to draw
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3))
  g.setAttribute('aCentre', new THREE.BufferAttribute(centre, 3))
  g.setAttribute('aColor', new THREE.BufferAttribute(color, 3))
  g.setAttribute('aOrbit', new THREE.BufferAttribute(orbit, 4))
  g.setAttribute('aSize', new THREE.BufferAttribute(size, 1))
  return g
}

export function Dust({ graph, focusCluster, selectedId, reduced }: { graph: MemoryGraph; focusCluster: ClusterId | null; selectedId: string | null; reduced: boolean }) {
  const dpr = useThree((s) => s.viewport.dpr)
  const height = useThree((s) => s.size.height)

  const clouds = useMemo<Cloud[]>(() => {
    const counts = new Map<ClusterId, number>()
    for (const n of graph.nodes) counts.set(n.cluster, (counts.get(n.cluster) ?? 0) + 1)
    const out: Cloud[] = []
    for (const s of graph.sections) {
      const at = graph.centres.get(s.id)
      const k = counts.get(s.id) ?? 0
      if (!at || k === 0) continue
      const r = rng(hash(`dust:${s.id}`))
      const spread = 1.5 + Math.sqrt(k) * 0.36
      const tint = new THREE.Color(s.color)
      const n = Math.min(320, 90 + k * 9)
      const geometry = build(n, (_, set) => {
        // denser towards the middle; a flattened disc with some lift, tilted per theme by its seed
        const rad = spread * Math.pow(r(), 0.65) * 1.25
        const c = tint.clone().multiplyScalar(0.05 + r() * r() * 0.16)
        set(at, c, [rad, r() * Math.PI * 2, (r() - 0.5) * spread * 0.7 * (1 - rad / (spread * 1.6)), 0.05 + 0.1 / (0.6 + rad)], 0.4 + r() * r() * 1.6)
      })
      out.push({ geometry, cluster: s.id })
    }
    // loose motes through the whole sky
    const r = rng(11)
    out.push({ cluster: null, geometry: build(700, (_, set) => {
      const c = new THREE.Color().setHSL(0.52 + r() * 0.12, 0.7, 0.6).multiplyScalar(0.05 + r() * 0.1)
      set([0, 1.2, 0], c, [3 + Math.sqrt(r()) * 24, r() * Math.PI * 2, (r() - 0.5) * 16, 0.008 + r() * 0.02], 0.3 + r() * 0.9)
    }) })
    return out
  }, [graph])
  useEffect(() => () => clouds.forEach((c) => c.geometry.dispose()), [clouds])

  const materials = useMemo(() => clouds.map(makeMaterial), [clouds])
  useEffect(() => () => materials.forEach((m) => m.dispose()), [materials])

  useEffect(() => {
    clouds.forEach((c, i) => {
      const m = materials[i]!
      m.uniforms.uScale!.value = height * dpr * 0.92
      const off = (focusCluster && c.cluster !== focusCluster) || (selectedId && c.cluster)
      m.uniforms.uDim!.value = c.cluster === null ? (focusCluster || selectedId ? 0.6 : 1) : off ? (focusCluster ? 0.18 : 0.45) : 1
    })
  }, [clouds, materials, height, dpr, focusCluster, selectedId])

  useFrame((_, dt) => {
    if (reduced) return
    // oxlint-disable-next-line react/immutability -- three.js uniforms are mutated per frame by design
    for (const m of materials) m.uniforms.uTime!.value += Math.min(dt, 0.1)
  })

  const nebulae = useMemo(() => graph.sections.flatMap((s) => {
    const at = graph.centres.get(s.id)
    const k = graph.nodes.filter((n) => n.cluster === s.id).length
    return at && k ? [{ id: s.id, at, color: new THREE.Color(s.color), size: 4.5 + Math.sqrt(k) * 1.1 }] : []
  }), [graph])

  return (
    <>
      {nebulae.map((n) => {
        const off = (focusCluster && n.id !== focusCluster) || selectedId
        return (
          <sprite key={`glow-${n.id}`} position={n.at} scale={[n.size, n.size * 0.7, 1]} raycast={() => null}>
            <spriteMaterial map={glow()} color={n.color} transparent opacity={off ? 0.015 : 0.045} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </sprite>
        )
      })}
      {clouds.map((c, i) => <points key={c.cluster ?? 'motes'} geometry={c.geometry} material={materials[i]} raycast={() => null} frustumCulled={false} />)}
    </>
  )
}
