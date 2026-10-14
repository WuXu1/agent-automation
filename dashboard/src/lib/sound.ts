// Optional interface sounds (DESIGN.md): synthesized on the fly, off unless you turn them on.
let ctx: AudioContext | null = null
let enabled = false

export function setSound(on: boolean): void {
  enabled = on
  if (on && !ctx) ctx = new AudioContext()
}

type Tone = 'tick' | 'open' | 'confirm' | 'warn'

const TONES: Record<Tone, { freq: number; to: number; dur: number; gain: number; type: OscillatorType }> = {
  tick: { freq: 1800, to: 1400, dur: 0.035, gain: 0.04, type: 'triangle' },
  open: { freq: 520, to: 880, dur: 0.12, gain: 0.05, type: 'sine' },
  confirm: { freq: 660, to: 990, dur: 0.16, gain: 0.06, type: 'sine' },
  warn: { freq: 330, to: 220, dur: 0.2, gain: 0.06, type: 'square' },
}

export function play(tone: Tone): void {
  if (!enabled || !ctx) return
  const t = TONES[tone]
  const now = ctx.currentTime
  const osc = ctx.createOscillator()
  const g = ctx.createGain()
  osc.type = t.type
  osc.frequency.setValueAtTime(t.freq, now)
  osc.frequency.exponentialRampToValueAtTime(t.to, now + t.dur)
  g.gain.setValueAtTime(t.gain, now)
  g.gain.exponentialRampToValueAtTime(0.0001, now + t.dur)
  osc.connect(g).connect(ctx.destination)
  osc.start(now)
  osc.stop(now + t.dur + 0.02)
}
