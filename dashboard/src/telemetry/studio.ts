import { api } from './live/client'
import { makeFeed, reloadFeed, useFeed } from './feed'
import { demoStudio, editDemoStudio } from './demo/studio'
import { useMode } from './mode'

// The content studio page (bridge/studio.py): the clips, overlay lines, TikTok sounds and the queue of planned posts. Every write below is one of the owner's own moves;
// the bridge makes it through the same functions the agents use, so the rules (rest days, "only approved lines", "a post is locked once approved") hold for both.

export type PostStatus = 'proposed' | 'ready' | 'approved' | 'delivered' | 'posted' | 'skipped'
export interface Crew { id: string; name: string; role: string; installed: boolean }
export interface Activity { id: string; title: string; status: string; assignee: string | null; at: number }
export interface Settings {
  post_every_days: number; plan_days: number; post_seconds: number; clip_rest_days: number; line_rest_days: number; sound_rest_days: number; cta_every: number
  caption_hashtags: string[]; page_name: string; page_brief: string
}
export interface Style {
  font: string; size_pct: number; color: string; shadow: boolean; outline_px: number; position: 'auto' | 'top' | 'center' | 'bottom'; max_width_pct: number
  align: 'center' | 'left'; fade_in_s: number; start_s: number; line_spacing_pct: number
}
export interface Needs {
  clips: number; clips_untagged: number; clips_free: number; lines_approved_free: number; cta_lines_free: number; lines_suggested: number; sounds_free: number
  posts: Record<PostStatus, number>; days_planned_ahead: number
}
export interface ClipTags { summary?: string; mood?: string; scene?: string; time_of_day?: string; weather?: string; calm?: number; quality?: number; text_zone?: string; has_people?: boolean; problems?: string[] }
export interface Clip { id: string; name: string; duration: number | null; added: string | null; bytes: number | null; tagged: boolean; tags: ClipTags | null; disabled: boolean; disabledReason: string; lastUsed: string | null; uses: number; thumb: string }
export interface Line { id: string; text: string; kind: 'line' | 'cta'; status: 'approved' | 'suggested' | 'retired'; tags: string[]; source: string; added: string; uses: unknown[]; last_used: string | null; note: string }
export interface Sound { id: string; url: string; title: string; artist: string; mood: string[]; notes: string; added: string; uses: unknown[]; last_used: string | null; disabled: boolean }
export interface PostRender { video: string; still: string | null; seconds: number | null; bytes: number | null; problems: string[]; rows: string[]; at: string | null }
export interface Post {
  id: string; due: string | null; status: PostStatus; kind: 'line' | 'cta'; caption: string; note: string
  line: { id: string; text: string } | null; clip: { id: string; name: string; thumb: string } | null
  sound: { id: string; title: string; artist: string; url: string } | null
  render: PostRender | null; making: boolean; approvedAt: string | null; postedAt: string | null; created: string | null
}
export interface Worker { busy: { verb: string; what: string; since: string } | null; last: { verb: string; what: string; ok: boolean; at: string; error?: string } | null; failures: { kind: string; what: string; message: string; at: string }[]; waiting: { verb: string; name?: string; clip?: string; post?: string }[] }
export interface StudioStatus {
  at: number; installed: boolean; name: string; crew: Crew[]; activity: Activity[]
  settings?: Settings; style?: Style; needs?: Needs; disk?: { freeGB: number }; worker?: Worker
  clips?: Clip[]; lines?: Line[]; sounds?: Sound[]; queue?: Post[]; fonts?: string[]
}

export const studioFeed = makeFeed<StudioStatus>({ path: '/studio/status', everyMs: 6000, demo: demoStudio })
export const useStudio = () => useFeed(studioFeed)

const isLive = () => useMode.getState().mode === 'live'

/** One write: live it goes to the bridge and the page re-reads; in the demo the made-up state is edited in place so the controls still do something. */
async function write<T>(method: 'POST' | 'DELETE', path: string, body: unknown, demo: (s: StudioStatus) => StudioStatus, timeoutMs = 20_000): Promise<T | undefined> {
  if (!isLive()) { editDemoStudio(demo); return undefined }
  const out = await api<T>(path, { method, body: method === 'DELETE' ? undefined : (body ?? {}), timeoutMs })
  await reloadFeed(studioFeed)
  return out
}
const patchPost = (id: string, f: (p: Post) => Post) => (s: StudioStatus): StudioStatus => ({ ...s, queue: (s.queue ?? []).map((p) => (p.id === id ? f(p) : p)) })

export const studio = {
  plan: () => write<{ card: string | null }>('POST', '/studio/plan', {}, (s) => s, 30_000),
  propose: (days?: number) => write<{ added: number; short: string[] }>('POST', '/studio/propose', days ? { days } : {}, (s) => s, 30_000),
  post: (id: string, body: Record<string, unknown>) => write('POST', `/studio/queue/${id}`, body, patchPost(id, (p) => {
    const a = body.action
    if (a === 'approve') return { ...p, status: 'approved', approvedAt: new Date().toISOString() }
    if (a === 'unapprove') return { ...p, status: 'ready', approvedAt: null }
    if (a === 'skip') return { ...p, status: 'skipped' }
    if (a === 'unskip') return { ...p, status: p.render ? 'ready' : 'proposed' }
    if (a === 'posted') return { ...p, status: 'posted', postedAt: new Date().toISOString() }
    if (a === 'set' && typeof body.caption === 'string') return { ...p, caption: body.caption }
    return p
  })),
  clip: (id: string, body: Record<string, unknown>) => write('POST', `/studio/clips/${id}`, body, (s) => ({ ...s, clips: (s.clips ?? []).map((c) => (c.id !== id ? c : {
    ...c, disabled: body.action === 'disable' ? true : body.action === 'enable' ? false : c.disabled, name: body.action === 'rename' ? String(body.name) : c.name }))})),
  deleteClip: (id: string) => write('DELETE', `/studio/clips/${id}`, undefined, (s) => ({ ...s, clips: (s.clips ?? []).filter((c) => c.id !== id) })),
  addLines: (texts: string[], kind: 'line' | 'cta') => write<{ added: string[]; skipped: { text: string; why: string }[] }>('POST', '/studio/lines', { texts, kind }, (s) => ({ ...s, lines: [
    ...texts.map((t, i): Line => ({ id: `l_demo${Date.now()}${i}`, text: t, kind, status: 'approved', tags: [], source: 'owner', added: new Date().toISOString(), uses: [], last_used: null, note: '' })), ...(s.lines ?? [])] })),
  line: (id: string, body: Record<string, unknown>) => write('POST', `/studio/lines/${id}`, body, (s) => ({ ...s, lines: (s.lines ?? []).map((l) => (l.id === id ? { ...l, ...body } as Line : l)) })),
  deleteLine: (id: string) => write('DELETE', `/studio/lines/${id}`, undefined, (s) => ({ ...s, lines: (s.lines ?? []).filter((l) => l.id !== id) })),
  addSound: (url: string, title: string, artist: string) => write('POST', '/studio/sounds', { url, title, artist }, (s) => ({ ...s, sounds: [
    { id: `s_demo${Date.now()}`, url, title, artist, mood: [], notes: '', added: new Date().toISOString(), uses: [], last_used: null, disabled: false }, ...(s.sounds ?? [])] })),
  sound: (id: string, body: Record<string, unknown>) => write('POST', `/studio/sounds/${id}`, body, (s) => ({ ...s, sounds: (s.sounds ?? []).map((x) => (x.id === id ? { ...x, ...body } as Sound : x)) })),
  deleteSound: (id: string) => write('DELETE', `/studio/sounds/${id}`, undefined, (s) => ({ ...s, sounds: (s.sounds ?? []).filter((x) => x.id !== id) })),
  settings: (body: Partial<Settings>) => write('POST', '/studio/settings', body, (s) => ({ ...s, settings: { ...s.settings!, ...body } })),
  style: (body: Partial<Style>) => write('POST', '/studio/style', body, (s) => ({ ...s, style: { ...s.style!, ...body } })),
  clearFailures: () => write('POST', '/studio/failures/clear', {}, (s) => ({ ...s, worker: s.worker ? { ...s.worker, failures: [] } : s.worker })),
  voice: () => (isLive() ? api<{ text: string }>('/studio/voice') : Promise.resolve({ text: demoVoice })),
  saveVoice: async (text: string) => { if (isLive()) await api('/studio/voice', { method: 'POST', body: { text } }) },
}
const demoVoice = 'Short, plain, second person. Always starts with "could you" or says what you want wants you. Never advice, never hashtags, no emoji. Calm, a little tender.'

/** Sends one file with progress (XMLHttpRequest: fetch cannot report upload progress). The bridge refuses with a plain reason (name, type, size, room). */
export function uploadStudioFile(kind: 'clips' | 'fonts', file: File, onProgress: (sent: number, total: number) => void, signal?: AbortSignal): Promise<void> {
  if (!isLive()) {
    return new Promise((resolve, reject) => {                         // demo: pretend, so the progress bar can be seen
      let n = 0
      const id = window.setInterval(() => { n += 0.2; onProgress(Math.min(n, 1) * file.size, file.size); if (n >= 1) { window.clearInterval(id); resolve() } }, 250)
      signal?.addEventListener('abort', () => { window.clearInterval(id); reject(new DOMException('Cancelled', 'AbortError')) })
    })
  }
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `/api/studio/${kind}/${encodeURIComponent(file.name)}`)
    xhr.setRequestHeader('X-Hermes-Dash', '1')
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total) }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { onProgress(file.size, file.size); void reloadFeed(studioFeed); resolve(); return }
      let msg = `The server answered ${xhr.status}`
      try { const j = JSON.parse(xhr.responseText) as { error?: string }; if (j.error) msg = j.error } catch { /* not JSON */ }
      reject(new Error(msg))
    }
    xhr.onerror = () => reject(new Error('The upload was cut off (the connection dropped)'))
    xhr.ontimeout = () => reject(new Error('The upload timed out'))
    signal?.addEventListener('abort', () => { xhr.abort(); reject(new DOMException('Cancelled', 'AbortError')) })
    xhr.send(file)
  })
}
