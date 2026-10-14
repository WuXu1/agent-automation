import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

/** A glass panel with an optional heading row. Panels never nest. */
export function Panel({ title, aside, children, className, bodyClassName }: {
  title?: ReactNode
  aside?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={cn('glass flex min-h-0 flex-col', className)}>
      {title !== undefined && (
        <header className="flex items-center justify-between gap-3 px-4 pt-3.5 pb-2">
          <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-ink">{title}</h2>
          {aside}
        </header>
      )}
      <div className={cn('min-h-0 flex-1', title !== undefined ? 'px-4 pb-4' : 'p-4', bodyClassName)}>{children}</div>
    </section>
  )
}
