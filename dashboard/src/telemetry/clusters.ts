import type { ClusterId, Memory } from './types'

export interface Cluster {
  id: ClusterId
  label: string
  blurb: string
  /** Tints of the memory cyan, shifted in hue and lightness; never a semantic colour. */
  color: string
  words: readonly string[]
}

// The eight built-in sections (bridge/brain.py BUILTIN). Words are matched on whole-word stems.
export const CLUSTERS: readonly Cluster[] = [
  {
    id: 'uni', label: 'Study & courses', blurb: 'Courses, deadlines, exams, study plans', color: '#00f0ff',
    words: ['moodle', 'course', 'lecture', 'lab', 'deadline', 'exam', 'tutorial', 'essay', 'uni', 'school', 'college',
      'university', 'module', 'assignment', 'study', 'semester', 'coursework', 'openalex', 'reading', 'grade', 'revision'],
  },
  {
    id: 'admin', label: 'Everyday & admin', blurb: 'Calendar, routines, travel, shopping', color: '#7dd3fc',
    words: ['calendar', 'icloud', 'routine', 'flight', 'travel', 'grocer', 'shopping', 'rent', 'bill', 'morning', 'briefing',
      'reminder', 'weather', 'appointment', 'email', 'gmail', 'budget', 'bank', 'laundry', 'errand'],
  },
  {
    id: 'health', label: 'Health & wellbeing', blurb: 'Conditions, medication, sleep, check-ups', color: '#6ee7b7',
    words: ['health', 'medication', 'medicine', 'doctor', 'dentist', 'dose', 'symptom', 'sleep', 'insomnia', 'supplement',
      'pain', 'allergy', 'prescription', 'check-up', 'checkup', 'therapy', 'stress', 'cold'],
  },
  {
    id: 'fitness', label: 'Fitness & food', blurb: 'Training, sport, meals and goals', color: '#2dd4bf',
    words: ['swim', 'swimming', 'pool', 'gym', 'run', 'running', 'workout', 'fitness', 'protein', 'nutrition', 'meal', 'lunch',
      'calorie', 'rain', 'stretch', 'stretching', 'coach', 'training', 'steps', 'diet', 'sport', 'exercise'],
  },
  {
    id: 'software', label: 'Projects & tech', blurb: 'Projects, code, the server and its tools', color: '#a5f3fc',
    words: ['code', 'coding', 'github', 'repo', 'python', 'typescript', 'deploy', 'vm', 'server', 'commit', 'branch',
      'test', 'bug', 'api', 'hermes', 'mcp', 'model', 'tailscale', 'project', 'script'],
  },
  {
    id: 'people', label: 'People & contacts', blurb: 'Real people in your life, how to reach them', color: '#60a5fa',
    words: ['dad', 'mum', 'mother', 'father', 'parents', 'family', 'friend', 'sister', 'brother', 'contact', 'birthday',
      'flatmate', 'flatmates', 'girlfriend', 'boyfriend', 'partner'],
  },
  {
    id: 'rules', label: 'Assistant rules', blurb: 'Safety lines, tone, how to work', color: '#e0f2fe',
    words: ['never', 'always', 'rule', 'tone', 'prefer', 'prefers', 'style', 'reply', 'confirm', 'ask', 'approval', 'safety',
      'telegram', 'voice', 'concise', 'soul', 'persona', 'language', 'quiet'],
  },
  {
    id: 'interests', label: 'Interests & hobbies', blurb: 'Music, games, things outside work and study', color: '#93c5fd',
    words: ['music', 'concert', 'album', 'film', 'films', 'book', 'books', 'gaming', 'games', 'hobby', 'art', 'drawing',
      'photography', 'cooking', 'hiking'],
  },
]

export const CLUSTER_BY_ID = new Map<ClusterId, Cluster>(CLUSTERS.map((c) => [c.id, c]))

/** A section as the brain shows it: the eight above, plus any the AI started (bridge/brain.py). */
export interface Section { id: ClusterId; label: string; blurb: string; color: string; builtin: boolean }

// New sections get cool tints near the memory cyan, picked by id so a section keeps its colour.
const PALETTE = ['#38bdf8', '#5eead4', '#93c5fd', '#67e8f9', '#a5b4fc', '#99f6e4', '#bae6fd', '#c4b5fd', '#6ee7b7', '#7dd3fc']

export function withColours(list: ReadonlyArray<{ id: string; label: string; blurb?: string; builtin?: boolean }>): Section[] {
  return list.map((s) => {
    const known = CLUSTER_BY_ID.get(s.id)
    let h = 0
    for (const ch of s.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
    return { id: s.id, label: s.label, blurb: s.blurb ?? '', builtin: Boolean(s.builtin), color: known?.color ?? PALETTE[h % PALETTE.length]! }
  })
}

export const BUILTIN_SECTIONS: Section[] = withColours(CLUSTERS.map((c) => ({ ...c, builtin: true })))

// Imported categories that map straight onto a theme.
const CATEGORY_HINT: Record<string, ClusterId> = {
  study: 'uni', university: 'uni', academic: 'uni', education: 'uni',
  health: 'health', medical: 'health', fitness: 'fitness', sport: 'fitness', nutrition: 'fitness',
  interests: 'interests', hobbies: 'interests',
  contacts: 'people', family: 'people', relationships: 'people', people: 'people',
  preferences: 'rules', rules: 'rules', instructions: 'rules',
  tech: 'software', software: 'software', project: 'software', development: 'software',
  admin: 'admin', schedule: 'admin', finance: 'admin', travel: 'admin',
}

const WORD = /[a-z][a-z0-9]+/g

export function tokens(text: string): string[] {
  return text.toLowerCase().match(WORD) ?? []
}

/** Picks the theme with the most matching words; ties and no match fall back to the category hint, then 'rules'. */
export function classify(memory: Pick<Memory, 'text' | 'category'>): ClusterId {
  const hint = memory.category ? CATEGORY_HINT[memory.category.toLowerCase()] : undefined
  const words = tokens(memory.text)
  let best: ClusterId | undefined
  let bestScore = 0
  for (const c of CLUSTERS) {
    let score = 0
    for (const w of words) {
      for (const stem of c.words) {
        if (w === stem || (stem.length > 3 && w.startsWith(stem))) { score++; break }
      }
    }
    if (c.id === hint) score += 1.5
    if (score > bestScore) { bestScore = score; best = c.id }
  }
  return best ?? hint ?? 'rules'
}
