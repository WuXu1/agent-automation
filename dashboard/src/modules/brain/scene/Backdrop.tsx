import { useMemo } from 'react'
import * as THREE from 'three'
import { rng } from '@/lib/rng'

let glowTexture: THREE.Texture | null = null

/** A soft round glow (made once on a canvas), for the galaxy's core and each theme's nebula. */
export function glow(): THREE.Texture {
  if (glowTexture) return glowTexture
  const c = document.createElement('canvas')
  c.width = c.height = 128
  const g = c.getContext('2d')!
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  grad.addColorStop(0, 'rgba(255,255,255,1)')
  grad.addColorStop(0.25, 'rgba(255,255,255,0.45)')
  grad.addColorStop(0.6, 'rgba(255,255,255,0.1)')
  grad.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = grad
  g.fillRect(0, 0, 128, 128)
  glowTexture = new THREE.CanvasTexture(c)
  return glowTexture
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
