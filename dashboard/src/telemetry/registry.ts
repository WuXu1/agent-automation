import { create } from 'zustand'
import { registryApi, type Registry } from './tools'

// Names and labels the VM cannot tell (dashboard/bridge/registry.json, served at /api/registry with the team's ids). Live mode
// reads the VM's copy once per mode, so what is added to the registry shows after a reload; demo mode, and a bridge that
// cannot answer, use the copy below (written for the demo team).
export const DEFAULT_REGISTRY: Registry = {
  tools: [
    { key: 'kanban', label: 'Board', who: ['atlas'], rule: 'the chief creates and hands out cards' },
    { key: 'weather', label: 'Weather', who: ['atlas', 'ivy', 'rocky'], rule: 'forecasts only' },
    { key: 'openalex', label: 'Paper search', who: ['sage'], rule: 'OpenAlex, read only' },
    { key: 'gmail', label: 'Gmail (add-on)', who: ['atlas', 'ivy'], rule: 'read and draft; never sends without your yes' },
    { key: 'icloud', label: 'iCloud calendar (add-on)', who: ['sage', 'ivy'], rule: 'the tutor reads; the assistant writes' },
  ],
  mcp: {
    moodle: 'one session cookie; renew it when it expires',
    openalex: 'search for papers',
  },
  roles: { atlas: 'Chief of Staff', sage: 'Tutor', ivy: 'Assistant', rocky: 'Coach' },
  teams: [
    { id: 'specialists', label: 'Specialists', members: ['sage', 'ivy', 'rocky'], note: 'one specialist each; the chief hands them cards' },
  ],
  services: {
    'hermes-gateway': { label: 'Agents: Telegram and the API', port: 8642, described: true },
    'mem0-server': { label: 'Memory (Mem0)', port: 8888, described: true },
    postgresql: { label: 'Mem0’s database', port: 5432, described: true },
    'hermes-dash': { label: 'This dashboard', port: 8890, described: true },
    tailscaled: { label: 'Tailscale (private network)', port: null, described: true },
  },
}

interface RegistryStore {
  reg: Registry
  load: () => Promise<void>
}

export const useRegistry = create<RegistryStore>((set) => ({
  reg: DEFAULT_REGISTRY,
  load: async () => {
    try { set({ reg: (await registryApi.get()) ?? DEFAULT_REGISTRY }) } catch { set({ reg: DEFAULT_REGISTRY }) }
  },
}))
