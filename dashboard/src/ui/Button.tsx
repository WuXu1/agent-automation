import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react'
import { cn } from '@/lib/cn'

type Tone = 'plain' | 'memory' | 'danger' | 'ghost'

const TONE: Record<Tone, string> = {
  plain: 'border-line-strong bg-white/[0.04] text-ink hover:bg-white/[0.08] hover:border-white/25',
  memory: 'border-memory/40 bg-memory/10 text-memory hover:bg-memory/18 hover:border-memory/60',
  danger: 'border-alarm/45 bg-alarm/10 text-[#fca5a5] hover:bg-alarm/18 hover:border-alarm/70',
  ghost: 'border-transparent bg-transparent text-ink-dim hover:text-ink hover:bg-white/[0.05]',
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  ref?: Ref<HTMLButtonElement>
  tone?: Tone
  icon?: ReactNode
  size?: 'sm' | 'md'
}

export function Button({ tone = 'plain', icon, size = 'md', className, children, type = 'button', ...rest }: Props) {
  return (
    <button
      type={type}
      className={cn(
        'press inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium whitespace-nowrap',
        'disabled:opacity-45 disabled:hover:bg-transparent',
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-9 px-3.5 text-[13px]',
        TONE[tone],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  )
}

interface IconProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string
  active?: boolean
}

export function IconButton({ label, active, className, children, type = 'button', ...rest }: IconProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={cn(
        'press grid size-9 place-items-center rounded-lg border border-transparent text-ink-dim',
        'hover:bg-white/[0.06] hover:text-ink',
        active && 'bg-white/[0.06] text-ink',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}
