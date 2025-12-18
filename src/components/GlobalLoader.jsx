import React, { useEffect, useState } from 'react'
import { useAxiosLoader } from '../hooks/useAxiosLoader'
import './GlobalLoader.css'

export default function GlobalLoader({ enabled = true, maxDuration = 5000 }) {
  const isLoading = useAxiosLoader()
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (!enabled) {
      setVisible(false)
      return
    }

    let timeoutId

    if (isLoading) {
      setVisible(true)
      // Auto-hide after maxDuration so it never feels "stuck"
      timeoutId = setTimeout(() => {
        setVisible(false)
      }, maxDuration)
    } else {
      setVisible(false)
    }

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  }, [isLoading, enabled, maxDuration])

  if (!visible) return null

  return (
    <div className="global-loader-overlay">
      <div className="global-loader-spinner">
        <div className="global-loader-circle" />
      </div>
    </div>
  )
}

