import { create } from 'zustand'
import { useBrain } from './hooks/useMem0Graph'
import { api } from './live/client'
import { useMode } from './mode'

// The Second Brain's weekly check-up (bridge/review.py): the AI proposes merges, rewrites, expiries and section fixes;
// nothing changes until you apply one. Pins ("always true") are never proposed for a change.

export type ReviewKind = 'merge' | 'update' | 'expire' | 'section-merge' | 'section-rename'
export interface ReviewNote { id: string; text: string; by: string; at: string }
export interface ReviewItem {
  id: string
  kind: ReviewKind
  why: string
  ids?: string[]
  before?: ReviewNote[]
  text?: string | null
  section?: string
  into?: string
  label?: string
  intoLabel?: string
  newLabel?: string
  blurb?: string
  notes?: number
}
export interface ReviewView { at: number | null; running: boolean; items: ReviewItem[]; pins: string[]; nextAt: number | null }

const isLive = () => useMode.getState().mode === 'live'
const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms))
const DAY = 86_400_000

/** Demo: a few believable suggestions made from whatever demo notes are loaded. */
function demoView(pins: string[]): ReviewView {
  const ms = useBrain.getState().memories
  const pick = (re: RegExp) => ms.find((m) => re.test(m.text) && !pins.includes(m.id))
  const note = (m: (typeof ms)[number]) => ({ id: m.id, text: m.text, by: m.author, at: new Date(m.createdAt).toISOString().slice(0, 10) })
  const a = pick(/swim/i)
  const b = a && ms.find((m) => m.id !== a.id && /swim/i.test(m.text) && !pins.includes(m.id))
  const dated = pick(/\b(due|deadline|Friday|Monday|Tuesday|tomorrow|today|week|\d{1,2} (Oct|Nov|Sep))\b/i)
  const long = [...ms].filter((m) => !pins.includes(m.id) && m.id !== a?.id && m.id !== b?.id && m.id !== dated?.id).sort((x, y) => y.text.length - x.text.length)[0]
  const items: ReviewItem[] = []
  if (a && b) items.push({ id: 'demo00000001', kind: 'merge', why: 'Two notes say the same thing about swimming', ids: [a.id, b.id], before: [note(a), note(b)], text: `${a.text.replace(/\.$/, '')}; ${b.text.charAt(0).toLowerCase()}${b.text.slice(1)}` })
  if (dated) items.push({ id: 'demo00000002', kind: 'expire', why: 'The date in this note has passed', ids: [dated.id], before: [note(dated)], text: null })
  if (long) items.push({ id: 'demo00000003', kind: 'update', why: 'Shorter and clearer, every fact kept', ids: [long.id], before: [note(long)], text: long.text.split(/(?<=\.)\s/).slice(0, 2).join(' ') })
  // the smallest section folds into the biggest
  const { graph, sections } = useBrain.getState()
  const count = (id: string) => graph.nodes.filter((n) => n.cluster === id).length
  const sized = sections.map((x) => ({ ...x, n: count(x.id) })).filter((x) => x.n > 0).sort((x, y) => x.n - y.n)
  const small = sized[0]
  const big = sized[sized.length - 1]
  if (small && big && small.id !== big.id) items.push({ id: 'demo00000004', kind: 'section-merge', why: `${small.label} is small and overlaps ${big.label}`, section: small.id, into: big.id, label: small.label, intoLabel: big.label, notes: small.n })
  return { at: Date.now() - 2 * DAY, running: false, items: items.filter((i) => !demoDone.has(i.id)), pins, nextAt: Date.now() + 5 * DAY }
}
const demoDone = new Set<string>()
let demoPins: string[] = []

export const reviewApi = {
  get: async (): Promise<ReviewView> => (isLive() ? api<ReviewView>('/brain/review') : demoView(demoPins)),
  check: async (): Promise<void> => {
    if (!isLive()) { await sleep(1500); demoDone.clear(); return }
    await api<{ job: string }>('/brain/review', { method: 'POST', body: {}, timeoutMs: 60_000 })
  },
  apply: async (item: ReviewItem): Promise<ReviewView> => {
    if (isLive()) return api<ReviewView>(`/brain/review/${item.id}/apply`, { method: 'POST', body: {}, timeoutMs: 30_000 })
    // demo: the same change, in this tab only
    const brain = useBrain.getState()
    if (item.kind === 'merge' && item.ids && item.text) { await brain.update(item.ids[0]!, item.text); for (const id of item.ids.slice(1)) await brain.remove(id) }
    if (item.kind === 'update' && item.ids && item.text) await brain.update(item.ids[0]!, item.text)
    if (item.kind === 'expire' && item.ids) await brain.remove(item.ids[0]!)
    demoDone.add(item.id)
    return demoView(demoPins)
  },
  dismiss: async (item: ReviewItem): Promise<ReviewView> => {
    if (isLive()) return api<ReviewView>(`/brain/review/${item.id}/dismiss`, { method: 'POST', body: {} })
    demoDone.add(item.id)
    return demoView(demoPins)
  },
  pin: async (id: string, pinned: boolean): Promise<string[]> => {
    if (isLive()) return (await api<{ pins: string[] }>(`/memories/${encodeURIComponent(id)}/pin`, { method: 'PUT', body: { pinned } })).pins
    demoPins = pinned ? [...demoPins.filter((p) => p !== id), id] : demoPins.filter((p) => p !== id)
    return demoPins
  },
}

interface ReviewStore {
  view: ReviewView | null
  open: boolean
  busy: boolean
  error: string | null
  setOpen: (open: boolean) => void
  load: () => Promise<void>
  check: () => Promise<void>
  apply: (item: ReviewItem) => Promise<void>
  dismiss: (item: ReviewItem) => Promise<void>
  pin: (id: string, pinned: boolean) => Promise<void>
}

const msg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong')

export const useReview = create<ReviewStore>((set, get) => ({
  view: null,
  open: false,
  busy: false,
  error: null,
  setOpen: (open) => set({ open }),
  load: async () => { try { set({ view: await reviewApi.get(), error: null }) } catch (e) { set({ error: msg(e) }) } },
  check: async () => {
    set({ busy: true, error: null })
    try { await reviewApi.check(); await get().load() } catch (e) { set({ error: msg(e) }) } finally { set({ busy: false }) }
  },
  apply: async (item) => {
    set({ error: null })
    try {
      set({ view: await reviewApi.apply(item) })
      if (isLive()) { await useBrain.getState().refresh() }
    } catch (e) { set({ error: msg(e) }); throw e }
  },
  dismiss: async (item) => { try { set({ view: await reviewApi.dismiss(item), error: null }) } catch (e) { set({ error: msg(e) }) } },
  pin: async (id, pinned) => {
    const pins = await reviewApi.pin(id, pinned)
    set((s) => ({ view: s.view ? { ...s.view, pins } : { at: null, running: false, items: [], pins, nextAt: null } }))
    await get().load()                                   // a pin drops open suggestions about that note
  },
}))
