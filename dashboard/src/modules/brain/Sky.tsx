import { Canvas, useThree } from '@react-three/fiber'
import { RAIL_W, useApp } from '@/app/store'
import { Bloom, EffectComposer, Vignette } from '@react-three/postprocessing'
import { useEffect } from 'react'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { play } from '@/lib/sound'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { Agents } from './scene/Agents'
import { Backdrop } from './scene/Backdrop'
import { Dust } from './scene/Dust'
import { Edges } from './scene/Edges'
import { Labels } from './scene/Labels'
import { Nodes } from './scene/Nodes'
import { Rig } from './scene/Rig'
import { useBrainUi } from './store'

/** Centre the sky on the page (the canvas spans the window; the page starts right of the rail), and left of the drawer when it is open. */
function Frame() {
  const camera = useThree((s) => s.camera)
  const size = useThree((s) => s.size)
  const drawer = useBrainUi((s) => Boolean(s.selectedId) || s.composing)
  const rail = useApp((s) => (s.railCollapsed ? RAIL_W.collapsed : RAIL_W.open))
  useEffect(() => {
    // the brain in the middle of the page, not pushed right of the search column
    const shift = size.width < 768 ? 0 : drawer ? (rail - 424) / 2 : rail / 2
    camera.setViewOffset(size.width, size.height, -shift, 0, size.width, size.height)
    camera.updateProjectionMatrix()
    return () => { camera.clearViewOffset() }
  }, [camera, size.width, size.height, drawer, rail])
  return null
}

/** When the view is not shown, render one last frame and stop (frameloop 'demand'), so the dome costs nothing. */
function Settle({ active }: { active: boolean }) {
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => { invalidate() }, [active, invalidate])
  return null
}

function Scene({ active }: { active: boolean }) {
  const graph = useBrain((s) => s.graph)
  const memories = useBrain((s) => s.memories)
  const hits = useBrain((s) => s.hits)
  const selectedId = useBrainUi((s) => s.selectedId)
  const hoveredId = useBrainUi((s) => s.hoveredId)
  const focusCluster = useBrainUi((s) => s.focusCluster)
  const select = useBrainUi((s) => s.select)
  const hover = useBrainUi((s) => s.hover)
  const reduced = useReducedMotion()

  useEffect(() => {
    document.body.style.cursor = active && hoveredId ? 'pointer' : ''
    return () => { document.body.style.cursor = '' }
  }, [active, hoveredId])

  return (
    <>
      <color attach="background" args={['#05070a']} />
      <fog attach="fog" args={['#05070a', 26, 70]} />
      <Backdrop />
      <Dust graph={graph} focusCluster={focusCluster} selectedId={selectedId} reduced={reduced} />
      <Edges graph={graph} hits={hits} selectedId={selectedId} focusCluster={focusCluster} reduced={reduced} />
      <Nodes
        graph={graph}
        hits={hits}
        selectedId={selectedId}
        hoveredId={active ? hoveredId : null}
        focusCluster={focusCluster}
        onHover={(id) => { if (active && id !== useBrainUi.getState().hoveredId) hover(id) }}
        onSelect={(id) => { if (active) { play('open'); select(id) } }}
      />
      <Agents graph={graph} labels={active} />
      <Labels visible={active} graph={graph} memories={memories} hoveredId={hoveredId} selectedId={selectedId} focusCluster={focusCluster} />
      <Rig graph={graph} selectedId={selectedId} focusCluster={focusCluster} active={active} reduced={reduced} />
      <Settle active={active} />
      <Frame />
      <EffectComposer multisampling={0}>
        <Bloom mipmapBlur luminanceThreshold={0.5} luminanceSmoothing={0.25} intensity={1.25} radius={0.75} />
        <Vignette offset={0.3} darkness={0.78} />
      </EffectComposer>
    </>
  )
}

export default function Sky({ active }: { active: boolean }) {
  return (
    <Canvas
      className="!absolute inset-0"
      frameloop={active ? 'always' : 'demand'}
      dpr={[1, 1.75]}
      gl={{ antialias: false, powerPreference: 'high-performance', alpha: false }}
      camera={{ position: [0, 10.4, 18.4], fov: 46, near: 0.1, far: 200 }}
      onPointerMissed={() => { if (active) useBrainUi.getState().select(null) }}
      aria-label="Memory constellation: each point is one Mem0 note, grouped by theme"
    >
      <Scene active={active} />
    </Canvas>
  )
}
