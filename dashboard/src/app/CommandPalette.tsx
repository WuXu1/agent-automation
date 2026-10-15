import { Command } from 'cmdk'
import { MessageSquare, Orbit, Plus, Radio, Volume2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useBrief } from './brief'
import { useBrainUi } from '@/modules/brain/store'
import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { useMode } from '@/telemetry/mode'
import { useChief } from '@/telemetry/team'
import { useApp } from './store'
import { useVisibleViews } from './views'

const item =
  'flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-[13px] text-ink-dim data-[selected=true]:bg-white/[0.06] data-[selected=true]:text-ink'
const group = 'px-2 pt-2 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-ink-faint'

/** ⌘K: jump to a view, find a memory, switch modes. Opens instantly (no animation: it is used many times a day). */
export function CommandPalette() {
  const open = useApp((s) => s.paletteOpen)
  const setPalette = useApp((s) => s.setPalette)
  const go = useApp((s) => s.go)
  const toggleSound = useApp((s) => s.toggleSound)
  const memories = useBrain((s) => s.memories)
  const graph = useBrain((s) => s.graph)
  const mode = useMode((s) => s.mode)
  const bridge = useMode((s) => s.bridge)
  const setMode = useMode((s) => s.setMode)
  const chief = useChief()
  const VIEWS = useVisibleViews().all

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette(!useApp.getState().paletteOpen)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPalette])

  const [query, setQuery] = useState('')
  const directive = query.startsWith('>') ? query.slice(1).trim() : ''
  const run = (fn: () => void) => () => { fn(); setPalette(false); setQuery('') }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setPalette}
      label="Search or jump"
      overlayClassName="fixed inset-0 z-40 bg-void/60"
      contentClassName="fixed inset-x-3 top-[12vh] z-50 mx-auto max-w-xl overflow-hidden rounded-2xl border border-line-strong bg-glass-strong shadow-[0_24px_64px_-12px_rgb(0_0_0/0.7)] backdrop-blur-xl"
    >
      <Command.Input
        value={query}
        onValueChange={setQuery}
        placeholder={`Find a memory, open a view, or type > to brief ${chief.name}…`}
        className="h-12 w-full border-b border-line bg-transparent px-4 text-[15px] text-ink outline-none"
      />
      <Command.List className="max-h-[min(60vh,440px)] overflow-y-auto pb-2">
        <Command.Empty className="px-4 py-6 text-[13px] text-ink-faint">Nothing matches. Memory search by meaning is in the Second Brain’s search box.</Command.Empty>
        {query.startsWith('>') && (
          <Command.Group heading={chief.name} className={group} forceMount>
            <Command.Item value={`brief ${query}`} onSelect={run(() => useBrief.getState().show(directive))} className={item} forceMount>
              <MessageSquare className="size-4 text-[#f0abfc]" />
              <span className="line-clamp-1 flex-1 text-ink">{directive ? `Brief ${chief.name}: ${directive}` : `Brief ${chief.name}… (type your message after >)`}</span>
            </Command.Item>
          </Command.Group>
        )}
        <Command.Group heading="Views" className={group}>
          {VIEWS.map((v) => (
            <Command.Item key={v.id} value={`view ${v.label} ${v.hint}`} onSelect={run(() => go(v.id))} className={item}>
              <v.icon className="size-4 text-ink-faint" strokeWidth={1.75} />
              <span className="flex-1 text-ink">{v.label}</span>
              <span className="text-2xs text-ink-faint">{v.hint}</span>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Actions" className={group}>
          <Command.Item value={`brief ${chief.name} chief directive message tell ask`} onSelect={run(() => useBrief.getState().show(''))} className={item}>
            <MessageSquare className="size-4 text-ink-faint" /> Brief {chief.name}…
          </Command.Item>
          <Command.Item value="add a new memory note" onSelect={run(() => { go('brain'); useBrainUi.getState().compose(true) })} className={item}>
            <Plus className="size-4 text-ink-faint" /> Add a memory
          </Command.Item>
          <Command.Item
            value="switch mode demo live data source"
            disabled={mode === 'demo' && bridge !== 'up'}
            onSelect={run(() => setMode(mode === 'demo' ? 'live' : 'demo'))}
            className={item}
          >
            <Radio className="size-4 text-ink-faint" />
            {mode === 'demo' ? (bridge === 'up' ? 'Switch to live data' : 'Live data needs the bridge') : 'Switch to demo data'}
          </Command.Item>
          <Command.Item value="toggle interface sound" onSelect={run(toggleSound)} className={item}>
            <Volume2 className="size-4 text-ink-faint" /> Toggle interface sounds
          </Command.Item>
        </Command.Group>
        <Command.Group heading={`Memories (${memories.length})`} className={group}>
          {memories.map((m) => {
            const cluster = graph.sectionById.get(graph.byId.get(m.id)?.cluster ?? 'rules')
            return (
              <Command.Item
                key={m.id}
                value={`${m.text} ${m.id}`}
                onSelect={run(() => { go('brain'); useBrainUi.getState().select(m.id) })}
                className={item}
              >
                <Orbit className="size-4 shrink-0" style={{ color: cluster?.color }} strokeWidth={1.75} />
                <span className="line-clamp-1 flex-1">{m.text}</span>
              </Command.Item>
            )
          })}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  )
}
