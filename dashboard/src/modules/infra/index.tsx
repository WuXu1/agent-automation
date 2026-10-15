import { HardDrive, UploadCloud } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/cn'
import { useRegistry } from '@/telemetry/registry'
import { ago, bytes, dateShort, duration, stamp } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useFeature } from '@/telemetry/team'
import { useInfrastructure } from '@/telemetry/hooks/feeds'
import { useMode } from '@/telemetry/mode'
import type { Infra, Service } from '@/telemetry/types'
import { Chip, Dot, type Signal } from '@/ui/Chip'
import { FeedError, FeedStatus } from '@/ui/FeedStatus'
import { Meter, type Tone } from '@/ui/Meter'
import { Panel } from '@/ui/Panel'
import { Topology } from './Topology'
import { ConfirmButton } from '@/ui/ConfirmButton'
import { backups, type BackupState } from '@/telemetry/tools'
import { play } from '@/lib/sound'

const DAY = 86_400_000

function runway(credit: Infra['credit'], now: number) {
  const typed = new Date(`${credit.asOf}T12:00:00Z`).getTime()
  const asOf = Number.isFinite(typed) ? typed : now          // no snapshot typed in yet: count from today
  const estimate = Math.max(0, credit.balance - credit.burnPerDay * Math.max(0, (now - asOf) / DAY))
  const daysLeft = estimate / credit.burnPerDay
  return { asOf, typed: Number.isFinite(typed), estimate, daysLeft, endsAt: now + daysLeft * DAY }
}

/** The runway itself: from the snapshot to a little past the day the credit runs out, with today marked. */
function Runway({ credit }: { credit: Infra['credit'] }) {
  const now = useNow(60_000).getTime()
  const { estimate, daysLeft, endsAt, asOf, typed } = runway(credit, now)
  const from = Math.min(asOf, now) - 7 * DAY
  const to = Math.max(endsAt, now) + 14 * DAY
  const x = (t: number) => `${Math.max(0, Math.min(100, ((t - from) / (to - from)) * 100))}%`
  const months: number[] = []
  for (let d = new Date(from), m = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1); m < to; d = new Date(m), m = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)) months.push(m)
  const tight = daysLeft < 21

  return (
    <Panel title="Azure credit runway" aside={<span className="text-2xs text-ink-faint">{typed ? `snapshot ${dateShort(asOf)}` : 'no snapshot yet'} · ${credit.burnPerDay.toFixed(2)} a day</span>} className="lg:col-span-8">
      <div className="flex flex-wrap items-end gap-x-10 gap-y-3">
        <div>
          <div className="num text-[34px] leading-none font-medium tracking-[-0.03em] text-[#fcd34d]">${estimate.toFixed(2)}</div>
          <div className="mt-1.5 text-[12px] text-ink-dim">{typed ? `left today, estimated from $${credit.balance.toFixed(2)} on ${dateShort(asOf)}` : `a guess: type the real figure on the Integrations page`}</div>
        </div>
        <div>
          <div className={cn('num text-[22px] leading-none font-medium', tight ? 'text-[#fca5a5]' : 'text-ink')}>{Math.floor(daysLeft)} days</div>
          <div className="mt-1.5 text-[12px] text-ink-dim">until about <span className="text-ink">{dateShort(endsAt)}</span></div>
        </div>
        <div className="min-w-[180px] flex-1">
          <Meter value={credit.start - estimate} max={credit.start} tone="runway" label="Credit spent" />
          <div className="mt-1.5 flex justify-between text-[11px] text-ink-faint">
            <span className="num">${(credit.start - estimate).toFixed(0)} spent</span>
            <span className="num">of ${credit.start}</span>
          </div>
        </div>
      </div>

      <div className="relative mt-7 mb-2" aria-label="Timeline until the credit runs out">
        <div className="relative h-9">
          <div className="absolute inset-x-0 top-1/2 h-px bg-line-strong" aria-hidden />
          <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-runway/80" style={{ left: x(from), width: `calc(${x(now)} - ${x(from)})` }} aria-hidden />
          <div className="absolute top-[-6px] bottom-[-6px] w-0.5 rounded bg-ink" style={{ left: x(now) }} title="Today" aria-hidden />
          <div className={cn('absolute top-[-6px] bottom-[-6px] w-0.5 rounded', tight ? 'bg-alarm' : 'bg-runway')} style={{ left: x(endsAt) }} aria-hidden />
        </div>
        <div className="relative mt-2 h-8 text-[11px]">
          {months.map((m) => (
            <span key={m} className="absolute text-ink-faint" style={{ left: x(m) }}>{new Date(m).toLocaleDateString('en-GB', { month: 'short' })}</span>
          ))}
          <span className="absolute top-4 -translate-x-1/2 font-medium text-ink" style={{ left: x(now) }}>Today</span>
          <span className={cn('absolute top-4 -translate-x-1/2 font-medium whitespace-nowrap', tight ? 'text-[#fca5a5]' : 'text-[#fcd34d]')} style={{ left: x(endsAt) }}>
            Credit ends ~{dateShort(endsAt)}
          </span>
        </div>
      </div>
      <p className="text-2xs text-ink-faint">A student subscription has no API for the balance, so this counts down from the last snapshot. Check the real figure in the Azure portal now and then and type it on the Integrations page (the Azure card).</p>
    </Panel>
  )
}

function tone(pct: number, warn: number, alarm: number): Tone {
  return pct >= alarm ? 'alarm' : pct >= warn ? 'runway' : 'ok'
}

function Vm({ vm, cleanable }: { vm: Infra['vm']; cleanable: Infra['cleanable'] }) {
  const memPct = (vm.memUsed / vm.memTotal) * 100
  const diskPct = (vm.diskUsed / vm.diskTotal) * 100
  const clean = cleanable.reduce((s, c) => s + (c.bytes ?? 0), 0)
  const row = (label: string, value: string, el: React.ReactNode) => (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between text-[12px]">
        <span className="text-ink-dim">{label}</span>
        <span className="num text-ink">{value}</span>
      </div>
      {el}
    </div>
  )
  return (
    <Panel title="The VM" aside={<span className="num text-2xs text-ink-faint">up {duration(vm.uptimeSecs)} · load {vm.load[0].toFixed(2)}</span>} className="lg:col-span-4">
      <div className="space-y-4">
        {row('CPU', `${Math.round(vm.cpuPct)} %`, <Meter value={vm.cpuPct} max={100} tone={tone(vm.cpuPct, 70, 90)} label="CPU" />)}
        {row('Memory', `${bytes(vm.memUsed)} of ${bytes(vm.memTotal)}`, <Meter value={memPct} max={100} tone={tone(memPct, 80, 92)} label="Memory" />)}
        {row('Disk', `${bytes(vm.diskUsed)} of ${bytes(vm.diskTotal)} · ${Math.round(diskPct)} %`,
          <Meter value={diskPct} max={100} tone={tone(diskPct, 75, 90)} label="Disk" marks={[{ at: 90, label: '90 % alarm', tone: 'alarm' }]} />)}
      </div>
      {clean > 0 && (
        <div className="mt-2 rounded-lg border border-runway/30 bg-runway/[0.06] px-3 py-2.5">
          <div className="flex items-center gap-2 text-[12px] font-medium text-[#fcd34d]"><HardDrive className="size-3.5" /> About {bytes(clean)} could be freed</div>
          <ul className="mt-1.5 space-y-0.5">
            {cleanable.map((c) => (
              <li key={c.path} className="flex justify-between gap-3 text-2xs">
                <span className="num truncate text-ink-dim">{c.path}</span>
                <span className="num text-ink-faint">{c.bytes === null ? 'unreadable' : bytes(c.bytes)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-2xs text-ink-faint">Old runtimes and backups. Nothing is deleted without your yes.</p>
        </div>
      )}
    </Panel>
  )
}

const STATE_SIGNAL: Record<Service['state'], Signal> = { active: 'ok', activating: 'warn', inactive: 'idle', failed: 'alarm', unknown: 'idle' }

function Services({ services, className }: { services: Service[]; className: string }) {
  const reg = useRegistry((r) => r.reg)
  const down = services.filter((s) => s.state !== 'active').length
  return (
    <Panel title="Services" aside={down ? <Chip signal="alarm">{down} not running</Chip> : <Chip signal="ok">all running</Chip>} className={className}>
      <ul className="-mx-1 divide-y divide-line">
        {services.map((s) => (
          <li key={s.unit} className="flex items-center gap-3 px-1 py-2">
            <Dot signal={STATE_SIGNAL[s.state]} breathe={s.state === 'active'} />
            <div className="min-w-0 flex-1">
              <div className="num truncate text-[12px] text-ink">{s.unit}</div>
              <div className="truncate text-2xs text-ink-faint">{s.label || reg.services[s.unit]?.label || ''}{s.described === false && <span className="ml-1.5 rounded-full border border-runway/40 px-1.5 text-[10px] text-[#fcd34d]" title="Installed on the VM but not in the dashboard's registry yet">new</span>}</div>
            </div>
            <div className="text-right">
              <div className={cn('text-[11px]', s.state === 'active' ? 'text-ink-dim' : 'text-[#fca5a5]')}>{s.state === 'active' ? (s.since ? `up ${ago(s.since).replace(' ago', '')}` : 'running') : s.state}</div>
              {s.memBytes !== null && <div className="num text-[10px] text-ink-faint">{bytes(s.memBytes)}</div>}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

/** Starts the same unit the nightly timer starts (hermes-backup.service), through a root-owned helper; then watches it. */
function BackupNow() {
  const mode = useMode((s) => s.mode)
  const [state, setState] = useState<BackupState | null>(null)
  const busy = Boolean(state?.active || state?.requested)
  useEffect(() => {
    let stop = false
    const read = () => backups.state().then((s) => { if (!stop) setState(s) }).catch(() => {})
    void read()
    const id = window.setInterval(read, busy ? 4000 : 30_000)
    return () => { stop = true; window.clearInterval(id) }
  }, [busy, mode])
  const last = state?.last
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2.5">
      {busy ? (
        <span className="inline-flex items-center gap-2 text-[12px] text-[#fcd34d]"><Dot signal="warn" breathe />{state?.active ? 'Backing up now… (a few minutes)' : 'Starting…'}</span>
      ) : (
        <ConfirmButton label="Backup now" confirmLabel="Start a backup to Drive" tone="memory" size="sm" icon={<UploadCloud className="size-3.5" />}
          onConfirm={async () => { await backups.start(); play('confirm'); setState(await backups.state()) }} />
      )}
      {last && !busy && <span className="text-2xs text-ink-faint">{last.state === 'started' ? `Last started from here ${ago(last.at * 1000)}` : last.message}{state?.result && state.result !== 'success' ? ` · last result: ${state.result}` : ''}</span>}
    </div>
  )
}

function Backup({ backup }: { backup: Infra['backup'] }) {
  useNow(60_000)
  return (
    <Panel
      title="Nightly backup"
      aside={backup.ok === null ? <Chip>no run yet</Chip> : backup.ok ? <Chip signal="ok">last run ok</Chip> : <Chip signal="alarm">last run failed</Chip>}
      className="lg:col-span-6"
    >
      <dl className="divide-y divide-line text-[12px]">
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Last run</dt><dd className="num text-ink">{backup.lastRunAt ? `${stamp(backup.lastRunAt)} · ${ago(backup.lastRunAt)}` : 'never'}</dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Next run</dt><dd className="num text-ink">{backup.nextRunAt ? stamp(backup.nextRunAt) : 'not scheduled'}</dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">Goes to</dt><dd className="text-ink">Google Drive</dd></div>
        <div className="flex justify-between py-2"><dt className="text-ink-dim">What</dt><dd className="text-ink">an encrypted archive of /data/.hermes</dd></div>
      </dl>
      <BackupNow />
      <details className="mt-2 rounded-lg border border-runway/30 bg-runway/[0.06] px-3 py-2">
        <summary className="cursor-pointer text-2xs text-[#fcd34d]">Try a restore once, so you know the backup works (about 15 minutes, on your computer)</summary>
        <ol className="mt-2 list-decimal space-y-1.5 pl-4 text-[12px] text-ink-dim">
          <li>Open drive.google.com, the backup folder, and download the newest <span className="num">.tar.gz.gpg</span>.</li>
          <li>In a terminal (you need GnuPG; on a Mac: <span className="num">brew install gnupg</span>):<br /><span className="num text-ink">mkdir restore &amp;&amp; gpg -d backup.tar.gz.gpg | tar -xzf - -C restore</span><br />It asks for your backup passphrase.</li>
          <li>Check it: the VM’s folders are inside without the leading <span className="num">/</span> (<span className="num">restore/data/.hermes/…</span>). Open a SOUL.md, and you know the archive is good.</li>
          <li>Nothing on the VM changes for a rehearsal; a real restore uses the same archive (see the kit’s backup add-on).</li>
        </ol>
      </details>
    </Panel>
  )
}

/** The Runway: the Azure credit, the VM, its services and (with the backup add-on) the nightly backup. */
export default function InfraView() {
  const feed = useInfrastructure()
  const backup = useFeature('backup')
  const setMode = useMode((s) => s.setMode)
  const infra = feed.data
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] p-3 md:p-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-[13px] text-ink-dim">Money and machine: how long the Azure credit lasts, and whether the VM is well.</p>
          <FeedStatus feed={feed} source="the VM" />
        </div>
        {!infra ? (
          feed.status === 'error' ? <FeedError error={feed.error} onDemo={() => setMode('demo')} /> : <div className="glass h-64 animate-pulse" />
        ) : (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-12">
            <Runway credit={infra.credit} />
            <Vm vm={infra.vm} cleanable={infra.cleanable} />
            <Services services={infra.services} className={backup ? 'lg:col-span-6' : 'lg:col-span-12'} />
            {backup && <Backup backup={infra.backup} />}
            <Topology infra={infra} />
          </div>
        )}
      </div>
    </div>
  )
}
