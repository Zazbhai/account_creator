import React, { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import axios from 'axios'
import './Layout.css'

export default function Layout({ children }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [imapMissing, setImapMissing] = useState(false)
  const [imapChecked, setImapChecked] = useState(false)

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  // Global IMAP/API key guard for non-admin users
  useEffect(() => {
    if (!user || isAdmin) {
      setImapMissing(false)
      setImapChecked(true)
      return
    }

    let cancelled = false

    const checkImap = async () => {
      try {
        const res = await axios.get('/api/imap/config', { withCredentials: true })
        const cfg = res.data.config || {}
        const missing = !cfg.email || !cfg.password || !cfg.api_key
        if (cancelled) return
        setImapMissing(missing)
        setImapChecked(true)
        if (missing && location.pathname !== '/imap') {
          navigate('/imap')
        }
      } catch (err) {
        if (cancelled) return
        setImapMissing(true)
        setImapChecked(true)
        if (location.pathname !== '/imap') {
          navigate('/imap')
        }
      }
    }

    checkImap()

    return () => {
      cancelled = true
    }
  }, [user, isAdmin, location.pathname, navigate])

  return (
    <div className="layout">
      <div className="container">
        <div className="header">
          <h1>{getPageTitle(location.pathname)}</h1>
          <div className="nav-links">
            {!isAdmin && (
              <>
                <Link to="/" className={`nav-btn ${location.pathname === '/' ? 'active' : ''}`}>
                  Launcher
                </Link>
                <Link to="/imap" className={`nav-btn ${location.pathname === '/imap' ? 'active' : ''}`}>
                  IMAP
                </Link>
                <Link to="/funds" className={`nav-btn ${location.pathname === '/funds' ? 'active' : ''}`}>
                  Add Funds
                </Link>
                <Link to="/reports" className={`nav-btn ${location.pathname === '/reports' ? 'active' : ''}`}>
                  Reports
                </Link>
                <Link to="/logs" className={`nav-btn ${location.pathname === '/logs' ? 'active' : ''}`}>
                  Logs
                </Link>
              </>
            )}
            {isAdmin && (
              <>
                <Link to="/admin/dashboard" className={`nav-btn ${location.pathname === '/admin/dashboard' ? 'active' : ''}`}>
                  Dashboard
                </Link>
                <Link to="/admin/api" className={`nav-btn ${location.pathname === '/admin/api' ? 'active' : ''}`}>
                  API
                </Link>
                <Link to="/admin/users" className={`nav-btn ${location.pathname === '/admin/users' ? 'active' : ''}`}>
                  Users
                </Link>
              </>
            )}
            <button onClick={handleLogout} className="logout-btn">
              Logout
            </button>
          </div>
        </div>
        {!isAdmin && imapChecked && imapMissing && location.pathname !== '/imap' && (
          <div className="popup-overlay">
            <div className="popup">
              <h3>Configuration Required</h3>
              <p>
                Please enter your IMAP email, password, and Temporasms API key in the IMAP
                settings page before using the app.
              </p>
              <div
                style={{
                  marginTop: '16px',
                  display: 'flex',
                  gap: '10px',
                  justifyContent: 'center',
                }}
              >
                <button
                  type="button"
                  onClick={() => {
                    if (location.pathname !== '/imap') {
                      navigate('/imap')
                    }
                  }}
                >
                  Go to IMAP Settings
                </button>
              </div>
            </div>
          </div>
        )}
        {children}
      </div>
      <div className="bottom-nav">
        {!isAdmin && (
          <>
            <Link to="/" className={`link-btn ${location.pathname === '/' ? 'active' : ''}`}>
              Launcher
            </Link>
            <Link to="/imap" className={`link-btn ${location.pathname === '/imap' ? 'active' : ''}`}>
              IMAP
            </Link>
            <Link to="/funds" className={`link-btn ${location.pathname === '/funds' ? 'active' : ''}`}>
              Add Funds
            </Link>
            <Link to="/reports" className={`link-btn ${location.pathname === '/reports' ? 'active' : ''}`}>
              Reports
            </Link>
            <Link to="/logs" className={`link-btn ${location.pathname === '/logs' ? 'active' : ''}`}>
              Logs
            </Link>
          </>
        )}
        {isAdmin && (
          <>
            <Link to="/admin/dashboard" className={`link-btn ${location.pathname === '/admin/dashboard' ? 'active' : ''}`}>
              Dashboard
            </Link>
            <Link to="/admin/api" className={`link-btn ${location.pathname === '/admin/api' ? 'active' : ''}`}>
              API
            </Link>
            <Link to="/admin/users" className={`link-btn ${location.pathname === '/admin/users' ? 'active' : ''}`}>
              Users
            </Link>
          </>
        )}
      </div>
    </div>
  )
}

function getPageTitle(pathname) {
  const titles = {
    '/': 'Launcher',
    '/imap': 'IMAP Settings',
    '/funds': 'Add Funds',
    '/reports': 'Reports',
    '/logs': 'Logs',
    '/admin/dashboard': 'Admin Dashboard',
    '/admin/api': 'API Settings',
    '/admin/users': 'User Management'
  }
  return titles[pathname] || 'Account Creator'
}
