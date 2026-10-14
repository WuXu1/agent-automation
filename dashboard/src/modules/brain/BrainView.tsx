import { useBrain } from '@/telemetry/hooks/useMem0Graph'
import { Activity } from './Activity'
import { Inspector } from './Inspector'
import { Legend } from './Legend'
import { Review, useReviewSync } from './Review'
import { SearchPanel } from './SearchPanel'
import { LoadError, Status } from './Status'
import { useBrainUi } from './store'
import { useReview } from '@/telemetry/review'

/** The HUD over the constellation. The container lets clicks through to the sky; each panel takes its own. */
export function BrainView() {
  const status = useBrain((s) => s.status)
  const noteOpen = useBrainUi((s) => Boolean(s.selectedId) || s.composing)
  const reviewOpen = useReview((s) => s.open)
  const drawerOpen = noteOpen || reviewOpen
  useReviewSync()

  return (
    <div className="absolute inset-0">
      <div className="absolute inset-x-2 top-2 flex flex-col gap-2 md:inset-x-auto md:top-4 md:left-4 md:bottom-[300px] md:w-[360px]">
        <SearchPanel className="pointer-events-auto" />
      </div>

      {!drawerOpen && <Status className="pointer-events-auto absolute top-4 right-4 hidden md:flex" />}

      <Legend className="pointer-events-auto absolute right-2 bottom-2 left-2 md:right-auto md:bottom-4 md:left-4 md:w-[230px]" />

      {!drawerOpen && <Activity className="pointer-events-auto absolute right-4 bottom-4 hidden max-h-[230px] w-[340px] lg:flex" />}

      {status === 'error' && <LoadError />}
      <Inspector />
      <Review />
    </div>
  )
}
