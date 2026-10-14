import { Laptop, Minus, Plus, RotateCcw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { api } from '@/telemetry/live/client'
import { useMode } from '@/telemetry/mode'
import { useRegistry } from '@/telemetry/registry'
import { integrationsApi, type IntegrationStatus, type Hub } from '@/telemetry/tools'
import type { Infra } from '@/telemetry/types'
import { Panel } from '@/ui/Panel'

// Through which of the VM's services each outside service is reached, and a short word for it. Anything else the
// Integrations hub lists (a new integration Claude adds) goes through the gateway and is named by its kind.
const VIA: Record<string, { via: string; what: string }> = {
  deepseek: { via: 'hermes-gateway', what: 'the agents’ model' },
  telegram: { via: 'hermes-gateway', what: 'the agents’ chats' },
  gmail: { via: 'hermes-gateway', what: 'read and draft' },
  icloud: { via: 'hermes-gateway', what: 'calendar' },
  gemini: { via: 'hermes-gateway', what: 'the fallback model' },
  moodle: { via: 'hermes-gateway', what: 'course pages' },
  weather: { via: 'hermes-gateway', what: 'forecasts' },
  openalex: { via: 'hermes-gateway', what: 'paper search' },
  elevenlabs: { via: 'hermes-gateway', what: 'voice replies' },
  drive: { via: 'backup', what: 'nightly backup' },
}
const LOCAL = new Set(['mem0'])
const TONE: Record<IntegrationStatus | 'down', string> = { connected: '#22d3ee', expiring: '#f59e0b', attention: '#ef4444', unknown: '#64748b', off: '#475569', down: '#ef4444' }

const W = 1000
const ROW = 34

/** Runway's blueprint: your computer, the tunnel, the VM and its services, and the outside services they use. Live where it can be. */
export function Topology({ infra }: { infra: Infra }) {
  const mode = useMode((s) => s.mode)
  const reduced = useReducedMotion()
  const [rtt, setRtt] = useState<number | null>(null)
  const [hub, setHub] = useState<Hub | null>(null)
  const [zoom, setZoom] = useState(1)

  // the tunnel's real round trip: the page asks the bridge for /health over Tailscale and times it
  useEffect(() => {
    let stop = false
    const ping = async () => {
      if (mode !== 'live') { setRtt(28 + Math.round(Math.random() * 20)); return }
      const t = performance.now()
      try { await api('/health', { timeoutMs: 5000 }); if (!stop) setRtt(Math.round(performance.now() - t)) } catch { if (!stop) setRtt(null) }
    }
    void ping()
    const id = window.setInterval(() => void ping(), 15_000)
    return () => { stop = true; window.clearInterval(id) }
  }, [mode])
  useEffect(() => {
    let stop = false
    integrationsApi.get(false).then((h) => { if (!stop) setHub(h) }).catch(() => {})
    return () => { stop = true }
  }, [mode])

  const reg = useRegistry((s) => s.reg)
  const port = (unit: string, p?: number | null) => (p ?? reg.services[unit]?.port) ?? null
  // services with a port, the tunnel, and any service on the VM nobody has described yet
  const services = infra.services.filter((s) => port(s.unit, s.port) !== null || s.unit === 'tailscaled' || s.described === false)
  const order = Object.keys(VIA)
  const external = (hub?.cards ?? [])
    .filter((c) => c.inUse && !LOCAL.has(c.id) && (c.usedBy.length > 0 || c.id in VIA))
    .sort((a, b) => (order.includes(a.id) ? order.indexOf(a.id) : 99) - (order.includes(b.id) ? order.indexOf(b.id) : 99))
    .map((c) => ({ id: c.id, label: c.name.replace(/ \(.*\)$/, ''), via: VIA[c.id]?.via ?? 'hermes-gateway', what: VIA[c.id]?.what ?? c.kind, status: c.status }))
  const vmTop = 60
  const vmH = 56 + services.length * ROW
  const H = Math.max(vmTop + vmH + 40, 60 + external.length * 46)
  const vm = { x: 370, y: vmTop, w: 310, h: vmH }
  const rowY = (unit: string) => {
    const i = services.findIndex((s) => s.unit === unit)
    return i < 0 ? vm.y + vm.h - 18 : vm.y + 56 + i * ROW + ROW / 2 - 6
  }
  const mac = { x: 20, y: vm.y + vm.h / 2 - 44, w: 180, h: 88 }
  const tunnelOk = rtt !== null
  const vbW = W / zoom
  const vbH = H / zoom

  return (
    <Panel title="Blueprint" className="lg:col-span-12"
      aside={(
        <span className="flex items-center gap-1">
          <span className="mr-2 hidden text-2xs text-ink-faint sm:inline">moving dots = a healthy link · grey = not checked yet</span>
          {[[<Minus key="m" className="size-3.5" />, 'Zoom out', () => setZoom((z) => Math.max(0.6, z - 0.2))],
            [<Plus key="p" className="size-3.5" />, 'Zoom in', () => setZoom((z) => Math.min(2, z + 0.2))],
            [<RotateCcw key="r" className="size-3.5" />, 'Fit', () => setZoom(1)]].map(([icon, label, fn]) => (
            <button key={label as string} type="button" aria-label={label as string} title={label as string} onClick={fn as () => void}
              className="press grid size-7 place-items-center rounded-md text-ink-faint hover:bg-white/[0.05] hover:text-ink">{icon as React.ReactNode}</button>
          ))}
        </span>
      )}>
      <div className="overflow-auto">
        <svg viewBox={`${(W - vbW) / 2} 0 ${vbW} ${vbH}`} className="h-auto w-full min-w-[720px]" aria-labelledby="topology-title">
          <title id="topology-title">{`Your computer reaches the VM over Tailscale; the VM's services reach ${external.map((e) => e.label).join(', ')}`}</title>
          <defs>
            <style>{`.flow{stroke-dasharray:3 9;animation:${reduced ? 'none' : 'flow 1.4s linear infinite'}}@keyframes flow{to{stroke-dashoffset:-24}}`}</style>
          </defs>
          {/* your computer to the VM: the tunnel */}
          <path d={`M ${mac.x + mac.w} ${mac.y + mac.h / 2} H ${vm.x}`} stroke={tunnelOk ? '#22d3ee' : '#ef4444'} strokeOpacity={0.35} strokeWidth={2} fill="none" />
          {tunnelOk && <path className="flow" d={`M ${mac.x + mac.w} ${mac.y + mac.h / 2} H ${vm.x}`} stroke="#67e8f9" strokeWidth={2.5} fill="none" strokeLinecap="round" />}
          <text x={(mac.x + mac.w + vm.x) / 2} y={mac.y + mac.h / 2 - 12} textAnchor="middle" className="fill-ink-dim text-[11px]">Tailscale (WireGuard)</text>
          <text x={(mac.x + mac.w + vm.x) / 2} y={mac.y + mac.h / 2 + 20} textAnchor="middle" className={cn('num text-[11px]', tunnelOk ? 'fill-[#67e8f9]' : 'fill-[#fca5a5]')}>{tunnelOk ? `${rtt} ms round trip` : 'no answer'}</text>
          {/* VM to the outside */}
          {external.map((e, i) => {
            const y0 = e.via === 'backup' ? vm.y + vm.h - 18 : rowY(e.via)
            const y1 = 40 + i * 46 + 18
            const st = e.status
            const d = `M ${vm.x + vm.w} ${y0} C ${vm.x + vm.w + 70} ${y0}, ${780 - 70} ${y1}, 780 ${y1}`
            return (
              <g key={e.id}>
                <path d={d} stroke={TONE[st]} strokeOpacity={0.3} strokeWidth={1.5} fill="none" />
                {(st === 'connected' || st === 'expiring') && <path className="flow" d={d} stroke={TONE[st]} strokeWidth={2} fill="none" strokeLinecap="round" />}
                <rect x={780} y={40 + i * 46} width={190} height={36} rx={9} className="fill-[#0b1020]" stroke={TONE[st]} strokeOpacity={st === 'unknown' ? 0.4 : 0.7} />
                <circle cx={795} cy={y1} r={4} fill={TONE[st]} />
                <text x={808} y={y1 - 2} className="fill-ink text-[12px] font-medium">{e.label}</text>
                <text x={808} y={y1 + 11} className="fill-ink-faint text-[10px]">{e.what}</text>
              </g>
            )
          })}
          {/* your computer */}
          <rect x={mac.x} y={mac.y} width={mac.w} height={mac.h} rx={14} className="fill-[#0b1020]" stroke="#22d3ee" strokeOpacity={0.5} />
          <foreignObject x={mac.x + 14} y={mac.y + 14} width={30} height={30}><Laptop className="size-6 text-memory" /></foreignObject>
          <text x={mac.x + 52} y={mac.y + 32} className="fill-ink text-[13px] font-semibold">Your computer</text>
          <text x={mac.x + 14} y={mac.y + 62} className="fill-ink-faint text-[11px]">this dashboard, in the browser</text>
          {/* the VM */}
          <rect x={vm.x} y={vm.y} width={vm.w} height={vm.h} rx={14} className="fill-[#0b1020]" stroke="#a855f7" strokeOpacity={0.55} />
          <text x={vm.x + 16} y={vm.y + 26} className="fill-ink text-[13px] font-semibold">The VM</text>
          <text x={vm.x + 16} y={vm.y + 42} className="fill-ink-faint text-[10px]">Azure · {Math.round(infra.vm.memUsed / infra.vm.memTotal * 100)}% memory</text>
          {services.map((s, i) => {
            const ok = s.state === 'active'
            const y = vm.y + 56 + i * ROW
            return (
              <g key={s.unit}>
                <rect x={vm.x + 12} y={y} width={vm.w - 24} height={ROW - 8} rx={7} fill="white" fillOpacity={0.025} />
                <circle cx={vm.x + 26} cy={y + (ROW - 8) / 2} r={3.5} fill={ok ? '#10b981' : '#ef4444'} />
                <text x={vm.x + 38} y={y + (ROW - 8) / 2 + 4} className="num fill-ink text-[11px]">{s.unit}</text>
                <text x={vm.x + vm.w - 22} y={y + (ROW - 8) / 2 + 4} textAnchor="end" className="num fill-ink-faint text-[11px]">{s.unit === 'tailscaled' ? 'tailnet' : port(s.unit, s.port) ? `:${port(s.unit, s.port)}` : s.described === false ? 'new' : ''}{ok ? '' : ` · ${s.state}`}</text>
              </g>
            )
          })}
          <text x={vm.x + 16} y={vm.y + vm.h - 14} className="fill-ink-faint text-[10px]">nightly backup → Google Drive</text>
        </svg>
      </div>
    </Panel>
  )
}
