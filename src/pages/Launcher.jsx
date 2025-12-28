import React, { useState, useEffect } from 'react'

import axios from 'axios'

import { useNavigate } from 'react-router-dom'

import { useSocket } from '../hooks/useSocket'

import { useAuth } from '../hooks/useAuth'

import { Skeleton, SkeletonPill } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'
import { playStartSound, playCompletionSound } from '../utils/sounds'
import { requestNotificationPermission, notifyAccountCompletion } from '../utils/notifications'

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
  const [starting, setStarting] = useState(false)  // Loading state when starting account creation

  // Load configs from localStorage on mount
  const loadConfigsFromStorage = () => {
    try {
      const saved = localStorage.getItem('launcher_configs')
      if (saved) {
        const configs = JSON.parse(saved)
        return {
          totalAccounts: configs.totalAccounts ?? 10,
          maxParallel: configs.maxParallel ?? 4,
          useUsedAccount: configs.useUsedAccount ?? true,
          retryFailed: configs.retryFailed ?? true,
        }
      }
    } catch (e) {
      console.error('Failed to load configs from localStorage:', e)
    }
    return {
      totalAccounts: 10,
      maxParallel: 4,
      useUsedAccount: true,
      retryFailed: true,
    }
  }

  const savedConfigs = loadConfigsFromStorage()
  const [totalAccounts, setTotalAccounts] = useState(savedConfigs.totalAccounts)

  const [maxParallel, setMaxParallel] = useState(savedConfigs.maxParallel)

  const [popup, setPopup] = useState({ type: null, message: '' })

  const [imapReady, setImapReady] = useState(false)

  const [showImapPopup, setShowImapPopup] = useState(false)

  const [showBalancePopup, setShowBalancePopup] = useState(false)
  const [showNewAccountsWarning, setShowNewAccountsWarning] = useState(false)

  const [amountNeeded, setAmountNeeded] = useState(null)
  const [useUsedAccount, setUseUsedAccount] = useState(savedConfigs.useUsedAccount)
  const [retryFailed, setRetryFailed] = useState(savedConfigs.retryFailed)
  const [marginBalance, setMarginBalance] = useState(null)
  const [perAccountFee, setPerAccountFee] = useState(null)  // Per account margin fee

  // Save configs to localStorage whenever they change
  useEffect(() => {
    try {
      const configs = {
        totalAccounts,
        maxParallel,
        useUsedAccount,
        retryFailed,
      }
      localStorage.setItem('launcher_configs', JSON.stringify(configs))
    } catch (e) {
      console.error('Failed to save configs to localStorage:', e)
    }
  }, [totalAccounts, maxParallel, useUsedAccount, retryFailed])



  useEffect(() => {

    let intervalId = null

    // Request notification permission on mount
    requestNotificationPermission().then(granted => {
      if (granted) {
        console.log('[DEBUG] [Launcher] Notification permission granted')
      } else {
        console.log('[DEBUG] [Launcher] Notification permission not granted')
      }
    })

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

      const handleAccountSummary = (data) => {
        console.log('[DEBUG] [Launcher] Socket event: account_summary', data)
        
        const { success, failed, total } = data || {}
        const successCount = success || 0
        const failedCount = failed || 0
        const totalCount = total || 0
        
        // Play completion sound
        playCompletionSound()
        
        // Show browser notification
        notifyAccountCompletion(successCount, failedCount, totalCount)
        
        // Format message with line breaks
        const summaryMessage = `Account Creation Complete!\n\n✅ Successful: ${successCount}\n❌ Failed: ${failedCount}\n📊 Total: ${totalCount}`
        
        // Show popup with summary
        // Use 'success' type if all succeeded (failed === 0), otherwise use 'error' type
        setPopup({
          type: failedCount === 0 ? 'success' : 'error',
          message: summaryMessage
        })
        
        console.log('[DEBUG] [Launcher] Showing account summary popup:', { successCount, failedCount, totalCount })
      }

      const handleNoNumbers = (data) => {
        console.log('[DEBUG] [Launcher] Socket event: no_numbers', data)
        
        const message = data?.message || 'No numbers available right now. Please try again after some time.'
        
        // Show error popup
        setPopup({
          type: 'error',
          message: message
        })
        
        console.log('[DEBUG] [Launcher] Showing NO_NUMBERS popup:', message)
      }

      socket.on('balance', handleBalance)

      socket.on('worker_status', handleWorkerStatus)
      
      socket.on('account_summary', handleAccountSummary)
      
      socket.on('no_numbers', handleNoNumbers)



      return () => {

        socket.off('balance', handleBalance)

        socket.off('worker_status', handleWorkerStatus)
        
        socket.off('account_summary', handleAccountSummary)
        
        socket.off('no_numbers', handleNoNumbers)

      }

    }

  }, [socket])



  const loadBalance = async () => {

    try {
      console.log('[DEBUG] [Launcher] Calling GET /api/balance')
      const response = await axios.get('/api/balance', { withCredentials: true })
      console.log('[DEBUG] [Launcher] GET /api/balance response:', response.data)

      // Handle balance - ensure it's a number or null
      const balanceValue = typeof response.data.balance === 'number' ? response.data.balance : null
      setBalance(balanceValue)
      
      // Handle price - ensure it's a number or null
      const priceValue = typeof response.data.price === 'number' ? response.data.price : null
      setPrice(priceValue)
      
      // Handle capacity - ensure it's a number or null
      const capacityValue = typeof response.data.capacity === 'number' ? response.data.capacity : null
      setCapacity(capacityValue)

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
      // Also store per_account_fee for calculations
      if (typeof response.data.per_account_fee === 'number') {
        setPerAccountFee(response.data.per_account_fee)
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

      const allLines = content.split('\n').filter((line) => line.trim() !== '')
      
      // Transform technical logs into user-friendly messages
      const filteredLines = []
      let lastWasWaitingForOtp = false
      let lastWasRequestingNumber = false
      let inApiRequestBlock = false
      
      for (let i = 0; i < allLines.length; i++) {
        const line = allLines[i]
        const trimmed = line.trim()
        
        // Skip all API request detail blocks
        if (trimmed.includes('[CALLER API REQUEST]') || trimmed.includes('========================================================================')) {
          inApiRequestBlock = true
          continue
        }
        
        if (inApiRequestBlock) {
          if (trimmed === '' || (trimmed.startsWith('[') && !trimmed.includes('CALLER API') && !trimmed.includes('INFO') && !trimmed.includes('ERROR') && !trimmed.includes('WARN'))) {
            inApiRequestBlock = false
          } else {
            continue
          }
        }
        
        // Skip all technical API details
        if (trimmed.startsWith('URL:') || trimmed.startsWith('Action:') || trimmed.startsWith('Service:') || 
            trimmed.startsWith('[CONFIG]') || trimmed.startsWith('Params:') || trimmed.startsWith('Full URL') ||
            trimmed.startsWith('API Key:') || trimmed.startsWith('[OK] Status:') || trimmed.startsWith('Duration:') ||
            trimmed.startsWith('Response Length:') || trimmed.startsWith('Response:') && !trimmed.match(/\[(INFO|ERROR|WARN|DEBUG)\]/) ||
            trimmed.includes('Environment variables') || trimmed.includes('Updated API_KEY') || trimmed.includes('Updated BASE_URL') ||
            trimmed.includes('Updated SERVICE') || trimmed.includes('Updated OPERATOR') || trimmed.includes('Updated COUNTRY') ||
            trimmed.includes('Final caller configuration') || trimmed.includes('BASE_URL:') || trimmed.includes('SERVICE:') ||
            trimmed.includes('OPERATOR:') || trimmed.includes('COUNTRY:') || trimmed.includes('WAIT_FOR_OTP:') ||
            trimmed.includes('WAIT_FOR_SECOND_OTP:') || trimmed.includes('API_KEY:') || trimmed.includes('Signaling backend') ||
            trimmed.includes('Backend stop response') || trimmed.includes('NUMBER_QUEUE') || trimmed.includes('Enqueued') ||
            trimmed.includes('TIMEOUT] Signaling') || trimmed.includes('TIMEOUT] Backend stop')) {
          continue
        }
        
        // Transform user-friendly messages
        let friendlyMessage = null
        
        // Starting batch
        if (trimmed.includes('Starting new batch')) {
          friendlyMessage = '[INFO] Starting account creation...'
        }
        // Launching browser
        else if (trimmed.includes('[DEBUG] Launching browser')) {
          friendlyMessage = '[INFO] Opening browser...'
        }
        // Generated email
        else if (trimmed.includes('Generated Flipkart email:')) {
          const emailMatch = trimmed.match(/Generated Flipkart email: (.+)/)
          if (emailMatch) {
            friendlyMessage = `[INFO] Generated email: ${emailMatch[1]}`
          }
        }
        // Fetching number
        else if (trimmed.includes('[DEBUG] Fetching number from API') || trimmed.includes('Fetching number from API')) {
          if (!lastWasRequestingNumber) {
            friendlyMessage = '[INFO] Requesting phone number...'
            lastWasRequestingNumber = true
          } else {
            continue
          }
        }
        // Got number
        else if (trimmed.includes('[DEBUG] [OK] Got number:') || trimmed.includes('Got number:')) {
          const phoneMatch = trimmed.match(/phone=(\d+)/) || trimmed.match(/phone:(\d+)/)
          if (phoneMatch) {
            friendlyMessage = `[INFO] Phone number received: ${phoneMatch[1]}`
          } else {
            friendlyMessage = '[INFO] Phone number received'
          }
          lastWasRequestingNumber = false
        }
        // Navigating to signup
        else if (trimmed.includes('Navigating to Flipkart signup page')) {
          friendlyMessage = '[INFO] Opening signup page...'
        }
        // Page loaded
        else if (trimmed.includes('[DEBUG] [OK] Page loaded')) {
          friendlyMessage = '[INFO] Page loaded'
        }
        // Filling phone number
        else if (trimmed.includes('Filling phone number:') || trimmed.includes('[DEBUG] [OK] Phone number filled')) {
          const phoneMatch = trimmed.match(/Filling phone number: (\d+)/)
          if (phoneMatch) {
            friendlyMessage = `[INFO] Entering phone number: ${phoneMatch[1]}`
          } else if (trimmed.includes('[OK] Phone number filled')) {
            friendlyMessage = '[INFO] Phone number entered'
          }
        }
        // Waiting for OTP / OTP received
        else if (trimmed.includes('getStatus') || trimmed.includes('get_otp') || trimmed.includes('STATUS_WAIT_CODE') ||
                 trimmed.includes('Polling for OTP') || trimmed.includes('Fetching OTP')) {
          if (!lastWasWaitingForOtp) {
            friendlyMessage = '[INFO] Waiting for OTP...'
            lastWasWaitingForOtp = true
          } else {
            continue
          }
        }
        // Got OTP
        else if (trimmed.includes('[DEBUG] [OK] Got OTP:') || trimmed.includes('Got OTP:')) {
          const otpMatch = trimmed.match(/Got OTP: (\d+)/)
          if (otpMatch) {
            friendlyMessage = `[INFO] OTP received: ${otpMatch[1]}`
          } else {
            friendlyMessage = '[INFO] OTP received'
          }
          lastWasWaitingForOtp = false
        }
        // OTP timeout
        else if (trimmed.includes('OTP timeout') || trimmed.includes('TIMEOUT]')) {
          friendlyMessage = '[ERROR] OTP timeout - account creation stopped'
          lastWasWaitingForOtp = false
        }
        // Number canceled
        else if (trimmed.includes('canceled') || trimmed.includes('ACCESS_CANCEL')) {
          friendlyMessage = '[INFO] Number canceled'
        }
        // Already registered
        else if (trimmed.includes('already registered') || trimmed.includes('AlreadyRegisteredError')) {
          friendlyMessage = '[WARN] Phone number already registered'
        }
        // Login successful / account created
        else if (trimmed.includes('Recovery completed') || trimmed.includes('completed! Closing browser') || 
                 trimmed.includes('Account created successfully') || trimmed.includes('Login successful')) {
          friendlyMessage = '[INFO] Account created successfully!'
        }
        // Error messages
        else if (trimmed.includes('[ERROR]') || trimmed.includes('Exception occurred')) {
          // Skip technical error details, show simplified messages
          if (trimmed.includes('Failed to get number')) {
            friendlyMessage = '[ERROR] Failed to get phone number'
          } else if (trimmed.includes('Failed to retrieve OTP')) {
            friendlyMessage = '[ERROR] OTP not received'
          } else if (trimmed.includes('OTP is incorrect')) {
            friendlyMessage = '[ERROR] Invalid OTP'
          } else if (trimmed.includes('Number was canceled')) {
            friendlyMessage = '[INFO] Number was canceled'
          } else if (trimmed.includes('timeout')) {
            friendlyMessage = '[ERROR] Request timeout'
          } else if (trimmed.includes('NO_NUMBERS')) {
            friendlyMessage = '[ERROR] No phone numbers available'
          } else if (trimmed.includes('All workers completed')) {
            friendlyMessage = '[INFO] All workers completed!'
          } else if (!trimmed.includes('[DEBUG]') && !trimmed.includes('Environment') && !trimmed.includes('CONFIG')) {
            // Only show non-debug errors
            friendlyMessage = trimmed
          } else {
            continue
          }
        }
        // Skip all DEBUG messages except important ones
        else if (trimmed.includes('[DEBUG]') && !trimmed.includes('[OK]')) {
          continue
        }
        // Keep INFO, WARN, ERROR messages that aren't filtered above
        else if (trimmed.match(/\[(INFO|WARN|ERROR)\]/) && !trimmed.includes('CALLER API') && 
                 !trimmed.includes('Environment') && !trimmed.includes('CONFIG')) {
          friendlyMessage = trimmed
        }
        // Skip everything else that's technical
        else {
          continue
        }
        
        if (friendlyMessage) {
          filteredLines.push(friendlyMessage)
        }
      }

      setLogs(filteredLines)



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

    // Optimize for 4 vCPU, 16GB RAM: Increase log polling interval to reduce CPU/network load
    const id = setInterval(() => {

      loadLatestLogs({ silent: true })

    }, 3000)  // Increased from 2000ms to 3000ms

    return () => clearInterval(id)

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [])



  const handleSubmit = async (e) => {

    e.preventDefault()

    if (!imapReady) {

      setShowImapPopup(true)

      return

    }

    // Set starting state immediately for visual feedback
    setStarting(true)
    setPopup({ type: null, message: '' })

    setLogs([])

    // Show skeleton loading by setting values to null, then refresh from backend
    setBalance(null)
    setCapacity(null)
    setMarginBalance(null)
    setPrice(null)

    // Auto-hide loading overlay after 4 seconds regardless of API call status
    const loadingTimeout = setTimeout(() => {
      setStarting(false)
      console.log('[DEBUG] [Launcher] Loading overlay auto-hidden after 4 seconds')
    }, 4000)

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

      // Add timeout to prevent hanging (30 seconds should be enough for backend processing)
      const response = await axios.post('/api/run', formData, {

        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },

        withCredentials: true,

        timeout: 30000,  // 30 second timeout

      })
      console.log('[DEBUG] [Launcher] POST /api/run response:', response.data)

      // Clear the auto-hide timeout since we got a response
      clearTimeout(loadingTimeout)

      // Play start sound
      playStartSound()

      setRunning(true)
      
      // Refresh balance, price, capacity, and margin balance from backend
      // This will update the displayed values and hide skeleton loading
      console.log('[DEBUG] [Launcher] Refreshing balance and margin balance after start')
      await Promise.all([
        loadBalance(),
        loadMarginBalance()
      ])
      
      // Clear starting state after successful API call and data refresh
      setStarting(false)
      
      setTimeout(() => {
        loadLatestLogs({ silent: true })
      }, 500)

    } catch (error) {
      console.error('[DEBUG] [Launcher] Error in handleSubmit:', error)
      console.error('[DEBUG] [Launcher] Error response:', error.response?.data)
      console.error('[DEBUG] [Launcher] Error status:', error.response?.status)
      console.error('[DEBUG] [Launcher] Error code:', error.code)
      console.error('[DEBUG] [Launcher] Error message:', error.message)

      // Clear the auto-hide timeout since we got an error
      clearTimeout(loadingTimeout)

      // Clear starting state on error (before showing error popup)
      setStarting(false)

      // Reload balance and margin balance to restore correct values on error
      await Promise.all([
        loadBalance(),
        loadMarginBalance()
      ])

      let msg = 'Failed to start account creation'
      
      if (error.code === 'ECONNABORTED') {
        msg = 'Request timed out after 30 seconds. The backend may be slow or unresponsive. Please check the backend logs and try again.'
      } else if (error.response?.data?.error) {
        msg = error.response.data.error
      } else if (error.message) {
        msg = `Error: ${error.message}`
      } else if (!error.response) {
        msg = 'Network error: Could not connect to backend. Please ensure the backend server is running.'
      }

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

      {starting && (
        <div className="loading-overlay">
          <div className="loading-content">
            <div className="loading-spinner-large"></div>
            <p className="loading-text">Starting account creation...</p>
            <div className="loading-progress-bar">
              <div className="loading-progress-fill"></div>
            </div>
          </div>
        </div>
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

              Balance: ₹{balance !== null && balance !== undefined ? balance.toFixed(2) : 'N/A'}

            </span>

            <span className="info-pill">

              Price: ₹{price !== null && price !== undefined ? price.toFixed(2) : 'N/A'}

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

            disabled={running || starting || !imapReady}

          />

        </div>

        <div className="form-group toggle-group">
          <label htmlFor="use_used_account" className="toggle-label">
            <input
              id="use_used_account"
              type="checkbox"
              className="toggle-input"
              checked={useUsedAccount}
              onChange={(e) => {
                const newValue = e.target.checked
                // Show warning when disabling "No New Accounts" mode
                if (!newValue && useUsedAccount) {
                  setShowNewAccountsWarning(true)
                } else {
                  setUseUsedAccount(newValue)
                }
              }}
              disabled={running || starting || !imapReady}
            />
            <span className="toggle-slider"></span>
            <span className="toggle-text">No New Accounts</span>
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
              disabled={running || starting || !imapReady}
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

            disabled={running || starting || !imapReady}

          />

        </div>

        <button 
          type="submit" 
          disabled={running || starting || loading || capacity === null || marginBalance === null} 
          className={running || starting ? 'running' : ''}
        >

          {starting ? (

            <>

              <span className="spinner"></span>

              Starting...

            </>

          ) : running ? (

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



      {showNewAccountsWarning && (
        <div className="popup-overlay" onClick={() => setShowNewAccountsWarning(false)}>
          <div className="popup" onClick={(e) => e.stopPropagation()}>
            <h3>⚠️ Warning: Disabling No New Accounts Mode</h3>
            <p>
              Disabling "No New Accounts" mode will attempt to create accounts even if the phone number is already registered (recovery mode).
              This may result in additional balance deductions if the account creation process continues with recovery flow.
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
                  setUseUsedAccount(false)
                  setShowNewAccountsWarning(false)
                }}
                style={{ background: '#c62828', color: 'white' }}
              >
                Disable Anyway
              </button>
              <button
                type="button"
                onClick={() => setShowNewAccountsWarning(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      {showBalancePopup && (

        <div className="popup-overlay">

          <div className="popup">

            <h3>Insufficient Balance</h3>

            <p>

              To create {totalAccounts} account(s), please add at least ₹

              {amountNeeded != null && amountNeeded !== undefined ? amountNeeded.toFixed(2) : '0.00'} to your SMS balance.

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

              Please enter your IMAP email, password, and API key in the IMAP

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

