import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { Skeleton } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'
import './Login.css'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [popup, setPopup] = useState({ type: null, message: '' })
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setPopup({ type: null, message: '' })
    setLoading(true)

    const result = await login(username, password)
    
    if (result.success) {
      navigate('/')
    } else {
      setPopup({ type: 'error', message: result.error || 'Invalid username or password' })
    }
    
    setLoading(false)
  }

  return (
    <div className="login-page">
      <div className="login-container">
        <h1>Account Creator</h1>
        {popup.message && (
          <StatusPopup
            type={popup.type}
            message={popup.message}
            onClose={() => setPopup({ type: null, message: '' })}
          />
        )}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="username">Username:</label>
            <input
              type="text"
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              disabled={loading}
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password:</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
            />
          </div>
          <button type="submit" disabled={loading}>
            {loading ? 'Logging in...' : 'Login'}
          </button>
        </form>
      </div>
    </div>
  )
}
