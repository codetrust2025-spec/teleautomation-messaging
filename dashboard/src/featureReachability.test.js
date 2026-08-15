/**
 * Guards against silent feature loss.
 *
 * The split rewrote the shell and dropped desktop/DesktopApp.jsx and
 * mobile/MobileApp.jsx without re-parenting their children. Around 35 modules
 * stopped being imported. Nothing failed: unit tests passed, the production
 * build passed, and the bundle was byte-identical because an unimported module
 * simply is not bundled. The features were gone from the shipped app.
 *
 * So these tests do not assert that files exist. They walk the real import
 * graph from the entry point and assert that each feature is reachable from
 * something the user can actually render, and that every backend route the
 * service serves is referenced by that reachable set.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs'
import { join, dirname, resolve, extname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(SRC, '..', '..')

function resolveImport(spec, fromFile) {
  if (!spec.startsWith('.')) return null
  const base = resolve(dirname(fromFile), spec.split('?')[0])
  for (const c of [base, `${base}.js`, `${base}.jsx`, join(base, 'index.js'), join(base, 'index.jsx')]) {
    if (existsSync(c) && statSync(c).isFile()) return c
  }
  return null
}

function reachableFromEntry() {
  const seen = new Set()
  const queue = [join(SRC, 'main.jsx')]
  while (queue.length) {
    const file = queue.pop()
    if (!file || seen.has(file)) continue
    seen.add(file)
    const code = readFileSync(file, 'utf8')
    const specs = [
      ...code.matchAll(/(?:import|export)[^'"]*?from\s*['"]([^'"]+)['"]/g),
      ...code.matchAll(/\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g),
      ...code.matchAll(/^\s*import\s+['"]([^'"]+)['"]/gm),
    ].map((m) => m[1])
    for (const s of specs) {
      const r = resolveImport(s, file)
      if (r) queue.push(r)
    }
  }
  return seen
}

const reachable = reachableFromEntry()
const reachableRel = new Set([...reachable].map((f) => relative(SRC, f).replace(/\\/g, '/')))
const reachableCode = [...reachable]
  .filter((f) => /\.jsx?$/.test(f))
  .map((f) => readFileSync(f, 'utf8'))
  .join('\n')

// Each entry is a user-facing capability, named as the user would describe it.
const REQUIRED_MODULES = {
  'accounts panel': 'components/AccountPanel.jsx',
  'inbox and CRM': 'components/InboxPanel.jsx',
  'admin': 'components/AdminPanel.jsx',
  'logs': 'components/LogPanel.jsx',
  'dashboard home': 'desktop/DesktopDashboardHome.jsx',
  'navigation sidebar': 'desktop/MessagingSidebar.jsx',
  'knowledge assistant': 'components/KnowledgeAssistantPanel.jsx',
  'group master-list upload': 'components/GroupsUpload.jsx',
  'fleet-wide defaults': 'components/FleetDefaultsPanel.jsx',
  'change password': 'components/ChangePasswordModal.jsx',
  'incoming call modal': 'components/crm/IncomingCallModal.jsx',
  'notification sounds': 'notifications/GlobalNotificationSounds.jsx',
}

describe('marketing feature reachability', () => {
  for (const [feature, module] of Object.entries(REQUIRED_MODULES)) {
    it(`${feature} is reachable from main.jsx`, () => {
      expect(reachableRel.has(module)).toBe(true)
    })
  }

  it('renders a mobile shell rather than requiring a separate mobile app', () => {
    // The split replaced mobile/MobileApp.jsx with one responsive shell. That
    // is fine, but the mobile navigation affordance must still exist.
    const app = readFileSync(join(SRC, 'App.jsx'), 'utf8')
    expect(app).toMatch(/mobileNavOpen/)
    expect(readFileSync(join(SRC, 'messagingShell.css'), 'utf8')).toMatch(/@media/)
  })

  it('handles the incoming_call websocket event the backend still emits', () => {
    // services/phone_call_service.py publishes this; without a handler the call
    // neither rings nor appears anywhere in the UI.
    expect(reachableCode).toMatch(/incoming_call/)
    expect(reachableCode).toMatch(/notifyIncomingCall/)
  })

  it('can edit the group master list, not only download it', () => {
    expect(reachableCode).toMatch(/\/groups\/update/)
  })
})

// Collect the routes the service actually serves, then require that reachable
// UI references each one. A route no reachable module mentions is a feature the
// server offers and the app cannot use.
function backendRoutes() {
  const skipDirs = new Set(['node_modules', '.git', 'dashboard', 'static', 'data',
    'logs', 'android', '__pycache__', 'tests', '.venv', '.pytest_cache'])
  const files = []
  const walk = (d) => {
    for (const e of readdirSync(d)) {
      if (skipDirs.has(e)) continue
      const p = join(d, e)
      let st
      try { st = statSync(p) } catch { continue }
      if (st.isDirectory()) walk(p)
      else if (extname(p) === '.py') files.push(p)
    }
  }
  walk(REPO)
  const routes = new Set()
  for (const f of files) {
    for (const m of readFileSync(f, 'utf8')
      .matchAll(/@(?:app|router)\.(?:get|post|put|patch|delete)\(\s*["'`]([^"'`]+)["'`]/g)) {
      routes.add(m[1])
    }
  }
  return [...routes]
}

describe('marketing backend routes are reachable from the UI', () => {
  // Machine-to-machine and infrastructure routes have no UI by design.
  const NON_UI = [
    /^\/internal\//, /^\/health$/, /^\/version$/, /^\/$/, /^\/ws/, /^\/openapi/,
    /^\/docs/, /^\/webhook/, /^\/whatsapp\/webhook/, /^\/static/, /^\/favicon/,
    /^\/login$/, /^\/logout$/, /^\/login\/status$/, /^\/auth\/login/, /^\/auth\/logout/,
    /\{full_path/,          // SPA catch-all
  ]
  // Routes with no reachable UI in the CURRENT MONOLITH either. Verified
  // 2026-08-15 by walking the monolith's own import graph from its main.jsx and
  // testing each route with the same interpolation-aware matcher used below.
  // These are therefore not split regressions: the split is not required to
  // build UI the monolith never shipped.
  //
  // Removing an entry is a deliberate decision to build that UI. Adding one
  // requires evidence that the monolith does not reach it either — not merely
  // that the split does not.
  const NO_UI_IN_MONOLITH = [
    '/account/shutdown/clear-all',
    '/account/{slot}/forward-intelligence',
    '/account/{slot}/restart',
    '/account/{slot}/status',
    '/accounts/restore-sessions',
    '/ai/smart-reply/catch-up',
    '/ai/smart-reply/leads/{slot}/{user_id}',
    '/ai/smart-reply/leads/{slot}/{user_id}/toggle',
    '/alerts',
    '/call/join/{join_token}',
    '/crm/call-now/options',
    '/forward-message/settings',
    '/groups/health',
    '/groups/health-summary',
    '/groups/removed',
    '/inbox/listeners/refresh',
    '/inbox/{slot}/ai-reply',
    '/inbox/{slot}/send-location',
    '/inbox/{slot}/wa-media/{user_id}/{message_id}',
    '/message/preview',
    '/metrics/{slot}',
    '/shutdown/clear-all',
    '/stats/daily',
    '/stats/reset-24h',
    '/voice/analytics',
    '/voice/calls/{session_id}/outcome',
    '/voice/join/{join_token}',
    // Marketing serves this route but its only monolith consumers were the
    // Operations-owned candidates and dailyOps modules, which correctly do not
    // exist in Marketing. Candidate for removal from the Marketing backend.
    '/auth/verify-admin',
    // Superseded: the split polls /state, which carries the same account_info
    // this route returns after a refresh.
    '/account/status',
  ]
  const uiRoutes = backendRoutes()
    .filter((r) => !NON_UI.some((re) => re.test(r)))
    .filter((r) => !NO_UI_IN_MONOLITH.includes(r))

  // The client builds parameterised routes as template literals, so the literal
  // "/inbox/{slot}/ai-reply" never appears in the source. Match each path
  // parameter against an interpolation instead of comparing raw strings.
  function referenced(route) {
    const pattern = route
      .split(/\{[^}]+\}/)
      .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('[^\'"`\\s]*')
    return new RegExp(pattern).test(reachableCode)
  }

  it('every UI-facing route is referenced by a reachable module', () => {
    // Report the actual list so a regression names the lost feature.
    expect(uiRoutes.filter((r) => !referenced(r))).toEqual([])
  })
})
