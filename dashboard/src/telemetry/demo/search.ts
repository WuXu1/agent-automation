import { tokens } from '../clusters'
import type { Memory, SearchHit } from '../types'

// Demo mode has no embedder: a word-overlap score with a few synonyms stands in for Mem0's vector search,
// and the search box says so.
const SYN: Record<string, string[]> = {
  swim: ['swimming', 'pool', 'lanes'],
  gym: ['workout', 'training', 'sessions'],
  food: ['protein', 'meal', 'lunch', 'nutrition', 'shop'],
  deadline: ['due', 'deadlines', 'coursework'],
  study: ['revision', 'reading', 'lecture', 'lab'],
  family: ['dad', 'mum', 'parents', 'sister', 'brother'],
  code: ['coding', 'project', 'commit', 'tests'],
  money: ['budget', 'rent', 'bills', 'cheaper', 'spend'],
  sleep: ['bed', 'rest'],
  rain: ['weather', 'indoor'],
  phone: ['call', 'calls', 'contract', 'mobile'],
}

export function demoSearch(memories: readonly Memory[], query: string, topK = 12): SearchHit[] {
  const q = new Set(tokens(query).filter((w) => w.length > 2))
  for (const w of [...q]) for (const s of SYN[w] ?? []) q.add(s)
  if (q.size === 0) return []
  const hits: SearchHit[] = []
  for (const m of memories) {
    const words = tokens(m.text)
    let score = 0
    for (const w of words) for (const t of q) if (w === t || (t.length > 4 && w.startsWith(t))) score++
    if (score > 0) hits.push({ id: m.id, score: Math.min(0.95, 0.35 + score / (words.length * 0.35 + 2)) })
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, topK)
}
