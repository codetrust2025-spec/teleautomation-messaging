import React from 'react'

export function AccountsLoginGuide({ loggedInCount, onOpenSetupTab }) {
  return (
    <div className="accounts-login-guide" role="note">
      <p className="accounts-login-guide__lead">
        Manage which Telegram numbers are connected. To start or stop sending, use the{' '}
        {onOpenSetupTab ? (
          <button type="button" className="accounts-login-guide__link" onClick={onOpenSetupTab}>
            Setup tab
          </button>
        ) : (
          <strong>Setup tab</strong>
        )}
        .
      </p>
      <ol className="accounts-login-guide__steps">
        <li>Pick an account card below (or tap <strong>+ Add account</strong>).</li>
        <li>Log in with phone + OTP, or log out to switch numbers.</li>
        <li>Set each account to <strong>Forward</strong> or <strong>Campaign</strong> desk.</li>
      </ol>
      {loggedInCount > 0 && (
        <div className="accounts-login-guide__legend" aria-label="Card badge legend">
          <span className="accounts-login-guide__legend-title">Card badges</span>
          <span className="accounts-login-guide__legend-item">
            <span className="account-mini-status-pill account-mini-status-pill--running">Active</span>
            sending now
          </span>
          <span className="accounts-login-guide__legend-item">
            <span className="account-mini-status-pill account-mini-status-pill--sleeping">Waiting</span>
            paused between cycles
          </span>
          <span className="accounts-login-guide__legend-item">
            <span className="account-mini-mode-pill account-mini-mode-pill--forward">Forward</span>
            forwards posts
          </span>
          <span className="accounts-login-guide__legend-item">
            <span className="account-mini-mode-pill">Campaign</span>
            sends campaign messages
          </span>
        </div>
      )}
    </div>
  )
}
