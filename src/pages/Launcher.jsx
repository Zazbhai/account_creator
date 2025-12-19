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

  const [popup, setPopup] = useState({ type: null, message: '' })

  const [imapReady, setImapReady] = useState(false)

  const [showImapPopup, setShowImapPopup] = useState(false)

  const [showBalancePopup, setShowBalancePopup] = useState(false)

  const [amountNeeded, setAmountNeeded] = useState(null)
  const [useUsedAccount, setUseUsedAccount] = useState(true)
  const [retryFailed, setRetryFailed] = useState(true)
  const [marginBalance, setMarginBalance] = useState(null)



  useEffect(() => {

    let intervalId = null



    const init = async () => {

      try {
        console.log('[DEBUG] [Launcher] Calling GET /api/imap/config')
        const res = await axios.get('/api/imap/config', { withCredentials: true })
        console.log('[DEBUG] [Launcher] GET /api/imap/config response:', res.data)

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
        await loadMarginBalance()

        await checkWorkerStatus()

        intervalId = setInterval(() => {

          checkWorkerStatus()
          loadMarginBalance()

        }, 2000)

      } catch (err) {
        console.error('[DEBUG] [Launcher] Error checking IMAP/API config:', err)
        console.error('[DEBUG] [Launcher] Error response:', err.response?.data)
        console.error('[DEBUG] [Launcher] Error status:', err.response?.status)

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



  // Socket is now used only for balance and worker status;

  // logs in the launcher are sourced from latest_logs.txt via HTTP polling.

  useEffect(() => {

    if (socket) {

      const handleBalance = (data) => {
        console.log('[DEBUG] [Launcher] Socket event: balance', data)

        setBalance(data.balance)

        setPrice(data.price)

        setCapacity(data.capacity)

        setLoading(false)

      }



      const handleWorkerStatus = (data) => {
        console.log('[DEBUG] [Launcher] Socket event: worker_status', data)

        setRunning(data.running)

      }



      socket.on('balance', handleBalance)

      socket.on('worker_status', handleWorkerStatus)



      return () => {

        socket.off('balance', handleBalance)

        socket.off('worker_status', handleWorkerStatus)

      }

    }

  }, [socket])



  const loadBalance = async () => {

    try {
      console.log('[DEBUG] [Launcher] Calling GET /api/balance')
      const response = await axios.get('/api/balance', { withCredentials: true })
      console.log('[DEBUG] [Launcher] GET /api/balance response:', response.data)

      setBalance(response.data.balance)

      setPrice(response.data.price)

      setCapacity(response.data.capacity)

    } catch (error) {
      console.error('[DEBUG] [Launcher] Error in loadBalance:', error)
      console.error('[DEBUG] [Launcher] Error response:', error.response?.data)
      setPopup({ type: 'error', message: 'Failed to load balance' })

    } finally {

      setLoading(false)

    }

  }



  const checkWorkerStatus = async () => {

    try {
      console.log('[DEBUG] [Launcher] Calling GET /api/worker-status')
      const response = await axios.get('/api/worker-status', {

        withCredentials: true,

        skipLoader: true,

      })
      console.log('[DEBUG] [Launcher] GET /api/worker-status response:', response.data)

      setRunning(response.data.running)

    } catch (error) {
      console.error('[DEBUG] [Launcher] Error in checkWorkerStatus:', error)
      console.error('[DEBUG] [Launcher] Error response:', error.response?.data)

    }

  }

  const loadMarginBalance = async () => {
    try {
      console.log('[DEBUG] [Launcher] Calling GET /api/margin-fees')
      const response = await axios.get('/api/margin-fees', {
        withCredentials: true,
        skipLoader: true,
      })
      console.log('[DEBUG] [Launcher] GET /api/margin-fees response:', response.data)
      if (typeof response.data.margin_balance === 'number') {
        setMarginBalance(response.data.margin_balance)
      } else {
        setMarginBalance(0)  // Set to 0 instead of null so skeleton doesn't show
      }
    } catch (error) {
      console.error('[DEBUG] [Launcher] Error loading margin balance:', error)
      console.error('[DEBUG] [Launcher] Error response:', error.response?.data)
      setMarginBalance(0)  // Set to 0 on error so skeleton doesn't show forever
    }
  }



  const loadLatestLogs = async ({ silent = false } = {}) => {

    try {
      if (!silent) {
        console.log('[DEBUG] [Launcher] Calling GET /api/reports/log-file?name=latest_logs.txt')
      }
      const res = await axios.get('/api/reports/log-file', {

        params: { name: 'latest_logs.txt' },

        withCredentials: true,

        skipLoader: true,

      })
      if (!silent) {
        console.log('[DEBUG] [Launcher] GET /api/reports/log-file response length:', res.data.content?.length || 0)
      }

      const content = res.data.content || ''

      const lines = content.split('\n').filter((line) => line.trim() !== '')

      setLogs(lines)



      // Auto-scroll to bottom

      setTimeout(() => {

        const logContainer = document.querySelector('.log-container')

        if (logContainer) {

          logContainer.scrollTop = logContainer.scrollHeight

        }

      }, 50)

    } catch (err) {

      // If file doesn't exist yet, just show "no logs" silently

      if (err.response?.status === 404) {
        if (!silent) {
          console.log('[DEBUG] [Launcher] GET /api/reports/log-file - file not found (404)')
        }
        setLogs([])

        return

      }

      console.error('[DEBUG] [Launcher] Error loading latest logs:', err)
      console.error('[DEBUG] [Launcher] Error response:', err.response?.data)

      if (!silent) {

        // Keep top-level error for run/balance; don't override it here

      }

    }

  }



  // Poll latest_logs.txt to keep launcher logs up to date without reload

  useEffect(() => {

    loadLatestLogs()

    const id = setInterval(() => {

      loadLatestLogs({ silent: true })

    }, 2000)

    return () => clearInterval(id)

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [])



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
      formData.append('use_used_account', useUsedAccount ? '1' : '0')
      formData.append('retry_failed', retryFailed ? '1' : '0')

      console.log('[DEBUG] [Launcher] Calling POST /api/run with data:', {
        total_accounts: totalAccounts,
        max_parallel: maxParallel,
        use_used_account: useUsedAccount ? '1' : '0',
        retry_failed: retryFailed ? '1' : '0',
      })

      const response = await axios.post('/api/run', formData, {

        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },

        withCredentials: true,

      })
      console.log('[DEBUG] [Launcher] POST /api/run response:', response.data)



      setRunning(true)
      // Reload balance, price, capacity, and margin balance IMMEDIATELY after starting
      console.log('[DEBUG] [Launcher] Reloading balance and margin balance after start')
      await Promise.all([
        loadBalance(),
        loadMarginBalance()
      ])
      setTimeout(() => {
        loadLatestLogs({ silent: true })
      }, 500)

    } catch (error) {
      console.error('[DEBUG] [Launcher] Error in handleSubmit:', error)
      console.error('[DEBUG] [Launcher] Error response:', error.response?.data)
      console.error('[DEBUG] [Launcher] Error status:', error.response?.status)

      const msg = error.response?.data?.error || 'Failed to start workers'

      const needed = error.response?.data?.amount_needed

      setPopup({ type: 'error', message: msg })

      if (typeof needed === 'number' && needed > 0) {

        setAmountNeeded(needed)

        setShowBalancePopup(true)

      }

    }

  }



  const handleStop = async () => {

    try {
      console.log('[DEBUG] [Launcher] Calling POST /api/stop')
      const response = await axios.post('/api/stop', {}, { withCredentials: true })
      console.log('[DEBUG] [Launcher] POST /api/stop response:', response.data)

      setRunning(false)
      loadMarginBalance()

    } catch (error) {
      console.error('[DEBUG] [Launcher] Error in handleStop:', error)
      console.error('[DEBUG] [Launcher] Error response:', error.response?.data)

    }

  }



  return (

    <div className="launcher-page">

      <h2>Account Launcher</h2>

      <div className="margin-fees-row">
        <span className="margin-fees-label">Margin fees balance</span>
        {marginBalance === null ? (
          <SkeletonPill />
        ) : (
          <div
            className="margin-fees-pill"
            onClick={() => navigate('/funds')}
          >
            <span className="margin-fees-amount">
              ₹{marginBalance.toFixed(2)}
            </span>
            <span className="margin-fees-plus">+</span>
          </div>
        )}
      </div>



      {popup.message && (
        <StatusPopup
          type={popup.type}
          message={popup.message}
          onClose={() => setPopup({ type: null, message: '' })}
        />
      )}



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

        <div className="form-group toggle-group">
          <label htmlFor="use_used_account" className="toggle-label">
            <input
              id="use_used_account"
              type="checkbox"
              className="toggle-input"
              checked={useUsedAccount}
              onChange={(e) => setUseUsedAccount(e.target.checked)}
              disabled={running || !imapReady}
            />
            <span className="toggle-slider"></span>
            <span className="toggle-text">Recovery Mode</span>
          </label>
        </div>

        <div className="form-group toggle-group">
          <label htmlFor="retry_failed" className="toggle-label">
            <input
              id="retry_failed"
              type="checkbox"
              className="toggle-input"
              checked={retryFailed}
              onChange={(e) => setRetryFailed(e.target.checked)}
              disabled={running || !imapReady}
            />
            <span className="toggle-slider"></span>
            <span className="toggle-text">Retry Failed</span>
          </label>
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

        <button 
          type="submit" 
          disabled={running || loading || capacity === null || marginBalance === null} 
          className={running ? 'running' : ''}
        >

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



      {showBalancePopup && (

        <div className="popup-overlay">

          <div className="popup">

            <h3>Insufficient Balance</h3>

            <p>

              To create {totalAccounts} account(s), please add at least ₹

              {amountNeeded != null ? amountNeeded.toFixed(2) : '0.00'} to your SMS balance.

            </p>

            <button

              type="button"

              onClick={() => setShowBalancePopup(false)}

              style={{ marginTop: '16px' }}

            >

              OK

            </button>

          </div>

        </div>

      )}



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

