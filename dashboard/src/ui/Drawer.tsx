import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { drawer, fade } from '@/lib/motion'
import { useReducedMotion } from '@/lib/useReducedMotion'
import { IconButton } from './Button'

/** A side sheet for details (right on a laptop, bottom on a phone). Escape closes it. Not modal: the view stays usable. */
export function Drawer({ open, onClose, title, children, className, footer, wide, actions }: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  className?: string
  /** Pinned under the scrolling body: the drawer's actions. */
  footer?: ReactNode
  wide?: boolean
  /** Small buttons in the header, left of the close button. */
  actions?: ReactNode
}) {
  const reduced = useReducedMotion()
  const narrow = typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches
  const hidden = reduced ? { opacity: 0 } : { opacity: 1, transform: narrow ? 'translateY(100%)' : 'translateX(calc(100% + 24px))' }

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          key="drawer"
          initial={hidden}
          animate={{ opacity: 1, transform: 'translate(0px, 0px)' }}
          exit={hidden}
          transition={reduced ? fade : drawer}
          className={cn(
            'glass fixed z-30 flex flex-col overflow-hidden bg-glass-strong shadow-[0_24px_64px_-16px_rgb(0_0_0/0.75)]',
            'inset-x-2 bottom-[72px] max-h-[78%] md:inset-x-auto md:top-[72px] md:right-4 md:bottom-4 md:max-h-none',
            wide ? 'md:w-[560px]' : 'md:w-[400px]',
            className,
          )}
        >
          <header className="flex items-center gap-2 border-b border-line px-5 py-3">
            <div className="min-w-0 flex-1 text-[14px] font-semibold">{title}</div>
            {actions}
            <IconButton label="Close" onClick={onClose}><X className="size-4" /></IconButton>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="border-t border-line px-5 py-3.5">{footer}</footer>}
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
