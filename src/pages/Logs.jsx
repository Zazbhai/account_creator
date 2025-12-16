import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useSocket } from '../hooks/useSocket'
import { useAuth } from '../hooks/useAuth'
import { Skeleton } from '../components/Skeleton'
import './Logs.css'

export default function Logs() {
  const { user } = useAuth()
  const { socket } = useSocket(user?.id)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadLogs()
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

      socket.on('log', handleLog)

      return () => {
        socket.off('log', handleLog)
      }
    }
  }, [socket])

  const loadLogs = async () => {
    try {
      const response = await axios.get('/api/logs', { withCredentials: true })
      setLogs(response.data.logs || [])
    } catch (error) {
      console.error('Error loading logs:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="logs-page">
        <h2>Logs</h2>
        <Skeleton height="400px" />
      </div>
    )
  }

  return (
    <div className="logs-page">
      <h2>Logs</h2>
      <div className="log-container">
        {logs.length === 0 ? (
          <div className="log-line">No logs available.</div>
        ) : (
          logs.map((line, index) => (
            <div key={index} className="log-line">
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
