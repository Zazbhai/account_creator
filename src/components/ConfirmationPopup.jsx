import React from 'react'
import { createPortal } from 'react-dom'
import './ConfirmationPopup.css'

export default function ConfirmationPopup({
  message,
  onConfirm,
  onCancel,
  confirmText = 'Agree',
  cancelText = 'Deny',
  type = 'warning'
}) {
  if (!message) return null

  const popupContent = (
    <div className="confirmation-popup-overlay" onClick={onCancel || onConfirm}>
      <div className={`confirmation-popup confirmation-popup--${type}`} onClick={(e) => e.stopPropagation()}>
        <div className="confirmation-icon">
          {type === 'warning' && (
            <svg
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M12 9V13M12 17H12.01M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z"
                stroke="#F59E0B"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>
        <div className="confirmation-message" style={{ whiteSpace: typeof message === 'string' ? 'pre-line' : 'normal' }}>
          {message}
        </div>
        <div className="confirmation-buttons">
          {onCancel && (
            <button
              type="button"
              className="confirmation-btn confirmation-btn--cancel"
              onClick={onCancel}
            >
              {cancelText}
            </button>
          )}
          <button
            type="button"
            className="confirmation-btn confirmation-btn--confirm"
            onClick={onConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )

  // Render using portal to document body to ensure it's above everything
  if (typeof document !== 'undefined' && document.body) {
    return createPortal(popupContent, document.body)
  }
  return popupContent
}


