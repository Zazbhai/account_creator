import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Skeleton, SkeletonCard } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'
import './AdminApi.css'

export default function AdminApi() {
  const [settings, setSettings] = useState({
    base_url: '',
    service: '',
    operator: '',
    country: '',
    default_price: 6.99,
    wait_for_otp: 5,
    wait_for_second_otp: 5,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [popup, setPopup] = useState({ type: null, message: '' })

  useEffect(() => {
    loadSettings()
  }, [])

  const loadSettings = async () => {
    try {
      const res = await axios.get('/api/admin/api-settings', { withCredentials: true })
      setSettings(res.data.settings || settings)
    } catch (err) {
      console.error('Error loading API settings:', err)
      setPopup({ type: 'error', message: 'Failed to load API settings' })
    } finally {
      setLoading(false)
    }
  }


  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setPopup({ type: null, message: '' })

    try {
      const res = await axios.post('/api/admin/api-settings', settings, {
        withCredentials: true,
      })
      setSettings(res.data.settings || settings)
      setPopup({ type: 'success', message: 'API settings saved successfully' })
    } catch (err) {
      setPopup({
        type: 'error',
        message: err.response?.data?.error || 'Failed to save API settings',
      })
    } finally {
      setSaving(false)
    }
  }


  if (loading) {
    return (
      <div className="admin-api-page">
        <h2>API Settings</h2>
        <SkeletonCard />
      </div>
    )
  }

  return (
    <div className="admin-api-page">
      <h2>API Settings</h2>
      {popup.message && (
        <StatusPopup
          type={popup.type}
          message={popup.message}
          onClose={() => setPopup({ type: null, message: '' })}
        />
      )}
      <form onSubmit={handleSubmit} className="api-form">
        <div className="form-group">
          <label>API Base URL:</label>
          <input
            type="text"
            value={settings.base_url}
            onChange={(e) => setSettings({ ...settings, base_url: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label>Service Code:</label>
          <input
            type="text"
            value={settings.service}
            onChange={(e) => setSettings({ ...settings, service: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label>Operator:</label>
          <input
            type="text"
            value={settings.operator}
            onChange={(e) => setSettings({ ...settings, operator: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label>Country:</label>
          <input
            type="text"
            value={settings.country}
            onChange={(e) => setSettings({ ...settings, country: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label>Default Price (₹):</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={settings.default_price}
            onChange={(e) => setSettings({ ...settings, default_price: e.target.value })}
            required
            disabled={saving}
          />
        </div>
        <div className="form-group">
          <label>Wait for First OTP (minutes):</label>
          <input
            type="number"
            step="0.1"
            min="0.1"
            value={settings.wait_for_otp}
            onChange={(e) => setSettings({ ...settings, wait_for_otp: e.target.value })}
            required
            disabled={saving}
          />
          <small>Time to wait for first OTP (signup OTP) before timing out (in minutes)</small>
        </div>
        <div className="form-group">
          <label>Wait for Second OTP (minutes):</label>
          <input
            type="number"
            step="0.1"
            min="0.1"
            value={settings.wait_for_second_otp}
            onChange={(e) => setSettings({ ...settings, wait_for_second_otp: e.target.value })}
            required
            disabled={saving}
          />
          <small>Time to wait for second OTP (phone OTP) after requesting new OTP (in minutes)</small>
        </div>
        <button type="submit" disabled={saving}>
          {saving ? 'Saving...' : 'Save API Settings'}
        </button>
      </form>
    </div>
  )
}
