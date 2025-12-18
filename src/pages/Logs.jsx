import React, { useState, useEffect } from 'react'

import axios from 'axios'

import { Skeleton } from '../components/Skeleton'

import './Logs.css'



export default function Logs() {

  const [logFiles, setLogFiles] = useState([])

  const [selectedLog, setSelectedLog] = useState('')

  const [logContent, setLogContent] = useState('')

  const [loading, setLoading] = useState(true)

  const [error, setError] = useState('')



  const loadLogFile = async (name, { silent = false } = {}) => {

    if (!name) return

    if (!silent) setError('')

    try {

      const res = await axios.get('/api/reports/log-file', {

        params: { name },

        withCredentials: true,

        skipLoader: true,

      })

      setLogContent(res.data.content || '')

    } catch (err) {

      console.error('Error loading log file:', err)

      if (!silent) {

        setError(err.response?.data?.error || 'Failed to load log file.')

      }

    }

  }



  const loadLogFiles = async () => {

    setError('')

    try {

      const res = await axios.get('/api/reports/log-files', {

        withCredentials: true,

        skipLoader: true,

      })

      const files = res.data.files || []

      setLogFiles(files)

      if (files.length > 0) {

        const firstName = files[0].name

        setSelectedLog(firstName)

        await loadLogFile(firstName)

      } else {

        setSelectedLog('')

        setLogContent('')

      }

    } catch (err) {

      console.error('Error loading log files:', err)

      setError(err.response?.data?.error || 'Failed to load log files.')

    } finally {

      setLoading(false)

    }

  }



  useEffect(() => {

    loadLogFiles()

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [])



  // Auto-refresh currently selected log file every 2s

  useEffect(() => {

    if (!selectedLog) return

    const id = setInterval(() => {

      loadLogFile(selectedLog, { silent: true })

    }, 2000)

    return () => clearInterval(id)

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [selectedLog])



  const downloadSelectedLogFile = () => {

    if (!selectedLog) return

    const url = `/api/reports/log-file?name=${encodeURIComponent(selectedLog)}&download=1`

    window.open(url, '_blank')

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



      {error && <div className="error">{error}</div>}



      <div className="log-files-card">

        <div className="log-files-header">

          <h3>Log files</h3>

          <div className="log-files-actions">

            <button type="button" onClick={loadLogFiles}>

              Refresh list

            </button>

            <button type="button" onClick={downloadSelectedLogFile} disabled={!selectedLog}>

              Download

            </button>

          </div>

        </div>

        <div className="log-files-body">

          {logFiles.length === 0 ? (

            <div className="log-line">No log files found.</div>

          ) : (

            <>

              <select

                className="log-select"

                value={selectedLog}

                onChange={(e) => {

                  const name = e.target.value

                  setSelectedLog(name)

                  loadLogFile(name)

                }}

              >

                {logFiles.map((file) => (

                  <option key={file.name} value={file.name}>

                    {file.name} ({file.size} bytes)

                  </option>

                ))}

              </select>

              <pre className="log-file-view">

                {logContent || 'No content for this log file.'}

              </pre>

            </>

          )}

        </div>

      </div>

    </div>

  )

}

