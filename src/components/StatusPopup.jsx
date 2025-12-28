import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
import './StatusPopup.css'

export default function StatusPopup({
  type = 'success',
  message,
  onClose,
  autoCloseMs = 4000
}) {
  useEffect(() => {
    if (!autoCloseMs) return
    const id = setTimeout(() => {
      onClose?.()
    }, autoCloseMs)
    return () => clearTimeout(id)
  }, [autoCloseMs, onClose])

  if (!message) return null

  const isSuccess = type === 'success'

  // Use portal to render at document root to avoid z-index issues
  const popupContent = (
    <div className="status-popup-overlay">
      <div className={`status-popup ${isSuccess ? 'status-popup--success' : 'status-popup--error'}`}>
        <button
          type="button"
          className="status-popup-close"
          onClick={() => onClose?.()}
          aria-label="Close"
        >
          ×
        </button>

        <div className="status-icon">
          {isSuccess ? (
            <div className="ui-success">
              <svg
                viewBox="0 0 87 87"
                xmlns="http://www.w3.org/2000/svg"
                xmlnsXlink="http://www.w3.org/1999/xlink"
              >
                <g stroke="none" strokeWidth="1" fill="none" fillRule="evenodd">
                  <g transform="translate(2, 2)">
                    <circle
                      stroke="rgba(165, 220, 134, 0.2)"
                      strokeWidth="4"
                      cx="41.5"
                      cy="41.5"
                      r="41.5"
                    />
                    <circle
                      className="ui-success-circle"
                      stroke="#A5DC86"
                      strokeWidth="4"
                      cx="41.5"
                      cy="41.5"
                      r="41.5"
                    />
                    <polyline
                      className="ui-success-path"
                      stroke="#A5DC86"
                      strokeWidth="4"
                      points="19 38.8036813 31.1020744 54.8046875 63.299221 28"
                    />
                  </g>
                </g>
              </svg>
            </div>
          ) : (
            <div className="ui-error">
              <svg
                viewBox="0 0 87 87"
                xmlns="http://www.w3.org/2000/svg"
                xmlnsXlink="http://www.w3.org/1999/xlink"
              >
                <g stroke="none" strokeWidth="1" fill="none" fillRule="evenodd">
                  <g transform="translate(2, 2)">
                    <circle
                      stroke="rgba(252, 191, 191, 0.5)"
                      strokeWidth="4"
                      cx="41.5"
                      cy="41.5"
                      r="41.5"
                    />
                    <circle
                      className="ui-error-circle"
                      stroke="#F74444"
                      strokeWidth="4"
                      cx="41.5"
                      cy="41.5"
                      r="41.5"
                    />
                    <path
                      className="ui-error-line1"
                      d="M22.244224,22 L60.4279902,60.1837662"
                      stroke="#F74444"
                      strokeWidth="3"
                      strokeLinecap="square"
                    />
                    <path
                      className="ui-error-line2"
                      d="M60.755776,21 L23.244224,59.8443492"
                      stroke="#F74444"
                      strokeWidth="3"
                      strokeLinecap="square"
                    />
                  </g>
                </g>
              </svg>
            </div>
          )}
        </div>

        <div className="status-message" style={{ whiteSpace: 'pre-line' }}>{message}</div>
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

  // Render using portal to document body to ensure it's above everything
  // Fallback to regular render if portal is not available (SSR)
  if (typeof document !== 'undefined' && document.body) {
    return createPortal(popupContent, document.body)
  }
  return popupContent
}
