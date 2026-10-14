import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type Signal = 'ok' | 'warn' | 'alarm' | 'memory' | 'agent' | 'idle'

const DOT: Record<Signal, string> = {
  ok: 'bg-ok', warn: 'bg-runway', alarm: 'bg-alarm', memory: 'bg-memory', agent: 'bg-agent', idle: 'bg-ink-faint',
}
const TEXT: Record<Signal, string> = {
  ok: 'text-[#6ee7b7]', warn: 'text-[#fcd34d]', alarm: 'text-[#fca5a5]', memory: 'text-memory', agent: 'text-[#f0abfc]', idle: 'text-ink-dim',
}

/** A status dot; `breathe` for a healthy daemon that is running right now. */
export function Dot({ signal, breathe }: { signal: Signal; breathe?: boolean }) {
  return <span aria-hidden className={cn('inline-block size-1.5 shrink-0 rounded-full', DOT[signal], breathe && 'animate-breathe')} />
}

export function Chip({ signal = 'idle', children, breathe, className }: { signal?: Signal; children: ReactNode; breathe?: boolean; className?: string }) {
  return (
    <span className={cn('inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full whitespace-nowrap border border-line bg-white/[0.03] px-2 text-2xs font-medium', TEXT[signal], className)}>
      <Dot signal={signal} breathe={breathe} />
      {children}
    </span>
  )
}
