import { API } from '../config.js'

/** Set an account to Forwarding or Campaign (mutually exclusive). */
export async function applyAccountPostingMode(slot, mode) {
  if (!slot || (mode !== 'forwarding' && mode !== 'campaign')) {
    return { ok: false, error: 'Invalid slot or mode' }
  }
  const patch = mode === 'campaign'
    ? { campaign_enabled: true, forwarding_enabled: false }
    : {
        campaign_enabled: false,
        forwarding_enabled: true,
        forward_dispatch: 'auto',
      }

  try {
    const res = await fetch(`${API}/account/${slot}/posting-mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(patch),
    })
    const data = await res.json()
    if (data.status === 'error') {
      return { ok: false, error: data.message || 'Could not update mode' }
    }
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e.message || 'Request failed' }
  }
}
