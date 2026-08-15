import React from 'react'

import { ForwardMessagePanel } from './ForwardMessagePanel.jsx'
import { MessageEditor } from './MessageEditor.jsx'
import { PostingModePanel } from './PostingModePanel.jsx'
import { AccountPrimaryActions } from './AccountPrimaryActions.jsx'
import { WORKSPACE_CAMPAIGN, WORKSPACE_FORWARDING } from '../utils/workspaceMode.js'

export function ModesSetupPanel({
  slot,
  workspaceMode = WORKSPACE_FORWARDING,
  customMessage,
  rewriteEnabled,
  cyclePreview,
  onMessageSaved,
  onPostingModeUpdated,
  postingModeConfig,
  postingModes,
  accountStates,
  acctRunning = false,
  forwardJob,
  workerRunning = false,
  loggedIn = false,
  onStartAccount,
  onStopAccount,
  accountActionLoading = null,
}) {
  const fwd = postingModeConfig?.forwarding || {}
  const forwardSourceType = fwd.source_type === 'telegram_post' ? 'telegram_post' : 'template'
  const acctState = slot ? accountStates?.[slot] || {} : {}

  const showMessageEditor = workspaceMode === WORKSPACE_CAMPAIGN
    || (workspaceMode === WORKSPACE_FORWARDING && forwardSourceType === 'template')

  if (!slot) return null

  return (
    <div className={`modes-setup-panel modes-setup-panel--${workspaceMode}`}>
      <section className="setup-main__block" aria-labelledby="setup-main-run">
        <h3 id="setup-main-run" className="setup-main__heading">
          <span className="setup-main__num">3</span> Start or stop
        </h3>
        <AccountPrimaryActions
          slot={slot}
          postingModeConfig={postingModeConfig}
          postingModes={postingModes}
          accountStates={accountStates}
          acctState={acctState}
          forwardJob={forwardJob}
          onStart={onStartAccount}
          onStop={onStopAccount}
          accountActionLoading={accountActionLoading}
          forcedMode={workspaceMode}
          className="modes-setup-primary-actions"
        />
      </section>

      <details className="acct-setup-details modes-setup-details setup-main__details" open>
        <summary className="acct-setup-details__summary setup-main__details-summary">
          <span className="setup-main__num setup-main__num--inline">4</span>
          {workspaceMode === WORKSPACE_FORWARDING ? 'Link & options' : 'Message & options'}
        </summary>
        <PostingModePanel
          slot={slot}
          postingModeConfig={postingModeConfig}
          postingModes={postingModes}
          accountStates={accountStates}
          acctRunning={acctRunning}
          onUpdated={onPostingModeUpdated}
          onStartForward={s => onStartAccount?.(s, false, 'forwarding')}
          onStopForward={s => onStopAccount?.(s, 'forwarding')}
          setupFilter={workspaceMode}
          layout="simple"
          primaryMode={workspaceMode}
        />

        {showMessageEditor && (
          <MessageEditor
            key={`${slot}-${workspaceMode}-template`}
            slot={slot}
            customMessage={customMessage}
            rewriteEnabled={rewriteEnabled}
            cyclePreview={cyclePreview}
            onSaved={onMessageSaved}
          />
        )}

        {workspaceMode === WORKSPACE_FORWARDING && fwd.forward_dispatch === 'manual' && (
          <ForwardMessagePanel
            slot={slot}
            job={forwardJob}
            workerRunning={workerRunning}
            loggedIn={loggedIn}
            postingModeConfig={postingModeConfig}
          />
        )}

        {workspaceMode === WORKSPACE_FORWARDING && forwardSourceType === 'telegram_post' && (
          <p className="stat-hint modes-setup-hint">
            Uses the <strong>t.me link</strong> below.
          </p>
        )}
      </details>
    </div>
  )
}
