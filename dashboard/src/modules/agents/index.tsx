import { useRef, useState } from 'react'
import { useChief } from '@/telemetry/team'
import { useAgentMesh } from '@/telemetry/hooks/feeds'
import { useMode } from '@/telemetry/mode'
import { FeedError, FeedStatus } from '@/ui/FeedStatus'
import { Panel } from '@/ui/Panel'
import { AddServer, type AddServerPreset } from './AddServer'
import { Automations } from './Automations'
import { AgentEditor, type EditorTarget } from './AgentEditor'
import { AgentTerminal } from './AgentTerminal'
import { Handoffs } from './Handoffs'
import { RestartBar } from './RestartBar'
import { TeamTree } from './TeamTree'
import { ToolMatrix } from './ToolMatrix'
import { useRestart } from './writes'

/** Agent Studio: the team, its handoffs and its tools, and the profile manager. */
export default function AgentsView() {
  const feed = useAgentMesh()
  const chief = useChief()
  const setMode = useMode((s) => s.setMode)
  const needed = useRestart((s) => s.state.needed)
  const [target, setTarget] = useState<EditorTarget | null>(null)
  const [addServer, setAddServer] = useState<AddServerPreset | null>(null)
  const [watching, setWatching] = useState<{ id: string; profile: string; name: string; tint: string } | null>(null)
  const mesh = feed.data
  const openProfile = (profileOrId: string) => {
    const a = mesh?.agents.find((x) => x.profile === profileOrId || x.id === profileOrId)
    if (a) setTarget({ mode: 'edit', profile: a.profile })
  }
  // clicking an agent opens its settings, with a button to watch its live logs; a hand-off opens the terminal straight away
  const tints = useRef<Record<string, string>>({})
  const openAgent = (profile: string, tint?: string) => {
    if (tint) tints.current[profile] = tint
    openProfile(profile)
  }
  const openTerminal = (profileOrId: string, tint = '#c084fc') => {
    const a = mesh?.agents.find((x) => x.profile === profileOrId || x.id === profileOrId)
    if (a) setWatching({ id: a.id, profile: a.profile, name: a.name, tint })
  }
  const pendingFor = (profile: string) => needed.some((r) => r.includes(`(${profile})`) || r.endsWith(` ${profile}`))

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1500px] p-3 md:p-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-ink-dim">{chief.name} hands work to the team; everyone works from the board. {mesh ? `${mesh.agents.length} agents.` : ''}
            <span className="text-ink-faint"> New agents come through Claude.</span></p>
          <FeedStatus feed={feed} source="the agents" />
        </div>
        <RestartBar />
        {!mesh ? (
          feed.status === 'error' ? <FeedError error={feed.error} onDemo={() => setMode('demo')} /> : <div className="glass h-64 animate-pulse" />
        ) : (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 xl:grid-cols-12">
            <Panel title="Team" className="xl:col-span-12" bodyClassName="px-3 pt-1 pb-4 md:px-4"
              aside={<span className="hidden text-2xs text-ink-faint sm:inline">click an agent for its settings and live logs · running line = working on a card · amber = waiting on an answer · spark = a new hand-off</span>}>
              <TeamTree mesh={mesh} pendingFor={pendingFor} onOpen={openAgent} />
            </Panel>
            <Automations agents={mesh.agents} className="xl:col-span-12" />
            <Handoffs handoffs={mesh.handoffs} onOpen={(p) => openTerminal(p)} className="xl:col-span-12" />
            <ToolMatrix agents={mesh.agents} onOpen={openProfile} onAdd={(p) => { setTarget(null); setAddServer(p) }} />
          </div>
        )}
      </div>
      {watching && <AgentTerminal key={watching.id} agent={watching} onClose={() => setWatching(null)} onSettings={(p) => { setWatching(null); openProfile(p) }} />}
      {mesh && (
        <AgentEditor key={target ? `e:${target.profile}` : 'none'}
          target={target} mesh={mesh} onClose={() => setTarget(null)}
          onAddServer={(p) => { setTarget(null); setAddServer(p) }}
          onWatch={(p) => { setTarget(null); openTerminal(p, tints.current[p]) }} />
      )}
      {mesh && (
        <AddServer key={JSON.stringify(addServer)} preset={addServer} agents={mesh.agents} onClose={() => setAddServer(null)} />
      )}
    </div>
  )
}
