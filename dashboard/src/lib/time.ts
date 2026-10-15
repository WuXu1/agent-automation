import { teamNow } from '@/telemetry/team'

// Times are shown in the owner's time zone (hermes.json `timezone`), falling back to UK time if it is not a valid zone.
const ok = new Map<string, boolean>()
function zone(): string {
  const tz = teamNow().timezone
  if (!ok.has(tz)) {
    try { new Intl.DateTimeFormat('en-GB', { timeZone: tz }); ok.set(tz, true) } catch { ok.set(tz, false) }
  }
  return ok.get(tz) ? tz : 'Europe/London'
}

export function clock(d: Date): string {
  return d.toLocaleTimeString('en-GB', { timeZone: zone(), hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function dayDate(d: Date): string {
  return d.toLocaleDateString('en-GB', { timeZone: zone(), weekday: 'short', day: 'numeric', month: 'short' })
}

/** "just now", "4 min ago", "3 h ago", "2 days ago", "3 weeks ago", "4 months ago". */
export function ago(ms: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ms) / 1000))
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 36) return `${h} h ago`
  const days = Math.round(h / 24)
  if (days < 14) return `${days} days ago`
  const weeks = Math.round(days / 7)
  if (weeks < 9) return `${weeks} weeks ago`
  return `${Math.round(days / 30)} months ago`
}

export function stamp(ms: number): string {
  return new Date(ms).toLocaleString('en-GB', {
    timeZone: zone(), day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export function duration(secs: number): string {
  if (secs < 60) return `${Math.round(secs)} s`
  const m = Math.floor(secs / 60)
  const s = Math.round(secs % 60)
  if (m < 60) return s ? `${m} min ${s} s` : `${m} min`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h} h ${m % 60} min`
  return `${Math.floor(h / 24)} days ${h % 24} h`
}

export function bytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`
  if (n >= 1024 ** 2) return `${Math.round(n / 1024 ** 2)} MB`
  return `${Math.round(n / 1024)} KB`
}

export function dateShort(ms: number): string {
  return new Date(ms).toLocaleDateString('en-GB', { timeZone: zone(), day: 'numeric', month: 'short' })
}
