import { Save } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { studio, type Settings, type Style, type StudioStatus } from '@/telemetry/studio'
import { Button } from '@/ui/Button'
import { Panel } from '@/ui/Panel'
import { ErrorNote, UploadZone, useAct } from './shared'

const field = 'w-full rounded-md border border-line-strong bg-void px-2 py-1 text-[13px] text-ink'

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12px] text-ink-dim">{label}</span>
      <div className="mt-0.5">{children}</div>
      {hint && <span className="mt-0.5 block text-2xs text-ink-faint">{hint}</span>}
    </label>
  )
}

function Num({ value, onChange, min, max, step = 1 }: { value: number; onChange: (n: number) => void; min: number; max: number; step?: number }) {
  return <input type="number" className={field} value={value} min={min} max={max} step={step} onChange={(e) => { const n = Number(e.target.value); if (Number.isFinite(n)) onChange(n) }} />
}

/** A phone-shaped sketch of how the words will sit; the real video is the check, this is only a hint for the sliders. */
function Sketch({ st, text }: { st: Style; text: string }) {
  const place = st.position === 'top' ? 'top-[12%]' : st.position === 'bottom' ? 'bottom-[14%]' : 'top-1/2 -translate-y-1/2'
  const color = st.color === 'auto' ? 'white' : st.color
  return (
    <div className="relative mx-auto aspect-[9/16] w-40 overflow-hidden rounded-xl border border-line" style={{ backgroundImage: 'linear-gradient(170deg,#51635f,#1d2a2a)' }} aria-label="Sketch of the text on a video">
      <p className={`absolute inset-x-0 mx-auto leading-snug font-medium ${place}`}
        style={{ width: `${st.max_width_pct}%`, color, textAlign: st.align, fontSize: `${st.size_pct * 1.9}px`, lineHeight: 1 + st.line_spacing_pct / 100, textShadow: st.shadow ? '0 1px 6px rgba(0,0,0,.7)' : 'none',
          WebkitTextStroke: st.outline_px ? `${Math.min(st.outline_px, 3) / 2}px black` : undefined }}>{text}</p>
    </div>
  )
}

export function StyleTab({ s }: { s: StudioStatus }) {
  const [cfgDraft, setCfgDraft] = useState<Settings | null>(null)
  const [styDraft, setStyDraft] = useState<Style | null>(null)
  const [tagsDraft, setTagsDraft] = useState<string | null>(null)
  const [voice, setVoice] = useState<string | null>(null)
  const a = useAct()
  const b = useAct()
  const c = useAct()
  // the form shows what the server has until a field is touched; then the edits are kept until saved
  const cfg = cfgDraft ?? s.settings ?? null
  const sty = styDraft ?? s.style ?? null
  const tags = tagsDraft ?? (s.settings?.caption_hashtags ?? []).join(' ')
  const dirtyCfg = cfgDraft !== null || tagsDraft !== null
  const dirtySty = styDraft !== null
  const setTags = (t: string) => setTagsDraft(t)

  useEffect(() => { let on = true; void studio.voice().then((v) => { if (on) setVoice(v.text) }).catch(() => { if (on) setVoice('') }); return () => { on = false } }, [])

  if (!cfg || !sty) return null
  const up = <K extends keyof Settings>(k: K, v: Settings[K]) => setCfgDraft({ ...cfg, [k]: v })
  const us = <K extends keyof Style>(k: K, v: Style[K]) => setStyDraft({ ...sty, [k]: v })
  const fonts = s.fonts ?? []

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel title="How often, and what the page is" aside={dirtyCfg && <span className="text-2xs text-[#fcd34d]">unsaved</span>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Row label="A post every … days" hint="1 or 2 to start"><Num value={cfg.post_every_days} min={1} max={14} onChange={(n) => up('post_every_days', n)} /></Row>
          <Row label="Plan … days ahead"><Num value={cfg.plan_days} min={1} max={30} onChange={(n) => up('plan_days', n)} /></Row>
          <Row label="Video length (seconds)"><Num value={cfg.post_seconds} min={5} max={60} onChange={(n) => up('post_seconds', n)} /></Row>
          <Row label="Book line every … posts" hint="0 = never mention the book"><Num value={cfg.cta_every} min={0} max={50} onChange={(n) => up('cta_every', n)} /></Row>
          <Row label="Rest a scene for … days"><Num value={cfg.clip_rest_days} min={0} max={365} onChange={(n) => up('clip_rest_days', n)} /></Row>
          <Row label="Rest a line for … days"><Num value={cfg.line_rest_days} min={0} max={365} onChange={(n) => up('line_rest_days', n)} /></Row>
          <Row label="Rest a sound for … days"><Num value={cfg.sound_rest_days} min={0} max={365} onChange={(n) => up('sound_rest_days', n)} /></Row>
          <Row label="Hashtags under every caption" hint="up to ten, separated by spaces"><input className={field} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="#scotland #calm" /></Row>
        </div>
        <div className="mt-3 space-y-3">
          <Row label="Page name"><input className={field} value={cfg.page_name} maxLength={40} onChange={(e) => up('page_name', e.target.value)} /></Row>
          <Row label="What the page is about" hint="The AI reads this when it watches scenes and writes lines."><textarea rows={3} className={`${field} resize-y`} value={cfg.page_brief} maxLength={400} onChange={(e) => up('page_brief', e.target.value)} /></Row>
        </div>
        <div className="mt-3"><Button tone="memory" icon={<Save className="size-3.5" />} disabled={!dirtyCfg || a.busy !== null}
          onClick={() => void a.act('save', async () => { await studio.settings({ ...cfg, caption_hashtags: tags.split(/[\s,]+/).filter(Boolean) }); setCfgDraft(null); setTagsDraft(null) }, 'confirm')}>Save</Button></div>
        <ErrorNote error={a.error} onClose={a.clear} />
      </Panel>

      <Panel title="How the words look" aside={dirtySty && <span className="text-2xs text-[#fcd34d]">unsaved</span>}>
        <div className="grid gap-4 sm:grid-cols-[1fr_auto]">
          <div className="grid gap-3 sm:grid-cols-2">
            <Row label="Size" hint="% of the video's height"><Num value={sty.size_pct} min={2} max={9} step={0.1} onChange={(n) => us('size_pct', n)} /></Row>
            <Row label="Colour"><input className={field} value={sty.color} onChange={(e) => us('color', e.target.value)} placeholder="white, black, #ffffff or auto" /></Row>
            <Row label="Where" hint="auto = where the AI saw calm space">
              <select className={field} value={sty.position} onChange={(e) => us('position', e.target.value as Style['position'])}>
                <option value="auto">auto</option><option value="top">top</option><option value="center">middle</option><option value="bottom">bottom</option>
              </select>
            </Row>
            <Row label="Alignment"><select className={field} value={sty.align} onChange={(e) => us('align', e.target.value as Style['align'])}><option value="center">centred</option><option value="left">left</option></select></Row>
            <Row label="Widest line (%)"><Num value={sty.max_width_pct} min={40} max={94} onChange={(n) => us('max_width_pct', n)} /></Row>
            <Row label="Line spacing (%)"><Num value={sty.line_spacing_pct} min={0} max={60} onChange={(n) => us('line_spacing_pct', n)} /></Row>
            <Row label="Fade in (seconds)"><Num value={sty.fade_in_s} min={0} max={3} step={0.1} onChange={(n) => us('fade_in_s', n)} /></Row>
            <Row label="Appears after (seconds)"><Num value={sty.start_s} min={0} max={5} step={0.1} onChange={(n) => us('start_s', n)} /></Row>
            <Row label="Outline (pixels)"><Num value={sty.outline_px} min={0} max={8} onChange={(n) => us('outline_px', n)} /></Row>
            <label className="flex items-center gap-2 self-end pb-1.5 text-[12px] text-ink-dim"><input type="checkbox" checked={sty.shadow} onChange={(e) => us('shadow', e.target.checked)} />Soft shadow</label>
            <div className="sm:col-span-2">
              <Row label="Font" hint="Upload a .ttf or .otf file to match the page's look; until then a plain sans-serif is used.">
                <select className={field} value={sty.font} onChange={(e) => us('font', e.target.value)}>
                  <option value="">plain sans-serif (default)</option>
                  {fonts.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </Row>
              <div className="mt-2"><UploadZone kind="fonts" accept=".ttf,.otf" label="Add a font" hint=".ttf or .otf, up to 8 MB" multiple={false} /></div>
            </div>
          </div>
          <Sketch st={sty} text="could you let go of this feeling holding you back" />
        </div>
        <div className="mt-3"><Button tone="memory" icon={<Save className="size-3.5" />} disabled={!dirtySty || b.busy !== null}
          onClick={() => void b.act('save', async () => { await studio.style({ ...sty }); setStyDraft(null) }, 'confirm')}>Save</Button></div>
        <ErrorNote error={b.error} onClose={b.clear} />
        <p className="mt-2 text-2xs text-ink-faint">Saving changes the next videos; posts already made keep their look until you press Remake.</p>
      </Panel>

      <Panel title="The page's voice" className="xl:col-span-2" aside={<span className="hidden text-2xs text-ink-faint sm:inline">the Overlay Copywriter reads this before writing a line</span>}>
        {voice === null ? <p className="text-[12px] text-ink-faint">Reading…</p> : (
          <>
            <textarea rows={6} className={`${field} resize-y`} value={voice} onChange={(e) => setVoice(e.target.value)} aria-label="The page's voice" />
            <div className="mt-2"><Button tone="memory" icon={<Save className="size-3.5" />} disabled={c.busy !== null} onClick={() => void c.act('save', () => studio.saveVoice(voice), 'confirm')}>Save</Button></div>
            <ErrorNote error={c.error} onClose={c.clear} />
          </>
        )}
      </Panel>
    </div>
  )
}
