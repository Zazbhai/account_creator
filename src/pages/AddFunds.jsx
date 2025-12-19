import React, { useEffect, useState } from 'react'
import axios from 'axios'
import { Skeleton } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'
import './AddFunds.css'

export default function AddFunds() {
  const [currentBalance, setCurrentBalance] = useState(null)
  const [marginFee, setMarginFee] = useState(null)
  const [amount, setAmount] = useState('')
  const [utr, setUtr] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [popup, setPopup] = useState({ type: null, message: '' })
  const [showPlanner, setShowPlanner] = useState(true)
  const [plannerAmount, setPlannerAmount] = useState('')
  const [plannerAccounts, setPlannerAccounts] = useState('')
  const [payAnimating, setPayAnimating] = useState(false)
  const [showUtrPopup, setShowUtrPopup] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const [fundsRes, marginRes] = await Promise.all([
          axios.get('/api/funds', { withCredentials: true }),
          axios.get('/api/margin-fees', { withCredentials: true, skipLoader: true }),
        ])
        setCurrentBalance(fundsRes.data.balance ?? 0)
        if (typeof marginRes.data.per_account_fee === 'number') {
          setMarginFee(marginRes.data.per_account_fee)
        } else {
          setMarginFee(2.5)
        }
      } catch (err) {
        console.error('Error loading add-funds data:', err)
        setPopup({
          type: 'error',
          message: err.response?.data?.error || 'Failed to load balance information',
        })
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [])

  const effectiveMargin = marginFee && marginFee > 0 ? marginFee : 2.5
  const parsedAmount = parseFloat(amount || '0') || 0
  const accountsPossible =
    parsedAmount > 0 && effectiveMargin > 0
      ? Math.floor(parsedAmount / effectiveMargin)
      : 0

  const plannerAmountNum = parseFloat(plannerAmount || '0') || 0
  const plannerAccountsNum = parseInt(plannerAccounts || '0', 10) || 0
  const plannerValid =
    plannerAmountNum > 0 && plannerAccountsNum > 0 && effectiveMargin > 0

  const handlePlannerAmountChange = (e) => {
    const val = e.target.value
    setPlannerAmount(val)
    const num = parseFloat(val || '0') || 0
    if (num > 0 && effectiveMargin > 0) {
      setPlannerAccounts(Math.floor(num / effectiveMargin).toString())
    } else {
      setPlannerAccounts('')
    }
  }

  const handlePlannerAccountsChange = (e) => {
    const val = e.target.value
    setPlannerAccounts(val)
    const num = parseInt(val || '0', 10) || 0
    if (num > 0 && effectiveMargin > 0) {
      setPlannerAmount((num * effectiveMargin).toFixed(2))
    } else {
      setPlannerAmount('')
    }
  }

  const handlePlannerContinue = () => {
    if (!plannerValid) {
      return
    }
    setAmount(plannerAmount)
    setShowPlanner(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (!parsedAmount || parsedAmount <= 0) {
      setPopup({ type: 'error', message: 'Enter a valid amount to add.' })
      return
    }

    if (!utr.trim()) {
      setPopup({ type: 'error', message: 'Enter the UTR / RRN number.' })
      return
    }

    setSubmitting(true)
    try {
      const res = await axios.post(
        '/api/funds/add',
        { amount: parsedAmount, utr: utr.trim() },
        { withCredentials: true }
      )
      const newBal = res.data.wallet_balance ?? currentBalance ?? 0
      setCurrentBalance(newBal)
      setAmount('')
      setUtr('')
      setPopup({
        type: 'success',
        message: `₹${(res.data.credited ?? parsedAmount).toFixed(2)} added to your balance.`,
      })
    } catch (err) {
      console.error('Error adding funds:', err)
      setPopup({
        type: 'error',
        message: err.response?.data?.error || 'Failed to verify payment / add funds.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  const upiText = `upi://pay?pa=BHARATPE.8S0O1D0J6I92795@fbpe&pn=BharatPe%20Merchant&am=${
    parsedAmount > 0 ? parsedAmount.toString() : ''
  }&cu=INR&tn=Pay%20To%20BharatPe%20Merchant`

  const qrSrc = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=${encodeURIComponent(
    upiText
  )}`

  const handlePayClick = () => {
    if (!parsedAmount || parsedAmount <= 0) {
      setPopup({ type: 'error', message: 'Enter a valid amount to add before paying.' })
      return
    }
    // Trigger UPI intent on supported devices
    try {
      window.location.href = upiText
    } catch (e) {
      // ignore navigation errors
    }
    setPayAnimating(true)
    setTimeout(() => {
      setPayAnimating(false)
    }, 700)
    // Show UTR popup and blur background
    setShowUtrPopup(true)
  }

  if (loading) {
    return (
      <div className="add-funds-page">
        <h2>Add Funds</h2>
        <Skeleton height="48px" width="260px" />
        <div style={{ marginTop: '24px' }}>
          <Skeleton height="220px" />
        </div>
      </div>
    )
  }

  return (
    <div className="add-funds-page">
      <h2>Add Funds</h2>

      {showUtrPopup && (
        <div className="popup-overlay">
          <div className="popup utr-popup">
            <button
              type="button"
              className="popup-close-icon"
              onClick={() => setShowUtrPopup(false)}
            >
              ✕
            </button>
            <h3>Enter UTR / RRN</h3>
            <p style={{ marginBottom: '12px', color: '#666', fontSize: '14px' }}>
              After paying with UPI, enter the bank UTR / RRN to verify your payment.
            </p>
            <div className="form-group">
              <label htmlFor="utr_popup">UTR / RRN number</label>
              <input
                id="utr_popup"
                type="text"
                value={utr}
                onChange={(e) => setUtr(e.target.value)}
                placeholder="Enter bank UTR / RRN"
                autoFocus
              />
            </div>
            <button
              type="button"
              onClick={() => setShowUtrPopup(false)}
              style={{ marginTop: '12px' }}
            >
              Done
            </button>
          </div>
        </div>
      )}

      {showPlanner && (
        <div className="popup-overlay">
          <div className="popup add-funds-planner">
            <h3>Plan your funds</h3>
            <p style={{ marginBottom: '12px', color: '#555', fontSize: '14px' }}>
              Enter how much you want to add or how many accounts you want to create.
              Current margin per account: ₹
              {effectiveMargin.toFixed(2)}.
            </p>
            <div className="planner-grid">
              <div className="form-group">
                <label htmlFor="planner_amount">Amount to add (₹)</label>
                <input
                  id="planner_amount"
                  type="number"
                  min="1"
                  step="0.01"
                  value={plannerAmount}
                  onChange={handlePlannerAmountChange}
                />
              </div>
              <div className="form-group">
                <label htmlFor="planner_accounts">Accounts to create</label>
                <input
                  id="planner_accounts"
                  type="number"
                  min="1"
                  value={plannerAccounts}
                  onChange={handlePlannerAccountsChange}
                />
              </div>
            </div>
            <button
              type="button"
              onClick={handlePlannerContinue}
              disabled={!plannerValid}
              style={{ marginTop: '12px' }}
            >
              Continue
            </button>
          </div>
        </div>
      )}

      {popup.message && (
        <StatusPopup
          type={popup.type}
          message={popup.message}
          onClose={() => setPopup({ type: null, message: '' })}
        />
      )}

      <div className={`add-funds-content ${showUtrPopup ? 'blurred' : ''}`}>
        <div className="funds-balance-card">
          <div className="funds-balance-label">Current margin fees balance</div>
          <div className="funds-balance-value">
            ₹{(currentBalance ?? 0).toFixed(2)}
          </div>
        </div>

        <div className="add-funds-grid">
          <form className="add-funds-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="amount">Amount to add (₹)</label>
            <input
              id="amount"
              type="number"
              min="1"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="Enter amount in rupees"
              disabled={submitting}
            />
          </div>

          <div className="accounts-info">
            {parsedAmount > 0 ? (
              <span>
                With this amount you can create approximately{' '}
                <strong>{accountsPossible}</strong> account(s) at ₹
                {effectiveMargin.toFixed(2)} each.
              </span>
            ) : (
              <span className="muted">
                Enter an amount to see how many accounts you can create (₹
                {effectiveMargin.toFixed(2)} per account).
              </span>
            )}
          </div>

          <div className="form-group">
            <label htmlFor="utr">UTR / RRN number</label>
            <input
              id="utr"
              type="text"
              value={utr}
              onChange={(e) => setUtr(e.target.value)}
              placeholder="Enter bank UTR / RRN after payment"
              disabled={submitting}
            />
          </div>

          <button type="submit" disabled={submitting}>
            {submitting ? 'Verifying & adding...' : 'Verify Payment & Add Funds'}
          </button>
        </form>

        {!showPlanner && (
          <div className="add-funds-qr-card">
            <h3>Pay using UPI</h3>
            <div className="qr-wrapper">
              <div className="qr-animated-border">
                <span className="qr-border-segment" />
                <span className="qr-border-segment" />
                <span className="qr-border-segment" />
                <span className="qr-border-segment" />
                <div className="qr-inner">
                  <span className="qr-corner qr-corner-tl" />
                  <span className="qr-corner qr-corner-tr" />
                  <span className="qr-corner qr-corner-bl" />
                  <span className="qr-corner qr-corner-br" />
                  <img src={qrSrc} alt="UPI QR" className="upi-qr" />
                  <button
                    type="button"
                    className="download-qr-icon"
                    onClick={() => window.open(qrSrc, '_blank')}
                    title="Download QR"
                  >
                    ⬇
                  </button>
                </div>
              </div>
            </div>
            <div className="pay-actions-container">
              <button
                type="button"
                className={`pay-mobile-btn ${payAnimating ? 'animating' : ''}`}
                onClick={handlePayClick}
              >
                <span className="pay-arrow">➜</span>
                <span className="pay-text">Pay with UPI</span>
              </button>
            </div>
            <div className="upi-text">
              <div className="upi-note">
                Scan this QR in your UPI app, pay the amount, then enter the UTR /
                RRN number above to confirm and credit your balance.
              </div>
            </div>
          </div>
        )}
        </div>
      </div>
    </div>
  )
}

