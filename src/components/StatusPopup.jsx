import React, { useEffect } from 'react'
import './StatusPopup.css'

export default function StatusPopup({ type = 'success', message, onClose, autoCloseMs = 1800 }) {
  useEffect(() => {
    if (!autoCloseMs) return
    const id = setTimeout(() => {
      onClose?.()
    }, autoCloseMs)
    return () => clearTimeout(id)
  }, [autoCloseMs, onClose])

  if (!message) return null

  const isSuccess = type === 'success'

  return (
    <div className="status-popup-overlay">
      <div className="status-popup">
        <div className={`status-icon ${isSuccess ? 'success' : 'error'}`}>
          <span className="status-icon-mark" />
        </div>
        <div className="status-message">{message}</div>
        <button
          type="button"
          className="status-close-btn"
          onClick={() => onClose?.()}
        >
          OK
        </button>
      </div>
    </div>
  )
}

