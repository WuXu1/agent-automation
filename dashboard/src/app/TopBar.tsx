import { Command, Volume2, VolumeX } from 'lucide-react'
import { IconButton } from '@/ui/Button'
import { Kbd } from '@/ui/Kbd'
import { clock, dayDate } from '@/lib/time'
import { useCrew } from '@/telemetry/crew'
import { useNow } from '@/lib/useNow'
import { ModeSwitch } from './ModeSwitch'
import { useApp } from './store'
import { useCurrentView, VIEW_BY_ID } from './views'

function Clock() {
  const now = useNow(1000)
  const tz = useCrew((s) => s.crew.timezone)
  return (
    <div className="hidden text-right leading-tight sm:block" aria-label={`Time in ${tz.replace(/_/g, ' ')}`}>
      <div className="num text-[13px] text-ink">{clock(now)}</div>
      <div className="text-2xs text-ink-faint">{dayDate(now)}</div>
    </div>
  )
}

export function TopBar() {
  const view = VIEW_BY_ID.get(useCurrentView(useApp((s) => s.view)))
  const sound = useApp((s) => s.sound)
  const toggleSound = useApp((s) => s.toggleSound)
  const setPalette = useApp((s) => s.setPalette)

  return (
    <header className="pointer-events-auto z-20 flex items-center gap-3 border-b border-line bg-deck/70 px-4 backdrop-blur-md md:px-5">
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[15px] font-semibold tracking-[-0.02em]">
          {view?.label}
          <span className="ml-2 hidden font-normal text-ink-faint lg:inline">{view?.hint}</span>
        </h1>
      </div>
      <ModeSwitch />
      <button
        type="button"
        onClick={() => setPalette(true)}
        className="press hidden h-9 items-center gap-2 rounded-lg border border-line bg-white/[0.03] pr-1.5 pl-3 text-xs text-ink-dim hover:border-line-strong hover:text-ink sm:flex"
      >
        Search or jump
        <span className="flex gap-0.5"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
      </button>
      <IconButton label="Search or jump" className="sm:hidden" onClick={() => setPalette(true)}>
        <Command className="size-4" />
      </IconButton>
      <IconButton label={sound ? 'Turn interface sounds off' : 'Turn interface sounds on'} active={sound} onClick={toggleSound}>
        {sound ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
      </IconButton>
      <Clock />
    </header>
  )
}
