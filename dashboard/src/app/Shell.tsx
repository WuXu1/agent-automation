import { lazy, Suspense, useEffect } from 'react'
import { cn } from '@/lib/cn'
import { BrainView } from '@/modules/brain/BrainView'
import { useCrew } from '@/telemetry/crew'
import { useMem0Graph } from '@/telemetry/hooks/useMem0Graph'
import { useMode } from '@/telemetry/mode'
import { useRegistry } from '@/telemetry/registry'
import { useSettings } from '@/telemetry/settings'
import { BriefPanel } from './BriefPanel'
import { CommandPalette } from './CommandPalette'
import { Rail } from './Rail'
import { useApp } from './store'
import { TopBar } from './TopBar'
import { useCurrentView } from './views'

// three.js and friends load as their own chunk; the shell paints first.
const Sky = lazy(() => import('@/modules/brain/Sky'))
const VIEW = {
  agents: lazy(() => import('@/modules/agents')),
  infra: lazy(() => import('@/modules/infra')),
  board: lazy(() => import('@/modules/board')),
  inbox: lazy(() => import('@/modules/inbox')),
  integrations: lazy(() => import('@/modules/integrations')),
  settings: lazy(() => import('@/modules/settings')),
}

export function Shell() {
  // an add-on's view (the Inbox) opens only when crew.json switches the add-on on
  const view = useCurrentView(useApp((s) => s.view))
  const probe = useMode((s) => s.probe)
  const onBrain = view === 'brain'
  const collapsed = useApp((s) => s.railCollapsed)

  useEffect(() => { void probe() }, [probe])
  // the composer's tidy default and the dashboard model come from Settings
  const mode = useMode((s) => s.mode)
  const loadCrew = useCrew((s) => s.load)
  useEffect(() => { void loadCrew(mode) }, [mode, loadCrew])
  const loadSettings = useSettings((s) => s.load)
  useEffect(() => { void loadSettings() }, [mode, loadSettings])
  const loadRegistry = useRegistry((s) => s.load)
  useEffect(() => { void loadRegistry() }, [mode, loadRegistry])
  useMem0Graph()

  return (
    <div className="fixed inset-0 overflow-hidden bg-void">
      {/* The dome: the constellation stays behind every view, dimmed and paused when it is not the subject. */}
      <div aria-hidden={!onBrain} className={cn('absolute inset-0 transition-opacity duration-300', onBrain ? 'opacity-100' : 'opacity-30')}>
        <Suspense fallback={null}>
          <Sky active={onBrain} />
        </Suspense>
      </div>

      <div className={cn('pointer-events-none relative grid h-dvh grid-cols-1 grid-rows-[52px_minmax(0,1fr)_auto] md:grid-rows-[56px_minmax(0,1fr)]',
        'transition-[grid-template-columns] duration-200 ease-out', collapsed ? 'md:grid-cols-[76px_minmax(0,1fr)]' : 'md:grid-cols-[224px_minmax(0,1fr)]')}>
        <Rail />
        <TopBar />
        <main className={cn('relative min-h-0', !onBrain && 'pointer-events-auto')}>
          {view === 'brain' ? <BrainView /> : (
            <Suspense fallback={null}>
              {(() => { const View = VIEW[view]; return <View /> })()}
            </Suspense>
          )}
        </main>
      </div>

      <CommandPalette />
      <BriefPanel />
    </div>
  )
}
