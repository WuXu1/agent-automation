import { OrbitControls } from '@react-three/drei'
import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import type { MemoryGraph } from '@/telemetry/graph'
import type { ClusterId } from '@/telemetry/types'

const HOME_TARGET = new THREE.Vector3(0, 1.4, 0)
const HOME_DISTANCE = 21

interface Props {
  graph: MemoryGraph
  selectedId: string | null
  focusCluster: ClusterId | null
  active: boolean
  reduced: boolean
}

/**
 * Orbit by hand; picking a memory or a theme flies there. The flight is a critically damped follow
 * (no keyframes), so a new pick mid-flight just retargets, and grabbing the view cancels it.
 */
export function Rig({ graph, selectedId, focusCluster, active, reduced }: Props) {
  const controls = useRef<OrbitControlsImpl>(null)
  const camera = useThree((s) => s.camera)
  // a tall, narrow screen (a phone) needs the camera further back to fit the whole galaxy across
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height))
  const home = Math.min(42, HOME_DISTANCE * Math.max(1, 1.05 / aspect))
  const goal = useRef<{ target: THREE.Vector3; position: THREE.Vector3 } | null>(null)
  const idle = useRef(0)

  useEffect(() => {
    const node = selectedId ? graph.byId.get(selectedId) : undefined
    const c = controls.current
    let target: THREE.Vector3
    let distance: number
    if (node) { target = new THREE.Vector3(...node.position); distance = 9.5 }
    else if (focusCluster) { target = new THREE.Vector3(...(graph.centres.get(focusCluster) ?? [0, 0, 0])); distance = 11 }
    else { target = HOME_TARGET.clone(); distance = home }
    // Keep the current viewing direction, so the flight feels like leaning in rather than a cut.
    const from = c ? c.target : HOME_TARGET
    const dir = camera.position.clone().sub(from).normalize()
    if (dir.lengthSq() === 0) dir.set(0, 0.45, 1).normalize()
    const position = target.clone().add(dir.multiplyScalar(distance))
    if (reduced && c) {
      c.target.copy(target)
      camera.position.copy(position)
      c.update()
      goal.current = null
    } else {
      goal.current = { target, position }
    }
  }, [graph, selectedId, focusCluster, camera, reduced, home])

  useFrame((_, dt) => {
    const c = controls.current
    if (!c) return
    idle.current += dt
    const g = goal.current
    if (g) {
      const k = 1 - Math.exp(-dt * 3.2)
      c.target.lerp(g.target, k)
      camera.position.lerp(g.position, k)
      if (camera.position.distanceTo(g.position) < 0.02 && c.target.distanceTo(g.target) < 0.02) goal.current = null
    }
    c.autoRotate = active && !reduced && !g && idle.current > 6 && !selectedId
    c.update()
  })

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enabled={active}
      enableDamping
      dampingFactor={0.08}
      enablePan={false}
      minDistance={3.5}
      maxDistance={Math.max(32, home + 6)}
      autoRotateSpeed={0.35}
      rotateSpeed={0.6}
      zoomSpeed={0.7}
      onStart={() => { goal.current = null; idle.current = 0 }}
      onEnd={() => { idle.current = 0 }}
    />
  )
}
