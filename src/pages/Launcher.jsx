import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'
import { useSocket } from '../hooks/useSocket'
import { useAuth } from '../hooks/useAuth'
import { Skeleton, SkeletonPill } from '../components/Skeleton'
import './Launcher.css'

export default function Launcher() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { socket } = useSocket(user?.id)
  const [balance, setBalance] = useState(null)
  const [price, setPrice] = useState(null)
  const [capacity, setCapacity] = useState(null)
  const [loading, setLoading] = useState(true)
  const [logs, setLogs] = useState([])
  const [running, setRunning] = useState(false)
  const [totalAccounts, setTotalAccounts] = useState(10)
  const [maxParallel, setMaxParallel] = useState(4)
  const [error, setError] = useState('')
  const [imapReady, setImapReady] = useState(false)
  const [showImapPopup, setShowImapPopup] = useState(false)

  useEffect(() => {
    let intervalId = null

    const init = async () => {
      try {
        const res = await axios.get('/api/imap/config', { withCredentials: true })
        const cfg = res.data.config || {}
        const missing =
          !cfg.email || !cfg.password || !cfg.api_key

        if (missing) {
          setImapReady(false)
          setShowImapPopup(true)
          setLoading(false)
          return
        }

        setImapReady(true)
        await loadBalance()
        await checkWorkerStatus()
        intervalId = setInterval(() => {
          checkWorkerStatus()
        }, 2000)
      } catch (err) {
        console.error('Error checking IMAP/API config:', err)
        setImapReady(false)
        setShowImapPopup(true)
        setLoading(false)
      }
    }

    init()

    return () => {
      if (intervalId) {
        clearInterval(intervalId)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (socket) {
      const handleLog = (data) => {
        setLogs((prev) => {
          const newLogs = [...prev, data.line]
          // Auto-scroll to bottom
          setTimeout(() => {
            const logContainer = document.querySelector('.log-container')
            if (logContainer) {
              logContainer.scrollTop = logContainer.scrollHeight
            }
          }, 100)
          return newLogs
        })
      }

      const handleBalance = (data) => {
        setBalance(data.balance)
        setPrice(data.price)
        setCapacity(data.capacity)
        setLoading(false)
      }

      const handleWorkerStatus = (data) => {
        setRunning(data.running)
      }

      socket.on('log', handleLog)
      socket.on('balance', handleBalance)
      socket.on('worker_status', handleWorkerStatus)

      return () => {
        socket.off('log', handleLog)
        socket.off('balance', handleBalance)
        socket.off('worker_status', handleWorkerStatus)
      }
    }
  }, [socket])

  const loadBalance = async () => {
    try {
      const response = await axios.get('/api/balance', { withCredentials: true })
      setBalance(response.data.balance)
      setPrice(response.data.price)
      setCapacity(response.data.capacity)
    } catch (error) {
      setError('Failed to load balance')
    } finally {
      setLoading(false)
    }
  }

  const checkWorkerStatus = async () => {
    try {
      const response = await axios.get('/api/worker-status', { withCredentials: true })
      setRunning(response.data.running)
    } catch (error) {
      console.error('Error checking worker status:', error)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!imapReady) {
      setShowImapPopup(true)
      return
    }
    setError('')
    setLogs([])

    try {
      const formData = new URLSearchParams()
      formData.append('total_accounts', totalAccounts)
      formData.append('max_parallel', maxParallel)

      await axios.post('/api/run', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        withCredentials: true
      })

      setRunning(true)
    } catch (error) {
      setError(error.response?.data?.error || 'Failed to start workers')
    }
  }

  const handleStop = async () => {
    try {
      await axios.post('/api/stop', {}, { withCredentials: true })
      setRunning(false)
    } catch (error) {
      console.error('Error stopping workers:', error)
    }
  }

  return (
    <div className="launcher-page">
      <h2>Account Launcher</h2>
      
      {error && <div className="error">{error}</div>}

      <div className="info-pills">
        {loading ? (
          <>
            <SkeletonPill />
            <SkeletonPill />
            <SkeletonPill />
          </>
        ) : (
          <>
            <span className="info-pill">
              Balance: ₹{balance !== null ? balance.toFixed(2) : 'N/A'}
            </span>
            <span className="info-pill">
              Price: ₹{price !== null ? price.toFixed(2) : 'N/A'}
            </span>
            <span className="info-pill">
              Can create: {capacity || 0} account(s)
            </span>
          </>
        )}
      </div>

      <form onSubmit={handleSubmit} className="launcher-form">
        <div className="form-group">
          <label htmlFor="total_accounts">Total Accounts to Create:</label>
          <input
            type="number"
            id="total_accounts"
            value={totalAccounts}
            onChange={(e) => setTotalAccounts(parseInt(e.target.value))}
            min="1"
            max={capacity || undefined}
            required
            disabled={running || !imapReady}
          />
        </div>
        <div className="form-group">
          <label htmlFor="max_parallel">Maximum Parallel Windows:</label>
          <input
            type="number"
            id="max_parallel"
            value={maxParallel}
            onChange={(e) => setMaxParallel(parseInt(e.target.value))}
            min="1"
            required
            disabled={running || !imapReady}
          />
        </div>
        <button type="submit" disabled={running || loading} className={running ? 'running' : ''}>
          {running ? (
            <>
              <span className="spinner"></span>
              Running...
            </>
          ) : (
            'Start Creating Accounts'
          )}
        </button>
        {running && (
          <button type="button" onClick={handleStop} className="stop-button">
            Stop All Workers
          </button>
        )}
      </form>

      <div className="log-container">
        {logs.length === 0 ? (
          <div className="log-line">No logs yet. Start creating accounts to see logs here.</div>
        ) : (
          logs.map((line, index) => (
            <div key={index} className="log-line">
              {line}
            </div>
          ))
        )}
      </div>

      {showImapPopup && (
        <div className="popup-overlay">
          <div className="popup">
            <h3>Configuration Required</h3>
            <p>
              Please enter your IMAP email, password, and Temporasms API key in the IMAP
              settings page before starting account creation.
            </p>
            <div style={{ marginTop: '16px', display: 'flex', gap: '10px', justifyContent: 'center' }}>
              <button
                type="button"
                onClick={() => {
                  setShowImapPopup(false)
                  navigate('/imap')
                }}
              >
                Go to IMAP Settings
              </button>
              <button
                type="button"
                onClick={() => setShowImapPopup(false)}
                style={{ background: '#c62828' }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
