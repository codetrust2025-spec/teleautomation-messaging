import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { ConfirmProvider } from './context/ConfirmContext.jsx'
import { AuthGate } from './components/AuthGate.jsx'
import './index.css'
import './teleautomation.css'
import './inbox/inboxLayout.css'
import './components/ui/CommonModal.css'
import './inbox/outgoingCall.css'
import './admin.css'
import './responsive.css'
import './desktop/desktopDashboard.css'
import './messagingShell.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><AuthProvider><ConfirmProvider><AuthGate><App /></AuthGate></ConfirmProvider></AuthProvider></React.StrictMode>,
)
