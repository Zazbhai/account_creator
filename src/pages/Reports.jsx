import React, { useEffect, useState } from 'react'

import axios from 'axios'

import { Skeleton, SkeletonTable } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'

import './Reports.css'



export default function Reports() {

  const [usedEmails, setUsedEmails] = useState([])

  const [failedNumbers, setFailedNumbers] = useState([])

  const [loading, setLoading] = useState(true)

  const [popup, setPopup] = useState({ type: null, message: '' })



  const loadReports = async ({ silent = false } = {}) => {

    if (!silent) setPopup({ type: null, message: '' })

    try {

      const [emailsRes, numbersRes] = await Promise.all([

        axios.get('/api/reports/used-emails', { withCredentials: true, skipLoader: true }),

        axios.get('/api/reports/failed-numbers', { withCredentials: true, skipLoader: true }),

      ])



      setUsedEmails(emailsRes.data.items || [])

      setFailedNumbers(numbersRes.data.items || [])

    } catch (err) {

      console.error('Error loading reports:', err)

      if (!silent) {

        setPopup({ type: 'error', message: err.response?.data?.error || 'Failed to load reports' })

      }

    } finally {

      if (!silent) {

        setLoading(false)

      }

    }

  }



  useEffect(() => {

    // Initial load

    loadReports()

    // Poll every 3 seconds to pick up changes in text files

    const id = setInterval(() => {

      loadReports({ silent: true })

    }, 3000)

    return () => clearInterval(id)

    // eslint-disable-next-line react-hooks/exhaustive-deps

  }, [])



  const downloadUsedEmails = () => {

    window.open('/api/reports/used-emails?download=1', '_blank')

  }



  const downloadFailedNumbers = () => {

    window.open('/api/reports/failed-numbers?download=1', '_blank')

  }



  if (loading) {

    return (

      <div className="reports-page">

        <h2>Reports</h2>

        <Skeleton height="36px" width="200px" />

        <div style={{ marginTop: '20px' }}>

          <SkeletonTable rows={5} cols={2} />

        </div>

      </div>

    )

  }



  return (

    <div className="reports-page">

      <h2>Reports</h2>



      {popup.message && (
        <StatusPopup
          type={popup.type}
          message={popup.message}
          onClose={() => setPopup({ type: null, message: '' })}
        />
      )}



      <div className="reports-grid">

        <div className="report-card">

          <div className="report-header">

            <h3>Used Emails</h3>

            <button type="button" onClick={downloadUsedEmails}>

              Download

            </button>

          </div>

          <div className="report-body">

            {usedEmails.length === 0 ? (

              <p className="muted">No used emails recorded yet.</p>

            ) : (

              <ul className="report-list">

                {usedEmails.map((email, idx) => (

                  <li key={`${email}-${idx}`}>{email}</li>

                ))}

              </ul>

            )}

          </div>

        </div>



        <div className="report-card">

          <div className="report-header">

            <h3>Failed Numbers</h3>

            <button type="button" onClick={downloadFailedNumbers}>

              Download

            </button>

          </div>

          <div className="report-body">

            {failedNumbers.length === 0 ? (

              <p className="muted">No failed numbers recorded yet.</p>

            ) : (

              <ul className="report-list">

                {failedNumbers.map((num, idx) => (

                  <li key={`${num}-${idx}`}>{num}</li>

                ))}

              </ul>

            )}

          </div>

        </div>

      </div>

    </div>

  )

}

