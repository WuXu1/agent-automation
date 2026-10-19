import { useMemo } from 'react'
import * as THREE from 'three'
import { rng } from '@/lib/rng'

let glowTexture: THREE.Texture | null = null

/** A soft round glow (computed once), for the galaxy's core and each theme's nebula.
 *
 * Built as raw pixels, not drawn on a canvas: a canvas stores colour premultiplied by its alpha in 8 bits, so where the glow fades out
 * (alpha near zero) the colour channels come back coarse and tinted, and an iPhone's GPU showed that as black, blue and green
 * speckle across the haze. Here every pixel is plain white and only the alpha fades, with a hair of noise so it does not band. */
export function glow(): THREE.Texture {
  if (glowTexture) return glowTexture
  const N = 128
  const data = new Uint8Array(N * N * 4)
  const stops: [number, number][] = [[0, 1], [0.25, 0.45], [0.6, 0.1], [1, 0]]
  const alphaAt = (r: number) => {
    for (let k = 1; k < stops.length; k++) {
      const [r1, a1] = stops[k]!
      if (r <= r1) { const [r0, a0] = stops[k - 1]!; return a0 + ((a1 - a0) * (r - r0)) / (r1 - r0) }
    }
    return 0
  }
  const noise = rng(5)
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const r = Math.hypot(x + 0.5 - N / 2, y + 0.5 - N / 2) / (N / 2)
      const a = r >= 1 ? 0 : alphaAt(r) * 255 + (noise() - 0.5)
      const o = (y * N + x) * 4
      data[o] = data[o + 1] = data[o + 2] = 255
      data[o + 3] = Math.max(0, Math.min(255, Math.round(a)))
    }
  }
  const t = new THREE.DataTexture(data, N, N, THREE.RGBAFormat)
  t.magFilter = THREE.LinearFilter
  t.minFilter = THREE.LinearFilter
  t.generateMipmaps = false
  t.needsUpdate = true
  glowTexture = t
  return t
}

/** Far stars, a faint galactic glow at the centre, and the celestial grid (the spec's grid overlay, drawn as the dome's
 * coordinate lines, kept very faint so the nebula reads first). */
export function Backdrop() {
  const stars = useMemo(() => {
    const r = rng(7)
    const n = 1600
    const pos = new Float32Array(n * 3)
    const col = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      const u = r() * 2 - 1
      const phi = r() * Math.PI * 2
      const rad = 45 + r() * 40
      const s = Math.sqrt(1 - u * u)
      pos.set([s * Math.cos(phi) * rad, u * rad, s * Math.sin(phi) * rad], i * 3)
      const b = 0.18 + r() * r() * 0.55
      col.set([b * 0.85, b * 0.92, b], i * 3)
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    return g
  }, [])

  const grid = useMemo(() => {
    const R = 36
    const pts: number[] = []
    const seg = 96
    // Declination circles every 20°, right-ascension meridians every 30°.
    for (let dec = -60; dec <= 60; dec += 20) {
      const y = Math.sin((dec * Math.PI) / 180) * R
      const rr = Math.cos((dec * Math.PI) / 180) * R
      for (let i = 0; i < seg; i++) {
        const a = (i / seg) * Math.PI * 2
        const b = ((i + 1) / seg) * Math.PI * 2
        pts.push(Math.cos(a) * rr, y, Math.sin(a) * rr, Math.cos(b) * rr, y, Math.sin(b) * rr)
      }
    }
    for (let ra = 0; ra < 360; ra += 30) {
      const t = (ra * Math.PI) / 180
      for (let i = 0; i < seg / 2; i++) {
        const a = -Math.PI / 2 + (i / (seg / 2)) * Math.PI
        const b = -Math.PI / 2 + ((i + 1) / (seg / 2)) * Math.PI
        pts.push(Math.cos(a) * Math.cos(t) * R, Math.sin(a) * R, Math.cos(a) * Math.sin(t) * R,
          Math.cos(b) * Math.cos(t) * R, Math.sin(b) * R, Math.cos(b) * Math.sin(t) * R)
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
    return g
  }, [])

  return (
    <>
      <points geometry={stars}>
        <pointsMaterial vertexColors size={0.16} sizeAttenuation depthWrite={false} toneMapped={false} />
      </points>
      <lineSegments geometry={grid}>
        <lineBasicMaterial color="#94a3b8" transparent opacity={0.03} depthWrite={false} />
      </lineSegments>
      <sprite position={[0, 0.6, 0]} scale={[34, 20, 1]} raycast={() => null}>
        <spriteMaterial map={glow()} color="#14304d" transparent opacity={0.4} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </sprite>
    </>
  )
}
