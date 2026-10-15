import { advanceSharedBoard, sharedBoard } from '../demo/board'
import { demoMesh, tickMesh } from '../demo/agents'
import { demoInfra, tickInfra } from '../demo/infra'
import { useRoster } from '../agents'
import { useTeam } from '../team'
import { makeFeed, useFeed } from '../feed'
import type { AgentMesh, Board, Infra } from '../types'

// One hook per bridge route. Each polls its route in live mode; demo data moves on its own.
export const agentFeed = makeFeed<AgentMesh>({ path: '/agents', everyMs: 10_000, demo: demoMesh, tick: tickMesh, tickMs: 6000 })
export const infraFeed = makeFeed<Infra>({ path: '/infra', everyMs: 15_000, demo: () => demoInfra(), tick: tickInfra, tickMs: 3000 })
export const boardFeed = makeFeed<Board>({ path: '/board', everyMs: 20_000, demo: sharedBoard, tick: advanceSharedBoard, tickMs: 6000 })

export const useAgentMesh = () => useFeed(agentFeed)
export const useInfrastructure = () => useFeed(infraFeed)
export const useBoard = () => useFeed(boardFeed)

// Every view that names an agent reads the roster; the agent feed keeps it in step with the VM's profiles.
agentFeed.subscribe((s, prev) => {
  if (s.data && s.data !== prev.data) useRoster.getState().fromMesh(s.data.agents)
})
// a new team resets the roster to it (agents.ts); put back what the VM reported, if we have it
useTeam.subscribe((s, prev) => {
  const d = agentFeed.getState().data
  if (s.team !== prev.team && d) useRoster.getState().fromMesh(d.agents)
})
