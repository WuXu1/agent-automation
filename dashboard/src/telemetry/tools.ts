import { api } from './live/client'
import { agentFeed } from './hooks/feeds'
import { reloadFeed } from './feed'
import { useMode } from './mode'
import { ownerName } from './crew'

// Skills, MCP servers, AI enhance and backup-now (bridge/tools.py, bridge/jobs.py). Live: the bridge; the network ones run
// as jobs on the VM and are polled. Demo: plausible answers in this tab, nothing leaves the page. Agents are named by their
// Hermes profile here; the bridge also accepts the crew's ids.

const isLive = () => useMode.getState().mode === 'live'
const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

interface JobOut { state: 'running' | 'done'; ok?: boolean; error?: string }

/** Start a job on the VM and wait for its result (the runner starts within a second or two). */
async function job<T>(start: Promise<{ job: string }>, timeoutMs = 120_000): Promise<T> {
  const { job: id } = await start
  const until = Date.now() + timeoutMs
  for (let wait = 700; Date.now() < until; wait = Math.min(2000, wait * 1.3)) {
    await sleep(wait)
    const out = await api<JobOut & T>(`/jobs/${id}`)
    if (out.state === 'done') {
      if (!out.ok) throw new Error(out.error ?? 'The job failed')
      return out
    }
  }
  throw new Error('The VM is taking too long; try again in a minute')
}

// -- AI enhance --------------------------------------------------------------------------------------------------------------

export type EnhanceField = 'description' | 'soul' | 'skill'

function demoEnhance(field: EnhanceField, text: string, name: string): string {
  const tidy = text.trim().replace(/\s+\n/g, '\n').replace(/(^|[.!?]\s+)([a-z])/g, (_, a: string, b: string) => a + b.toUpperCase())
  if (field === 'description') return `${name || 'This agent'}: ${tidy.replace(/^[^:]{1,24}:\s*/, '').replace(/\.?$/, '.')}`
  const owner = ownerName()
  if (field === 'soul') return `You are ${name || `one of ${owner}’s agents`}.\n\n## What you do\n${tidy}\n\n## How you work\n- Plain words, short answers.\n- Never send, buy, submit or delete anything without ${owner}’s yes.`
  return `## When to use it\n${tidy}\n\n## Steps\n1. …`
}

/** A rewrite of what you typed (DeepSeek on the VM, a fraction of a penny). */
export async function enhance(field: EnhanceField, text: string, name = '', about = ''): Promise<string> {
  if (!isLive()) { await sleep(900); return demoEnhance(field, text, name) }
  const out = await job<{ text: string }>(api('/enhance', { method: 'POST', body: { field, text, name, about } }))
  return out.text
}

// -- skills ------------------------------------------------------------------------------------------------------------------

export interface Skill {
  name: string
  category: string
  description: string
  /** builtin: ships with Hermes · hub: installed from a registry · local: written by hand · dashboard: the team list */
  source: 'builtin' | 'hub' | 'local' | 'dashboard'
  identifier: string | null
  enabled: boolean
}
/** A skills.sh result (the only registry the dashboard searches): `repo` it comes from, `installs` on skills.sh. */
export interface HubSkill { name: string; identifier: string; source: string; trust_level: string; description: string; repo: string; installs: number | null }

const DEMO_SKILLS: Skill[] = ([
  ['deadline-reminders', 'productivity', 'Use when scheduling reminders for deadlines or commitments.', 'local'],
  ['email-inbox-triage', 'email', 'Sort an inbox into reply, read later and ignore.', 'builtin'],
  ['weekly-review', 'productivity', 'Sum up the week: what got done, what slipped, what is next.', 'local'],
  ['arxiv', 'research', 'Search arXiv and summarise papers.', 'builtin'],
  ['obsidian', 'note-taking', 'Read and write notes in an Obsidian vault.', 'builtin'],
  ['p5js', 'creative', 'Make interactive sketches with p5.js.', 'builtin'],
  ['humanizer', 'creative', 'Rewrite text so it sounds like a person wrote it.', 'builtin'],
  ['youtube-content', 'media', 'Summarise a YouTube video from its transcript.', 'builtin'],
  ['claude-code', 'autonomous-ai-agents', 'Hand a coding task to Claude Code.', 'builtin'],
] as Array<[string, string, string, Skill['source']]>).map(([name, category, description, source]) => ({ name, category, description, source, identifier: null, enabled: true }))
const demoSkills = new Map<string, Skill[]>()
const mine = (profile: string) => {
  if (!demoSkills.has(profile)) demoSkills.set(profile, DEMO_SKILLS.map((s) => ({ ...s })))
  return demoSkills.get(profile)!
}

export const skills = {
  list: async (profile: string): Promise<Skill[]> =>
    isLive() ? (await api<{ skills: Skill[] }>(`/agents/${profile}/skills`, { timeoutMs: 30_000 })).skills : mine(profile),
  setEnabled: async (profile: string, name: string, enabled: boolean): Promise<Skill[]> => {
    if (isLive()) return (await api<{ skills: Skill[] }>(`/agents/${profile}/skills/${name}`, { method: 'PUT', body: { enabled }, timeoutMs: 30_000 })).skills
    const s = mine(profile).find((x) => x.name === name)
    if (s) s.enabled = enabled
    return [...mine(profile)]
  },
  remove: async (profile: string, name: string): Promise<Skill[]> => {
    if (isLive()) return (await api<{ skills: Skill[] }>(`/agents/${profile}/skills/${name}`, { method: 'DELETE', body: {}, timeoutMs: 60_000 })).skills
    demoSkills.set(profile, mine(profile).filter((x) => x.name !== name))
    return mine(profile)
  },
  create: async (profile: string, input: { name: string; description: string; body: string }): Promise<Skill[]> => {
    if (isLive()) return (await api<{ skills: Skill[] }>(`/agents/${profile}/skills`, { method: 'POST', body: input, timeoutMs: 30_000 })).skills
    if (mine(profile).some((s) => s.name === input.name)) throw new Error('This agent already has a skill with that name')
    mine(profile).push({ name: input.name, category: 'custom', description: input.description, source: 'local', identifier: null, enabled: true })
    return [...mine(profile)]
  },
  search: async (profile: string, query: string): Promise<HubSkill[]> => {
    if (!isLive()) {
      await sleep(700)
      const q = query.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      return [
        { name: q, identifier: `skills-sh/anthropics/skills/${q}`, source: 'skills.sh', trust_level: 'trusted', description: `Indexed by skills.sh from anthropics/skills · 206,133 installs`, repo: 'anthropics/skills', installs: 206133 },
        { name: `${q}-helper`, identifier: `skills-sh/example/skills/${q}-helper`, source: 'skills.sh', trust_level: 'community', description: `Indexed by skills.sh from example/skills · 1,204 installs`, repo: 'example/skills', installs: 1204 },
      ]
    }
    return (await job<{ results: HubSkill[] }>(api(`/agents/${profile}/skills/search`, { method: 'POST', body: { query } }))).results
  },
  inspect: async (profile: string, identifier: string): Promise<string> => {
    if (!isLive()) { await sleep(500); return `---\nname: ${identifier.split('/').pop()}\n---\n\n(Demo) The skill's instructions would show here before you install it.` }
    return (await job<{ text: string }>(api(`/agents/${profile}/skills/inspect`, { method: 'POST', body: { identifier } }))).text
  },
  install: async (profile: string, identifier: string): Promise<string> => {
    if (!isLive()) {
      await sleep(900)
      const name = identifier.split('/').pop() ?? identifier
      mine(profile).push({ name, category: 'hub', description: 'Installed from the hub (demo).', source: 'hub', identifier, enabled: true })
      return `Installed ${name}`
    }
    return (await job<{ text: string }>(api(`/agents/${profile}/skills/install`, { method: 'POST', body: { identifier } }), 300_000)).text
  },
}

// -- MCP servers -------------------------------------------------------------------------------------------------------------

export interface ServerRow {
  name: string
  transport: 'http' | 'stdio'
  /** The URL without its query, or the command and its first arguments. */
  address: string
  auth: string | null
  env: string[]
  /** profile -> switched on */
  agents: Record<string, boolean>
}
export interface CatalogEntry {
  name: string
  description: string
  transport: 'http' | 'stdio'
  auth: 'none' | 'api_key' | 'oauth'
  url: string | null
  needsInstall: boolean
  postInstall: string
  env: Array<{ name: string; prompt: string; secret: boolean; required: boolean }>
}
export interface AddServer {
  source: 'catalog' | 'custom' | 'copy'
  name: string
  profiles: string[]
  entry?: string
  from?: string
  secrets?: Record<string, string>
  transport?: 'http' | 'stdio'
  url?: string
  headers?: Array<{ name: string; value: string; secret: boolean }>
  oauth?: boolean
  command?: string
  args?: string[]
  env?: Array<{ name: string; value: string; secret: boolean }>
}

const DEMO_CATALOG: CatalogEntry[] = ([
  ['deepwiki', 'Ask questions about any public GitHub repo (Devin’s DeepWiki).', 'none'],
  ['context7', 'Up-to-date, version-specific library docs and code examples.', 'none'],
  ['linear', 'Find, create, and update Linear issues, projects, and comments.', 'oauth'],
  ['canva', 'Create, search, and manage Canva designs.', 'oauth'],
  ['kiwi', 'Kiwi.com flight search: itineraries with direct booking links.', 'none'],
  ['airtable', 'Bases, tables, and records from your Airtable workspace.', 'api_key'],
] as Array<[string, string, CatalogEntry['auth']]>).map(([name, description, auth]) => ({ name, description, transport: 'http' as const, auth, url: `https://mcp.${name}.example/mcp`,
  needsInstall: false, postInstall: auth === 'oauth' ? 'Signs in with your account once.' : '', env: auth === 'api_key' ? [{ name: `${name.toUpperCase()}_API_KEY`, prompt: `${name} API key`, secret: true, required: true }] : [] }))

function demoServers(): ServerRow[] {
  const rows = new Map<string, ServerRow>()
  for (const a of agentFeed.getState().data?.agents ?? []) {
    for (const m of a.mcp) {
      const r = rows.get(m.name) ?? { name: m.name, transport: 'http', address: `https://${m.name}.example/mcp`, auth: null, env: [], agents: {} }
      r.agents[a.profile] = m.enabled
      rows.set(m.name, r)
    }
  }
  return [...rows.values()].sort((x, y) => x.name.localeCompare(y.name))
}

export const mcp = {
  servers: async (): Promise<ServerRow[]> => (isLive() ? (await api<{ servers: ServerRow[] }>('/mcp', { timeoutMs: 30_000 })).servers : demoServers()),
  catalog: async (): Promise<CatalogEntry[]> => (isLive() ? (await api<{ entries: CatalogEntry[] }>('/mcp/catalog', { timeoutMs: 60_000 })).entries : DEMO_CATALOG),
  add: async (input: AddServer): Promise<{ added: string[]; skipped: string[]; note: string | null }> => {
    if (isLive()) {
      const out = await api<{ added: string[]; skipped: string[]; note: string | null }>('/mcp', { method: 'POST', body: input, timeoutMs: 90_000 })
      await reloadFeed(agentFeed)
      return out
    }
    const s = agentFeed.getState()
    const added: string[] = []
    if (s.data) {
      agentFeed.setState({ data: { ...s.data, agents: s.data.agents.map((a) => {
        if (!input.profiles.includes(a.profile) || a.mcp.some((m) => m.name === input.name)) return a
        added.push(a.profile)
        return { ...a, mcp: [...a.mcp, { name: input.name, enabled: true }] }
      }) } })
    }
    return { added, skipped: input.profiles.filter((x) => !added.includes(x)), note: input.source === 'catalog' ? DEMO_CATALOG.find((c) => c.name === input.entry)?.postInstall || null : null }
  },
  remove: async (name: string, profile: string): Promise<void> => {
    if (isLive()) { await api(`/mcp/${name}/${profile}`, { method: 'DELETE', body: {}, timeoutMs: 60_000 }); await reloadFeed(agentFeed); return }
    const s = agentFeed.getState()
    if (s.data) agentFeed.setState({ data: { ...s.data, agents: s.data.agents.map((a) => (a.profile === profile ? { ...a, mcp: a.mcp.filter((m) => m.name !== name) } : a)) } })
  },
}

// -- backup now --------------------------------------------------------------------------------------------------------------

export interface BackupState { active: boolean; result: string | null; requested: boolean; last: { at: number; state: string; message: string } | null }

let demoBackup: BackupState = { active: false, result: 'success', requested: false, last: null }

export const backups = {
  state: async (): Promise<BackupState> => (isLive() ? api<BackupState>('/backup') : demoBackup),
  start: async (): Promise<void> => {
    if (isLive()) { await api('/backup', { method: 'POST', body: {} }); return }
    demoBackup = { active: true, result: null, requested: false, last: { at: Date.now() / 1000, state: 'started', message: 'Backup started' } }
    window.setTimeout(() => { demoBackup = { ...demoBackup, active: false, result: 'success' } }, 8000)
  },
}

// -- settings, balances, the brain's sections ---------------------------------------------------------------------------------

export interface ModelChoice { id: string; provider: string; label: string; note: string; available: boolean }
export interface Settings { model: string; tidyMemories: boolean; credit?: { balance: number; as_of: string; burn_per_day: number; start: number }; models: ModelChoice[] }
export interface Balances {
  at: number
  deepseek?: { balance?: number; currency?: string; ok?: boolean; error?: string }
  elevenlabs?: { used?: number; limit?: number; tier?: string; resetAt?: number | null; error?: string }
}

const DEMO_MODELS: ModelChoice[] = [
  { id: 'deepseek-flash', provider: 'deepseek', label: 'DeepSeek Flash', note: 'what the agents use; about 0.01p a rewrite', available: true },
  { id: 'deepseek-v4-pro', provider: 'deepseek', label: 'DeepSeek V4 Pro', note: 'stronger, about 4x the price', available: true },
  { id: 'gemini-2.5-flash', provider: 'gemini', label: 'Gemini 2.5 Flash', note: 'your AI Studio key: free tier unless billing is on', available: true },
  { id: 'gemini-2.5-flash-lite', provider: 'gemini', label: 'Gemini 2.5 Flash Lite', note: 'your AI Studio key: free tier unless billing is on', available: true },
]
let demoSettings: Settings = { model: 'deepseek-flash', tidyMemories: true, models: DEMO_MODELS,
  credit: { balance: 87.4, as_of: '2026-10-01', burn_per_day: 1.2, start: 100 } }

export const settingsApi = {
  get: async (): Promise<Settings> => (isLive() ? api<Settings>('/settings') : demoSettings),
  save: async (patch: Partial<Pick<Settings, 'model' | 'tidyMemories' | 'credit'>>): Promise<Settings> => {
    if (isLive()) return api<Settings>('/settings', { method: 'PUT', body: patch })
    demoSettings = { ...demoSettings, ...patch }
    return demoSettings
  },
}

export async function balances(refresh = false): Promise<Balances | null> {
  if (!isLive()) {
    await sleep(300)
    return { at: Date.now(), deepseek: { balance: 4.62, currency: 'USD', ok: true },
      elevenlabs: { used: 4_210, limit: 10_000, tier: 'free', resetAt: Date.now() + 27 * 86_400_000 } }
  }
  const first = await api<{ balances: Balances | null; job: string | null }>('/balances', { method: refresh ? 'POST' : 'GET', body: refresh ? {} : undefined })
  if (first.job && (refresh || !first.balances)) {
    try { return await job<Balances>(Promise.resolve({ job: first.job }), 60_000) } catch { return first.balances }
  }
  return first.balances
}

export interface Tidied { text: string; section: string | null; new: { label: string; blurb: string } | null }

export const brainApi = {
  /** The note rewritten as one clear line, and the section it belongs in (or a new one). */
  tidy: async (text: string, guess: (t: string) => string): Promise<Tidied> => {
    if (!isLive()) {
      await sleep(800)
      const t = text.trim().replace(/^i\b/i, ownerName()).replace(/^[a-z]/, (c) => c.toUpperCase()).replace(/\.?$/, '.')
      return /\b(car|insurance|savings?|money)\b/i.test(text)
        ? { text: t, section: null, new: { label: 'Money & savings', blurb: 'Budget, saving, insurance' } }
        : { text: t, section: guess(text), new: null }
    }
    return job<Tidied>(api('/memories/tidy', { method: 'POST', body: { text } }), 60_000)
  },
  rename: async (id: string, label: string, blurb: string) => api<unknown>(`/brain/sections/${id}`, { method: 'PUT', body: { label, blurb } }),
  merge: async (id: string, into: string) => api(`/brain/sections/${id}`, { method: 'DELETE', body: { into } }),
  resort: async () => api('/brain/resort', { method: 'POST', body: {} }),
}

// -- automations (Hermes cron jobs) ------------------------------------------------------------------------------------------

export interface Automation {
  id: string
  profile: string
  name: string
  schedule: string
  expr: string
  state: string
  nextAt: number | null
  lastAt: number | null
  lastStatus: string | null
  lastError: string | null
  failures: number
  deliver: string
  mode: 'agent' | 'script'
  script: string | null
  prompt: string
  repeat: { times: number; done: number } | null
  skills: string[]
  model: string | null
}
export interface AutomationInput { name?: string; schedule?: string; prompt?: string; deliver?: string }

const H = 3_600_000
let demoJobs: Automation[] = [
  { id: 'c669713a402c', profile: 'default', name: 'Moodle keep-alive', schedule: 'every 30m', expr: '', state: 'scheduled', nextAt: Date.now() + 0.4 * H, lastAt: Date.now() - 0.1 * H, lastStatus: 'ok', lastError: null, failures: 0, deliver: 'local', mode: 'script', script: 'moodle-keepalive.sh', prompt: '', repeat: null, skills: [], model: null },
  { id: '7a2fa221b143', profile: 'assistant', name: 'Morning briefing (daily 08:00)', schedule: '0 8 * * *', expr: '0 8 * * *', state: 'scheduled', nextAt: Date.now() + 7 * H, lastAt: Date.now() - 17 * H, lastStatus: 'ok', lastError: null, failures: 0, deliver: 'telegram', mode: 'agent', script: null, prompt: 'Write the morning briefing: calendar, deadlines, weather, the board.', repeat: null, skills: [], model: null },
  { id: '50a11b9ce171', profile: 'tutor', name: 'Sunday study plan', schedule: '0 18 * * 0', expr: '0 18 * * 0', state: 'paused', nextAt: null, lastAt: Date.now() - 150 * H, lastStatus: 'error', lastError: 'The model did not answer in time (timeout after 120 s).', failures: 1, deliver: 'telegram', mode: 'agent', script: null, prompt: 'Plan next week’s study blocks around the deadlines you know about.', repeat: null, skills: [], model: null },
  { id: 'cd1678c688ca', profile: 'coach', name: 'Stretch reminder', schedule: 'every day at 7:45am', expr: '45 7 * * *', state: 'scheduled', nextAt: Date.now() + 6.7 * H, lastAt: Date.now() - 17.3 * H, lastStatus: 'ok', lastError: null, failures: 0, deliver: 'origin', mode: 'agent', script: null, prompt: 'A two-line reminder to do ten minutes of stretching before breakfast.', repeat: { times: 14, done: 5 }, skills: [], model: null },
]

/** A systemd timer on the VM itself (not a Hermes job): read only. `described: false` = nobody added it to the registry yet. */
export interface VmTimer { unit: string; label: string; schedule: string; described: boolean; nextAt: number | null; lastAt: number | null }
const demoTimers = (): VmTimer[] => [{ unit: 'hermes-backup', label: 'Nightly backup to Google Drive (encrypted)', schedule: '*-*-* 03:30:00', described: true, nextAt: Date.now() + 9 * H, lastAt: Date.now() - 15 * H }]

export const automationsApi = {
  list: async (): Promise<Automation[]> => (await automationsApi.all()).jobs,
  /** The Hermes jobs and the VM's own timers in one read. */
  all: async (): Promise<{ jobs: Automation[]; timers: VmTimer[] }> => {
    if (!isLive()) return { jobs: demoJobs, timers: demoTimers() }
    const out = await api<{ jobs: Automation[]; timers?: VmTimer[] }>('/automations', { timeoutMs: 20_000 })
    return { jobs: out.jobs, timers: out.timers ?? [] }
  },
  act: async (a: Automation, verb: 'pause' | 'resume' | 'run'): Promise<Automation[]> => {
    if (isLive()) return (await api<{ jobs: Automation[] }>(`/automations/${a.profile}/${a.id}/${verb}`, { method: 'POST', body: {}, timeoutMs: 60_000 })).jobs
    demoJobs = demoJobs.map((j) => (j.id !== a.id ? j : verb === 'pause' ? { ...j, state: 'paused' } : verb === 'resume' ? { ...j, state: 'scheduled', nextAt: Date.now() + H } : { ...j, nextAt: Date.now() + 60_000 }))
    return demoJobs
  },
  edit: async (a: Automation, patch: AutomationInput): Promise<Automation[]> => {
    if (isLive()) return (await api<{ jobs: Automation[] }>(`/automations/${a.profile}/${a.id}`, { method: 'PUT', body: patch, timeoutMs: 60_000 })).jobs
    demoJobs = demoJobs.map((j) => (j.id === a.id ? { ...j, ...patch, schedule: patch.schedule ?? j.schedule } : j))
    return demoJobs
  },
  create: async (profile: string, input: Required<Pick<AutomationInput, 'schedule' | 'prompt'>> & AutomationInput): Promise<Automation[]> => {
    if (isLive()) return (await api<{ jobs: Automation[] }>('/automations', { method: 'POST', body: { profile, ...input }, timeoutMs: 60_000 })).jobs
    demoJobs = [...demoJobs, { id: Math.random().toString(16).slice(2, 14), profile, name: input.name ?? '', schedule: input.schedule, expr: input.schedule, state: 'scheduled',
      nextAt: Date.now() + H, lastAt: null, lastStatus: null, lastError: null, failures: 0, deliver: input.deliver ?? 'telegram', mode: 'agent', script: null, prompt: input.prompt, repeat: null, skills: [], model: null }]
    return demoJobs
  },
  remove: async (a: Automation): Promise<Automation[]> => {
    if (isLive()) return (await api<{ jobs: Automation[] }>(`/automations/${a.profile}/${a.id}`, { method: 'DELETE', body: {}, timeoutMs: 60_000 })).jobs
    demoJobs = demoJobs.filter((j) => j.id !== a.id)
    return demoJobs
  },
}

// -- the Integrations Hub ----------------------------------------------------------------------------------------------------

export type IntegrationStatus = 'connected' | 'expiring' | 'attention' | 'unknown' | 'off'
export interface IntegrationCard {
  id: string
  name: string
  kind: string
  status: IntegrationStatus
  usedBy: string[]
  /** Where the secret lives (a path, never a value). */
  secret: string
  facts: string[]
  fix: string
  /** false: found on the VM (an MCP server) but not described in the registry yet. */
  described: boolean
  /** false: kept on the VM but nothing uses it, or an add-on that is not switched on. */
  inUse: boolean
  /** The crew.json feature this optional add-on needs ('gmail', 'moodle', 'icloud', 'voice', 'backup'), or null. */
  addon?: string | null
  balance?: { value: number | null; currency?: string; limit?: number | null; resetAt?: number | null } | null
}
/** A suggestion from Hermes' MCP catalog that no agent has yet. `for`: the profiles it would go on. */
export interface Suggestion { catalog: string; name: string; for: string[]; agents: string[]; why: string; cost: string; description: string; auth: string | null; oneClick: boolean }
/** A secret name on the VM that no integration explains (the name and the file, never the value). */
export interface FoundKey { key: string; where: string[] }
export interface Hub { checkedAt: number | null; cards: IntegrationCard[]; found: FoundKey[]; suggestions: Suggestion[]; job?: string | null }

const D = 86_400_000
function demoHub(): Hub {
  const now = Date.now()
  const card = (c: Omit<IntegrationCard, 'described' | 'inUse'> & Partial<IntegrationCard>): IntegrationCard => ({ described: true, inUse: true, ...c })
  const all = ['atlas', 'sage', 'ivy', 'rocky']
  return { checkedAt: now - 12 * 60_000, cards: [
    card({ id: 'deepseek', name: 'DeepSeek', kind: 'API key (required)', status: 'connected', usedBy: all, secret: '/data/.hermes/.env and each profile’s .env (DEEPSEEK_API_KEY)', facts: ['the agents’ model, pay as you go'], balance: { value: 4.62, currency: 'USD' }, fix: 'top up at platform.deepseek.com' }),
    card({ id: 'gemini', name: 'Gemini', kind: 'API key (optional fallback)', status: 'connected', usedBy: all, secret: '/data/.hermes/.env (GEMINI_API_KEY)', facts: ['key works', 'used only when DeepSeek is down'], fix: 'a free key at aistudio.google.com/apikey' }),
    card({ id: 'telegram', name: 'Telegram', kind: 'bot tokens, one per agent (four bots)', status: 'connected', usedBy: all, secret: '/data/.hermes/.env and each profile’s .env (TELEGRAM_BOT_TOKEN)', facts: ['4 of 4 bots answering', '@atlas_demo_bot, @sage_demo_bot, @ivy_demo_bot, @rocky_demo_bot'], fix: 'a new token from @BotFather' }),
    card({ id: 'mem0', name: 'Mem0 (memory)', kind: 'runs on the VM', status: 'connected', usedBy: all, secret: '/data/.hermes/mem0-server/server.env and each profile’s .env (MEM0_API_KEY)', facts: ['mem0-server running'], fix: 'sudo systemctl status mem0-server on the VM' }),
    card({ id: 'weather', name: 'Open-Meteo weather', kind: 'free, no key', status: 'connected', usedBy: ['atlas', 'ivy', 'rocky'], secret: 'no secret', facts: ['no key needed', 'forecasts only'], fix: 'nothing to renew' }),
    card({ id: 'openalex', name: 'OpenAlex', kind: 'Hermes plugin, no key', status: 'connected', usedBy: ['sage'], secret: 'no secret', facts: ['plugin installed for Sage'], fix: 'hermes -p tutor plugins install openalex on the VM' }),
    card({ id: 'gmail', name: 'Gmail', kind: 'IMAP app password (add-on)', status: 'connected', usedBy: ['atlas', 'ivy'], addon: 'gmail', secret: '/data/.hermes/owner/.secrets/gmail.env', facts: ['login works', 'read and draft only: no sending, deleting or marking read'], fix: 'a new app password at myaccount.google.com/apppasswords' }),
    card({ id: 'moodle', name: 'Moodle', kind: 'session cookie, moodle-cli (add-on)', status: 'expiring', usedBy: ['atlas', 'sage', 'ivy'], addon: 'moodle', secret: '/data/.hermes/owner/.secrets/moodle.env', facts: ['cookie renewed 12 days ago', 'keep-alive ok 6 min ago'], fix: 'copy a fresh MoodleSession cookie from your browser, then a quiet restart' }),
    card({ id: 'icloud', name: 'iCloud Calendar', kind: 'CalDAV app-specific password (add-on)', status: 'connected', usedBy: ['sage', 'ivy'], addon: 'icloud', secret: '/data/.hermes/owner/.secrets/icloud.env', facts: ['signed in', 'Sage reads, Ivy writes'], fix: 'a new app-specific password at appleid.apple.com' }),
    card({ id: 'elevenlabs', name: 'ElevenLabs (voice replies)', kind: 'API key (add-on)', status: 'connected', usedBy: ['atlas'], addon: 'voice', secret: '/data/.hermes/.env (ELEVENLABS_API_KEY)', facts: ['resets in 27 days', 'free plan'], balance: { value: 5_790, limit: 10_000, resetAt: now + 27 * D }, fix: 'elevenlabs.io: subscription and API key' }),
    card({ id: 'drive', name: 'Google Drive (backups)', kind: 'rclone OAuth token (add-on)', status: 'connected', usedBy: [], addon: 'backup', secret: '/etc/hermes-backup/rclone.conf (root only)', facts: ['last backup success 20 h ago', 'encrypted archive to Google Drive'], fix: 'sign rclone in again if Google signs it out' }),
    card({ id: 'mcp:weather-plus', name: 'weather-plus', kind: 'MCP server (http)', status: 'connected', usedBy: ['rocky'], secret: 'env: WEATHER_PLUS_KEY', facts: ['on for Rocky', 'https://example.invalid/mcp'], fix: 'describe it in dashboard/bridge/registry.json', described: false }),
  ], found: [{ key: 'SPOTIFY_CLIENT_ID', where: ['coach .env'] }], suggestions: [
    { catalog: 'wolfram', name: 'Wolfram|Alpha', for: ['tutor'], agents: ['sage'], why: 'the tutor can check maths, physics and stats working step by step', cost: 'free', description: 'Wolfram|Alpha computation, math, and curated knowledge.', auth: 'none', oneClick: true },
    { catalog: 'strava', name: 'Strava', for: ['coach'], agents: ['rocky'], why: 'the coach sees your runs, rides and training load (read only)', cost: 'free · one Strava sign-in', description: 'Strava: activities, fitness trends, training load (read-only).', auth: 'oauth', oneClick: true },
    { catalog: 'kiwi', name: 'Kiwi.com flights', for: ['assistant'], agents: ['ivy'], why: 'the assistant finds cheap flights and links you to book yourself', cost: 'free', description: 'Kiwi.com flight search: itineraries with direct booking links.', auth: 'none', oneClick: true },
  ] }
}

export const integrationsApi = {
  /** The hub as it stands; when its checks are old the VM starts new ones (refresh forces that). */
  get: async (refresh = false): Promise<Hub> => {
    if (!isLive()) { await sleep(refresh ? 900 : 250); return demoHub() }
    const first = await api<Hub>(refresh ? '/integrations/refresh' : '/integrations', { method: refresh ? 'POST' : 'GET', body: refresh ? {} : undefined, timeoutMs: 20_000 })
    if (first.job && (refresh || !first.checkedAt)) {
      try { await job(Promise.resolve({ job: first.job }), 90_000) } catch { return first }
      return api<Hub>('/integrations', { timeoutMs: 20_000 })
    }
    return first
  },
}

// -- the registry: names and labels the VM cannot tell (dashboard/bridge/registry.json) --------------------------------------

export interface Registry {
  tools: Array<{ key: string; label: string; who: string[]; rule: string }>
  mcp: Record<string, string>
  roles: Record<string, string>
  /** Departments under the chief, drawn as lanes in Agent Studio. `members` report to the chief; their own workers follow `reportsTo`.
   * `planned`: workers written but not installed yet (shown greyed, with what they wait for). */
  teams?: Array<{ id: string; label: string; members: string[]; note: string
    planned?: Array<{ id: string; name: string; role: string; reportsTo: string; waits: string }> }>
  services: Record<string, { label: string; port: number | null; described: boolean }>
}

export const registryApi = {
  get: async (): Promise<Registry | null> => (isLive() ? api<Registry>('/registry') : null),
}

// -- the Inbox (read only) ---------------------------------------------------------------------------------------------------

export type Channel = 'gmail'
export interface Message {
  id: string
  channel: Channel
  folder: 'inbox' | 'drafts'
  uid: string
  from: { name: string; address: string }
  to: string
  subject: string
  at: number | null
  unread: boolean
  draft: boolean
  snippet: string
}
export interface MessageBody { id: string; from: { name: string; address: string }; to: string; cc: string; subject: string; at: number | null; attachments: string[]; body: string; truncated: boolean }
export interface InboxSummary { headline: string; points: Array<{ text: string; id: string | null }>; at: number; listAt?: number }
export interface InboxState { list: { at: number; messages: Message[] } | null; summary: InboxSummary | null; job?: string | null }

const H_ = 3_600_000
function demoInbox(): InboxState {
  const now = Date.now()
  const m = (i: number, name: string, address: string, subject: string, ago: number, unread: boolean, snippet: string, folder: 'inbox' | 'drafts' = 'inbox'): Message =>
    ({ id: `gmail:${folder}:${100 + i}`, channel: 'gmail', folder, uid: String(100 + i), from: { name, address }, to: 'sam@example.invalid', subject, at: now - ago, unread, draft: folder === 'drafts', snippet })
  const messages = [
    m(1, 'Dr Rivera', 'rivera@university.example', 'Statistics lab 2: submission reminder', 1.2 * H_, true, 'A reminder that lab 2 is due tomorrow at noon. Please upload your notebook and the short write-up…'),
    m(2, 'Swim Club', 'club@swim.example', 'Friday session moved to 19:30', 4 * H_, true, 'The pool is closed until 7 on Friday, so the session starts at 19:30. Reply if you can make it…'),
    m(3, 'Example Bank', 'help@bank.example', 'Your October statement is ready', 9 * H_, false, 'Your statement for September is ready to view in the app.'),
    m(4, 'Alex', 'alex@friends.example', 'Sunday dinner', 26 * H_, false, '6 o’clock is fine, can you bring dessert?'),
    m(5, 'City Dental', 'noreply@dental.example', 'Your check-up is booked', 30 * H_, false, 'Your appointment is confirmed for Thursday at 09:00.'),
    m(6, 'Game Store', 'noreply@games.example', 'Items on your wishlist are on sale', 50 * H_, false, 'Up to 60% off this weekend.'),
    m(7, 'Sam', 'sam@example.invalid', 'Re: Sunday dinner', 25 * H_, false, 'Sounds good, I’ll bring a cheesecake.', 'drafts'),
  ]
  return { list: { at: now - 3 * 60_000, messages }, summary: { at: now - 3 * 60_000, headline: 'Two things need you today: lab 2 is due tomorrow and the swim club wants a reply.', points: [
    { text: 'Statistics lab 2 is due tomorrow at noon: the notebook and a short write-up.', id: 'gmail:inbox:101' },
    { text: 'Friday’s swim moved to 19:30; they want to know if you are coming.', id: 'gmail:inbox:102' },
    { text: 'Your dental check-up is Thursday at 09:00.', id: 'gmail:inbox:105' },
    { text: 'Alex asked you to bring dessert on Sunday (you have a draft reply).', id: 'gmail:inbox:104' },
  ] } }
}
const DEMO_BODY: Record<string, string> = {
  'gmail:inbox:101': 'Dear all,\n\nA reminder that statistics lab 2 is due tomorrow at 12:00 noon.\n\nPlease upload your notebook and the short write-up through the course page.\n\nBest wishes,\nDr Rivera',
}

export const inboxApi = {
  get: async (refresh = false): Promise<InboxState> => {
    if (!isLive()) { await sleep(refresh ? 800 : 250); return demoInbox() }
    const first = await api<InboxState>(refresh ? '/inbox/refresh' : '/inbox', { method: refresh ? 'POST' : 'GET', body: refresh ? {} : undefined, timeoutMs: 20_000 })
    if (first.job && (refresh || !first.list)) {
      try { await job(Promise.resolve({ job: first.job }), 90_000) } catch { return first }
      return api<InboxState>('/inbox', { timeoutMs: 20_000 })
    }
    return first
  },
  read: async (m: Message): Promise<MessageBody> => {
    if (!isLive()) {
      await sleep(400)
      return { id: m.id, from: m.from, to: m.to, cc: '', subject: m.subject, at: m.at, attachments: [], body: DEMO_BODY[m.id] ?? `${m.snippet}\n\n(Demo: the full message would show here.)`, truncated: false }
    }
    return job<MessageBody>(api(`/inbox/${m.folder}/${m.uid}`, { timeoutMs: 20_000 }), 60_000)
  },
  summarise: async (): Promise<InboxSummary> => {
    if (!isLive()) { await sleep(1000); return demoInbox().summary! }
    const { job: id } = await api<{ job: string | null }>('/inbox/summary', { method: 'POST', body: {} })
    if (!id) throw new Error('The VM is busy; try again in a minute')
    return job<InboxSummary>(Promise.resolve({ job: id }), 90_000)
  },
}
