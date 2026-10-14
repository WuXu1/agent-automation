import { ChevronsLeft, ChevronsRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import { play } from '@/lib/sound'
import { useApp } from './store'
import { SECTIONS, SETTINGS_VIEW, useCurrentView, useVisibleViews, type View } from './views'

function Mark() {
  return (
    <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden>
      <g fill="none" stroke="var(--color-memory)" strokeWidth="1.4" strokeLinecap="round" opacity="0.55">
        <path d="M8 22 16 9l8 13" />
        <path d="M8 22h16" />
      </g>
      <circle cx="16" cy="9" r="2.6" fill="var(--color-agent)" />
      <circle cx="8" cy="22" r="2" fill="var(--color-memory)" />
      <circle cx="24" cy="22" r="2" fill="var(--color-memory)" />
    </svg>
  )
}

/** One tab on a laptop: a long button, icon and name (just the icon when the rail is collapsed). */
function Tab({ v, collapsed }: { v: View; collapsed: boolean }) {
  const active = useCurrentView(useApp((s) => s.view)) === v.id
  const go = useApp((s) => s.go)
  const Icon = v.icon
  return (
    <button
      type="button"
      onClick={() => { play('tick'); go(v.id) }}
      aria-current={active ? 'page' : undefined}
      aria-label={collapsed ? v.label : undefined}
      title={collapsed ? `${v.label}: ${v.hint}` : v.hint}
      className={cn(
        'press group relative flex h-9 w-full items-center gap-3 rounded-lg text-[13px] transition-colors duration-150',
        collapsed ? 'justify-center px-0' : 'px-2.5',
        active ? 'bg-white/[0.07] font-medium text-ink' : 'text-ink-dim hover:bg-white/[0.04] hover:text-ink',
      )}
    >
      {active && <span aria-hidden className="absolute top-2 bottom-2 left-0 w-[3px] rounded-full bg-memory" />}
      <Icon className={cn('size-[18px] shrink-0', active ? 'text-memory' : 'text-ink-faint group-hover:text-ink-dim')} strokeWidth={1.75} />
      {!collapsed && <span className="truncate">{v.label}</span>}
    </button>
  )
}

/** One tab in the phone's bottom bar: icon over a short name. */
function PhoneTab({ v }: { v: View }) {
  const active = useCurrentView(useApp((s) => s.view)) === v.id
  const go = useApp((s) => s.go)
  const Icon = v.icon
  return (
    <button type="button" onClick={() => { play('tick'); go(v.id) }} aria-current={active ? 'page' : undefined} title={v.label}
      className={cn('press flex min-w-16 flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium', active ? 'text-ink' : 'text-ink-faint')}>
      <span className={cn('grid size-8 place-items-center rounded-lg', active && 'bg-white/[0.07] text-memory')}>
        <Icon className="size-[18px]" strokeWidth={1.75} />
      </span>
      {v.short}
    </button>
  )
}

/**
 * Laptop: a left rail of long buttons grouped under section headings (more tabs fit, and stay findable), Settings pinned
 * at the bottom, and a button that shrinks it to icons. Phone: a bottom tab bar that scrolls sideways when it fills up.
 */
export function Rail() {
  const collapsed = useApp((s) => s.railCollapsed)
  const toggle = useApp((s) => s.toggleRail)
  const { views, all } = useVisibleViews()
  return (
    <>
      <nav aria-label="Views" className="pointer-events-auto z-20 hidden min-h-0 flex-col border-r border-line bg-deck/85 px-3 pt-3 pb-3 backdrop-blur-md md:row-span-2 md:flex">
        <div className={cn('flex h-10 items-center gap-2.5', collapsed ? 'justify-center' : 'px-1.5')} title="Hermes Command">
          <Mark />
          {!collapsed && <span className="truncate text-[14px] font-semibold tracking-[-0.02em]">Hermes Command</span>}
        </div>
        <div className="mt-4 min-h-0 flex-1 space-y-4 overflow-y-auto">
          {SECTIONS.map((sec) => {
            const tabs = views.filter((v) => v.section === sec.id)
            if (!tabs.length) return null
            return (
              <section key={sec.id} aria-label={sec.label}>
                {collapsed
                  ? <div aria-hidden className="mx-auto mb-1.5 h-px w-6 bg-line-strong" />
                  : <div className="mb-1 px-2.5 text-[10px] font-medium tracking-[0.08em] text-ink-faint uppercase">{sec.label}</div>}
                <div className="space-y-0.5">{tabs.map((v) => <Tab key={v.id} v={v} collapsed={collapsed} />)}</div>
              </section>
            )
          })}
        </div>
        <div className="mt-3 space-y-0.5 border-t border-line pt-3">
          <Tab v={SETTINGS_VIEW} collapsed={collapsed} />
          <button type="button" onClick={toggle} aria-label={collapsed ? 'Expand the sidebar' : 'Collapse the sidebar'} title={collapsed ? 'Expand' : 'Collapse to icons'}
            className={cn('press flex h-8 w-full items-center gap-3 rounded-lg text-[12px] text-ink-faint hover:bg-white/[0.04] hover:text-ink-dim', collapsed ? 'justify-center' : 'px-2.5')}>
            {collapsed ? <ChevronsRight className="size-4" /> : <><ChevronsLeft className="size-4" />Collapse</>}
          </button>
        </div>
      </nav>
      <nav aria-label="Views" className="pointer-events-auto z-20 order-last flex overflow-x-auto border-t border-line bg-deck/85 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden">
        {all.map((v) => <PhoneTab key={v.id} v={v} />)}
      </nav>
    </>
  )
}
