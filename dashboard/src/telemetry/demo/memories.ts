import type { AgentId, ClusterId, Memory } from '../types'
import { hash, pick, rng } from '@/lib/rng'

// Invented notes for demo mode, about a made-up owner called Sam. Nobody real; they only have the right shape and spread.
const TEXT: Record<ClusterId, readonly string[]> = {
  uni: [
    'Second-year student; lab sessions run on Tuesday and Thursday afternoons.',
    'Prefers to start coursework the weekend it is released, not the week it is due.',
    'Course deadlines are listed in UK time; reminders go out 48 hours and 6 hours before.',
    'Uses AI tools only within each course\'s stated rules; check the rules before helping with an assignment.',
    'Study blocks work best before 11:00; afternoons are for labs and reading.',
    'Keeps lecture notes in one document per week per course.',
    'Wants deadline summaries as a short list: course, task, due date, hours left.',
    'Statistics course: weekly problem sheet due Friday 16:00.',
    'Programming module first, lab write-up second, when both are due the same week.',
    'Reading lists come from the course page; OpenAlex is used to find the open-access version.',
    'Exam period starts mid-December; revision timetable to be drafted in November.',
    'Group project meetings are on Wednesdays; minutes go in the shared folder.',
    'Likes a worked example before the theory when learning something new.',
    'Tutorial attendance counts towards the grade in one course.',
    'Asks Sage for a ten-minute recap the evening before a lab.',
    'Library study rooms can be booked a week ahead.',
  ],
  admin: [
    'Morning briefing at 08:00: weather, calendar, deadlines, anything waiting on the board.',
    'Calendar lives in iCloud; Sage and Ivy both read it, only Ivy writes to it.',
    'Rent is paid on the first of the month by standing order.',
    'Weekly shop on Sunday; prefers a list grouped by aisle.',
    'Gmail: agents may read and draft, never send without a yes.',
    'Prefers reminders as a single Telegram line with the time first.',
    'Train tickets are cheaper booked 8 to 12 weeks ahead.',
    'Keeps a monthly budget; flag any single spend over £40.',
    'Laundry slot is Thursday evening.',
    'Weather checks matter for the walk to campus and for swimming.',
    'Doctor and dentist appointments go in the calendar with a day-before reminder.',
    'Bills folder in Drive, one subfolder per year.',
    'Bank card renewal due early next year.',
  ],
  fitness: [
    'Swims on Friday evenings at the local pool.',
    'Rain rule: if the chance of rain at session time is over 60 per cent, suggest an indoor option.',
    'Aims for a high-protein lunch on training days.',
    'Gym sessions Monday and Wednesday, 45 minutes, before lectures.',
    'Prefers plain-language nutrition advice, no calorie counting apps.',
    'Sleep target: in bed by 23:30 on weeknights.',
    'Stretching routine after swimming: ten minutes, hips and shoulders.',
    'Tracks steps on the phone; 8,000 is a good day.',
    'Rocky checks in on Sunday with a short plan for the week.',
    'Takes a rest day after two hard sessions in a row.',
    'Likes simple lunches that keep until the afternoon.',
    'Hydration reminder on long lab days.',
    'Wants exercise drills written as three steps at most.',
    'A cold usually means skip the gym, keep the walk.',
    'Running route along the river, about 5 km.',
  ],
  software: [
    'Learning Python this term; small scripts first, then a web app.',
    'Every change to the VM is done through Claude and written down in the repo.',
    'Hermes stays on its pinned release; no automatic updates.',
    'The VM is reachable only over Tailscale; there is no public SSH.',
    'MCP servers load at gateway start; restart only through the quiet-restart button.',
    'Secrets are typed at a hidden prompt, never pasted into chat.',
    'Tests run before every push; a red test is never skipped.',
    'Prefers Python standard library for small tools.',
    'Small, reviewable commits with a plain-English message.',
    'The budget for the VM is the student credit; flag anything that costs money.',
    'Back up configs before editing them.',
  ],
  people: [
    'Family calls go best on Sunday evenings.',
    'Flatmates share a group chat for bills and cleaning.',
    'Birthdays go in the calendar with a reminder a week ahead.',
    'A friend from the swim club organises the Friday sessions.',
    'Likes a nudge to reply to messages left over 24 hours.',
    'Messages to family are drafted for Sam to send themselves.',
    'Course group contacts are kept in the university directory.',
    'Prefers voice notes for longer updates from family.',
  ],
  rules: [
    'Replies on Telegram stay short; long answers become a document.',
    'Never send, buy, submit or delete without asking first.',
    'One current note per fact: search, then update or delete the stale one.',
    'Atlas speaks for the team; specialists report back to Atlas.',
    'Tone: friendly, direct, no filler.',
    'Never claim to be a person; say it is a computer program when asked sincerely.',
    'Ask one question at a time when something is unclear.',
    'Plain words; explain the money impact of any change.',
    'Voice replies to voice notes, text replies to text.',
    'Quiet hours 23:00 to 07:00.',
    'Confirm before anything that books or pays.',
    'Say what was done, not what will be done.',
    'Keep the budget tight; prefer free tiers.',
  ],
}

const AUTHORS: Record<ClusterId, readonly (AgentId | 'import')[]> = {
  uni: ['sage', 'sage', 'ivy', 'import', 'atlas'],
  admin: ['ivy', 'ivy', 'atlas', 'import'],
  fitness: ['rocky', 'rocky', 'import', 'ivy'],
  software: ['atlas', 'atlas', 'import'],
  people: ['atlas', 'ivy', 'import'],
  rules: ['atlas', 'import', 'import', 'ivy'],
}

const DAY = 86_400_000

/** About 80 notes, stable across loads (seeded), ages spread over the last few weeks. */
export function demoMemories(now = Date.now()): Memory[] {
  const out: Memory[] = []
  for (const [cluster, texts] of Object.entries(TEXT) as Array<[ClusterId, readonly string[]]>) {
    texts.forEach((text, i) => {
      const r = rng(hash(`${cluster}:${i}`))
      const author = pick(r, AUTHORS[cluster] ?? AUTHORS.rules!)
      const created = now - Math.floor(r() * 28 * DAY) - DAY / 3
      const edited = r() < 0.25 ? created + Math.floor(r() * (now - created)) : null
      out.push({
        id: `demo-${cluster}-${String(i).padStart(2, '0')}`,
        text,
        author,
        source: author === 'import' ? 'import' : null,
        category: null,
        createdAt: created,
        updatedAt: edited,
        metadata: author === 'import' ? { source: 'import', fact_id: Math.floor(r() * 145) + 1 } : {},
      })
    })
  }
  return out
}
