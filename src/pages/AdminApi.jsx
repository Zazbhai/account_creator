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
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [marginFee, setMarginFee] = useState('')
  const [savingMargin, setSavingMargin] = useState(false)
  const [marginBalance, setMarginBalance] = useState(0)
  const [popup, setPopup] = useState({ type: null, message: '' })

  useEffect(() => {
    loadSettings()
    loadMargin()
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

  const loadMargin = async () => {
    try {
      const res = await axios.get('/api/admin/margin-fees', { withCredentials: true })
      if (typeof res.data.per_account_fee === 'number') {
        setMarginFee(res.data.per_account_fee.toString())
      }
      if (typeof res.data.margin_balance === 'number') {
        setMarginBalance(res.data.margin_balance)
      }
    } catch (err) {
      console.error('Error loading margin fees:', err)
      // Don't show popup here to avoid overriding API errors
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

  const handleSaveMargin = async (e) => {
    e.preventDefault()
    setSavingMargin(true)
    setPopup({ type: null, message: '' })
    try {
      const numericFee = parseFloat(marginFee)
      if (!numericFee || numericFee <= 0) {
        throw new Error('Margin fee must be greater than zero')
      }
      await axios.post(
        '/api/admin/margin-fees',
        { per_account_fee: numericFee },
        { withCredentials: true }
      )
      setPopup({ type: 'success', message: 'Margin fees updated successfully' })
    } catch (err) {
      setPopup({
        type: 'error',
        message:
          err.response?.data?.error ||
          err.message ||
          'Failed to update margin fees',
      })
    } finally {
      setSavingMargin(false)
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
        <button type="submit" disabled={saving}>
          {saving ? 'Saving...' : 'Save API Settings'}
        </button>
      </form>

      <h3 style={{ marginTop: '32px', marginBottom: '8px' }}>Margin Fees</h3>
      <form onSubmit={handleSaveMargin} className="api-form">
        <div className="form-group">
          <label>Current total margin fees balance (₹):</label>
          <input
            type="text"
            value={`₹${marginBalance.toFixed(2)}`}
            readOnly
            disabled
          />
        </div>
        <div className="form-group">
          <label>Margin per account (₹):</label>
          <input
            type="number"
            step="0.01"
            min="0"
            value={marginFee}
            onChange={(e) => setMarginFee(e.target.value)}
            required
            disabled={savingMargin}
          />
        </div>
        <button type="submit" disabled={savingMargin}>
          {savingMargin ? 'Saving...' : 'Save Margin Fees'}
        </button>
      </form>
    </div>
  )
}
