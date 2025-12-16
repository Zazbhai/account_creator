import React from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import './Layout.css'

export default function Layout({ children }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const isAdmin = user?.role === 'admin'

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

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
    '/reports': 'Reports',
    '/logs': 'Logs',
    '/admin/dashboard': 'Admin Dashboard',
    '/admin/api': 'API Settings',
    '/admin/users': 'User Management'
  }
  return titles[pathname] || 'Account Creator'
}
