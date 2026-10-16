import { studioFeed, type Clip, type Line, type Post, type Sound, type StudioStatus } from '../studio'

// Made-up content studio for demo mode: a calm page about quiet scenes, so every control has something to act on.

const day = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10)
const ago = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString()

const CLIPS: Clip[] = ([
  ['Loch at dawn', 'still water, low mist, pale light', 'calm'], ['Glen Coe road', 'empty road through the hills', 'open'], ['Rain on the window', 'rain running down glass, soft grey', 'tender'],
  ['Pier at dusk', 'a wooden pier, orange light fading', 'wistful'], ['Heather hillside', 'wind moving through purple heather', 'calm'], ['Harbour boats', 'small boats rocking at anchor', 'quiet'],
] as Array<[string, string, string]>).map(([name, summary, mood], i): Clip => ({
  id: `c_demo000${i}`, name, duration: 12 + i, added: ago(i + 1), bytes: 38_000_000 + i * 3_000_000, tagged: i !== 5, disabled: i === 2, disabledReason: i === 2 ? 'switched off by you' : '', lastUsed: i < 3 ? ago(3 + i) : null, uses: i < 3 ? 1 : 0,
  tags: i === 5 ? null : { summary, mood, scene: 'landscape', time_of_day: 'dawn', weather: 'overcast', calm: 9, quality: 8, text_zone: 'bottom', has_people: false, problems: [] }, thumb: '',
}))
const LINES: Line[] = ([
  'could you let go of this feeling holding you back', 'what you want wants you', 'could you rest here for a moment', 'could you stop waiting to feel ready', 'nothing is asking you to hurry',
] as string[]).map((text, i): Line => ({ id: `l_demo000${i}`, text, kind: 'line', status: i === 4 ? 'suggested' : 'approved', tags: [], source: i === 4 ? 'agent' : 'owner', added: ago(10 - i), uses: [], last_used: i === 0 ? ago(3) : null, note: '' }))
  .concat([{ id: 'l_demo0009', text: 'the Sedona Method is a quiet way to let feelings go: link in my bio', kind: 'cta', status: 'approved', tags: [], source: 'owner', added: ago(9), uses: [], last_used: null, note: '' } as Line])
const SOUNDS: Sound[] = [
  { id: 's_demo0000', url: 'https://www.tiktok.com/music/Limerence-7123456789', title: 'Limerence', artist: 'Yves Tumor', mood: ['wistful'], notes: '', added: ago(12), uses: [], last_used: ago(2), disabled: false },
  { id: 's_demo0001', url: 'https://www.tiktok.com/music/Digital-Bath-7234567890', title: 'Digital Bath', artist: 'Deftones', mood: ['dreamy'], notes: '', added: ago(11), uses: [], last_used: null, disabled: false },
]
const post = (i: number, status: Post['status'], over: Partial<Post> = {}): Post => {
  const L = LINES[i % 4]!, C = CLIPS[i]!, S = SOUNDS[i % 2]!
  return {
  id: `p_demo000${i}`, due: day(i === 0 ? -1 : i * 2), status, kind: 'line', caption: 'Could you let the thoughts that hold you in place go? #scotland', note: '',
  line: { id: L.id, text: L.text }, clip: { id: C.id, name: C.name, thumb: '' }, sound: { id: S.id, title: S.title, artist: S.artist, url: S.url },
  render: { video: '', still: null, seconds: 15, bytes: 6_500_000, problems: [], rows: [], at: ago(0) }, making: false, approvedAt: null, postedAt: null, created: ago(1), ...over,
  }
}

export function demoStudio(): StudioStatus {
  const queue = [post(0, 'posted', { postedAt: ago(1) }), post(1, 'ready'), post(2, 'proposed', { render: null, making: true }), post(3, 'approved', { approvedAt: ago(0) })]
  return {
    at: Date.now(), installed: true, name: 'Content studio',
    crew: ([['contentdirector', 'Content Director', 'Plans the posts and pairs clips, lines and sounds'], ['clipcurator', 'Clip Curator', 'Watches each new clip once and tags it'],
      ['overlaycopywriter', 'Overlay Copywriter', 'Writes overlay lines for you to approve'], ['videoeditor', 'Video Editor', 'Makes the finished 15-second videos']] as Array<[string, string, string]>)
      .map(([id, name, role]) => ({ id, name, role, installed: true })),
    activity: [{ id: 't_demo1', title: 'Render the next post', status: 'running', assignee: 'videoeditor', at: Date.now() - 120_000 }, { id: 't_demo2', title: 'Plan the next posts', status: 'done', assignee: 'contentdirector', at: Date.now() - 3_600_000 }],
    settings: { post_every_days: 2, plan_days: 7, post_seconds: 15, clip_rest_days: 30, line_rest_days: 60, sound_rest_days: 7, cta_every: 6, caption_hashtags: ['#scotland'], page_name: 'Could you?', page_brief: 'a calm, meditative page of raw, quiet Scottish scenes with a few plain words laid over them' },
    style: { font: '', size_pct: 4.6, color: 'white', shadow: true, outline_px: 0, position: 'auto', max_width_pct: 80, align: 'center', fade_in_s: 0.6, start_s: 0.4, line_spacing_pct: 28 },
    needs: { clips: 6, clips_untagged: 1, clips_free: 3, lines_approved_free: 3, cta_lines_free: 1, lines_suggested: 1, sounds_free: 1, posts: { proposed: 1, ready: 1, approved: 1, delivered: 0, posted: 1, skipped: 0 }, days_planned_ahead: 6 },
    disk: { freeGB: 18.4 }, worker: { busy: { verb: 'render', what: 'p_demo0002', since: new Date().toISOString() }, last: null, failures: [], waiting: [{ verb: 'render', post: 'p_demo0002' }] },
    clips: CLIPS, lines: LINES, sounds: SOUNDS, queue, fonts: [],
  }
}

export function editDemoStudio(f: (s: StudioStatus) => StudioStatus): void {
  const cur = studioFeed.getState().data ?? demoStudio()
  studioFeed.setState({ data: f(cur), at: Date.now() })
}
