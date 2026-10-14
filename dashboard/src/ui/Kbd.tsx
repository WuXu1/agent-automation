import type { ReactNode } from 'react'

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="num inline-grid h-5 min-w-5 place-items-center rounded border border-line-strong bg-white/[0.04] px-1 text-[10px] text-ink-dim">
      {children}
    </kbd>
  )
}
