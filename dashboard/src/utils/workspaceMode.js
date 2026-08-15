const STORAGE_KEY = 'tg_workspace_mode'

export const WORKSPACE_FORWARDING = 'forwarding'
export const WORKSPACE_CAMPAIGN = 'campaign'
export const WORKSPACE_FLEET = 'fleet'

export const WORKSPACE_MODE_OPTIONS = [
  { value: WORKSPACE_FORWARDING, label: 'Forward' },
  { value: WORKSPACE_CAMPAIGN, label: 'Campaign' },
]

export function loadWorkspaceMode() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === WORKSPACE_CAMPAIGN || v === WORKSPACE_FORWARDING || v === WORKSPACE_FLEET) return v
  } catch {
    /* ignore */
  }
  return WORKSPACE_FORWARDING
}

export function saveWorkspaceMode(mode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
}
