import type { Infra } from '../types'

const GB = 1024 ** 3

// A small Azure VM (B2als_v2: 4 GB, a 30 GB disk) on a $100 student credit burning about $1.20 a day.
export function demoInfra(now = Date.now()): Infra {
  const day = 86_400_000
  const lastBackup = new Date(now)
  lastBackup.setHours(4, 23, 0, 0)
  if (lastBackup.getTime() > now) lastBackup.setTime(lastBackup.getTime() - day)
  const services = ['hermes-gateway', 'mem0-server', 'postgresql', 'hermes-dash', 'tailscaled']
  return {
    at: now,
    vm: { cpuPct: 7, memUsed: 2.4 * GB, memTotal: 3.81 * GB, diskUsed: 17.4 * GB, diskTotal: 30 * GB, load: [0.18, 0.16, 0.12], uptimeSecs: 5 * 86_400 + 3_700 },
    services: services.map((unit, i) => ({
      unit,
      state: 'active',
      since: now - (i < 3 ? 2.5 : 5) * 3_600_000 * (i + 1),
      memBytes: [410, 520, 90, 15, 40][i]! * 1024 ** 2,
    })),
    backup: { lastRunAt: lastBackup.getTime(), ok: true, nextRunAt: lastBackup.getTime() + day },
    credit: { balance: 87.4, asOf: '2026-10-01', burnPerDay: 1.2, start: 100 },
    cleanable: [
      { path: '/data/.hermes/installs', bytes: 2.1 * GB },
      { path: '/data/.hermes/tools', bytes: 1.2 * GB },
      { path: '/data/backups', bytes: 0.7 * GB },
    ],
  }
}

/** Demo: CPU and memory wander a little; nothing else moves. */
export function tickInfra(prev: Infra): Infra {
  const cpu = Math.max(2, Math.min(60, prev.vm.cpuPct + (Math.random() - 0.5) * 8 + (Math.random() < 0.06 ? 25 : 0)))
  const mem = Math.max(2.1 * GB, Math.min(3.2 * GB, prev.vm.memUsed + (Math.random() - 0.5) * 0.05 * GB))
  return { ...prev, at: Date.now(), vm: { ...prev.vm, cpuPct: Math.round(cpu), memUsed: mem, uptimeSecs: prev.vm.uptimeSecs + 3 } }
}
