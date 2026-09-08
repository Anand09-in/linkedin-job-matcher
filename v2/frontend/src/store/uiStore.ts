import { create } from 'zustand'

/** Cross-page UI-only state — deliberately small: almost everything else in
 * this app is server state that belongs in React Query, not here. The one
 * thing worth sharing globally is which pipeline the user is currently
 * looking at, since both Job Results and the Tracker filter by it and
 * switching between those pages shouldn't reset the filter. */
interface UIState {
  selectedPipelineId: string | null
  setSelectedPipelineId: (id: string | null) => void
}

export const useUIStore = create<UIState>((set) => ({
  selectedPipelineId: null,
  setSelectedPipelineId: (id) => set({ selectedPipelineId: id }),
}))
