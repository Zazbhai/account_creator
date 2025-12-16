import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Skeleton } from '../components/Skeleton'
import './IMAPSettings.css'

export default function IMAPSettings() {
  const [config, setConfig] = useState({
    host: '',
    port: 993,
    email: '',
    password: '',
    mailbox: 'INBOX',
    api_key: ''
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      const response = await axios.get('/api/imap/config', { withCredentials: true })
      const incoming = response.data.config || {}
      setConfig((prev) => ({
        // Only prefill non-sensitive fields; keep email/password/api_key empty in UI
        ...prev,
        host: incoming.host || prev.host,
        port: incoming.port || prev.port,
        mailbox: incoming.mailbox || prev.mailbox,
        email: '',
        password: '',
        api_key: '',
      }))
    } catch (error) {
      console.error('Error loading config:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setMessage('')

    try {
      await axios.post('/api/imap/config', config, { withCredentials: true })
      setMessage('Settings saved successfully')
    } catch (error) {
      setMessage(error.response?.data?.error || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="imap-settings-page">
        <h2>IMAP Settings</h2>
        <Skeleton height="400px" />
      </div>
    )
  }

  return (
    <div className="imap-settings-page">
      <h2>IMAP Settings</h2>
      {message && (
        <div className={message.includes('success') ? 'success' : 'error'}>
          {message}
        </div>
      )}
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="host">IMAP Host:</label>
          <input
            type="text"
            id="host"
            value={config.host}
            onChange={(e) => setConfig({ ...config, host: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label htmlFor="port">Port:</label>
          <input
            type="number"
            id="port"
            value={config.port}
            onChange={(e) => setConfig({ ...config, port: parseInt(e.target.value) })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label htmlFor="email">Email:</label>
          <input
            type="email"
            id="email"
            value={config.email}
            onChange={(e) => setConfig({ ...config, email: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Password:</label>
          <input
            type="password"
            id="password"
            value={config.password}
            onChange={(e) => setConfig({ ...config, password: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label htmlFor="mailbox">Mailbox:</label>
          <input
            type="text"
            id="mailbox"
            value={config.mailbox}
            onChange={(e) => setConfig({ ...config, mailbox: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label htmlFor="api_key">API key:</label>
          <input
            type="text"
            id="api_key"
            value={config.api_key}
            onChange={(e) => setConfig({ ...config, api_key: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <button type="submit" disabled={saving}>
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </form>
    </div>
  )
}
