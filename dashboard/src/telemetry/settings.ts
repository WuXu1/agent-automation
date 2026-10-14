import { create } from 'zustand'
import { settingsApi, type Settings } from './tools'

// The dashboard's own settings (bridge/settings.py): read once per mode, changed from the Settings view.
interface SettingsStore {
  settings: Settings | null
  load: () => Promise<void>
  save: (patch: Parameters<typeof settingsApi.save>[0]) => Promise<void>
}

export const useSettings = create<SettingsStore>((set) => ({
  settings: null,
  load: async () => { try { set({ settings: await settingsApi.get() }) } catch { /* the defaults below apply */ } },
  save: async (patch) => set({ settings: await settingsApi.save(patch) }),
}))
