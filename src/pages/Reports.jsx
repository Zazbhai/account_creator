import React, { useEffect, useState } from 'react'

import axios from 'axios'

import { Skeleton, SkeletonTable } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'

import './Reports.css'



export default function Reports() {

  const [usedEmails, setUsedEmails] = useState([])

  const [failedNumbers, setFailedNumbers] = useState([])

  const [failedEmails, setFailedEmails] = useState([])

  const [loading, setLoading] = useState(true)

  const [popup, setPopup] = useState({ type: null, message: '' })

  const [showEditModal, setShowEditModal] = useState(false)

  const [editContent, setEditContent] = useState('')

  const [saving, setSaving] = useState(false)



  const loadReports = async ({ silent = false } = {}) => {

    if (!silent) setPopup({ type: null, message: '' })

    try {

      const [emailsRes, numbersRes, failedEmailsRes] = await Promise.all([

        axios.get('/api/reports/used-emails', { withCredentials: true, skipLoader: true }),

        axios.get('/api/reports/failed-numbers', { withCredentials: true, skipLoader: true }),

        axios.get('/api/reports/failed-emails', { withCredentials: true, skipLoader: true }),

      ])



      // Sort emails in ascending order by number (flipkart1, flipkart2, etc.)
      const sortedEmails = (emailsRes.data.items || []).sort((a, b) => {
        // Extract numbers from emails like "flipkart1@husan.shop" -> 1
        const extractNumber = (email) => {
          const match = email.match(/flipkart(\d+)/i)
          return match ? parseInt(match[1], 10) : 0
        }
        const numA = extractNumber(a)
        const numB = extractNumber(b)
        // If both have numbers, sort numerically
        if (numA > 0 && numB > 0) {
          return numA - numB
        }
        // If only one has a number, put it first
        if (numA > 0) return -1
        if (numB > 0) return 1
        // If neither has a number, sort alphabetically
        return a.localeCompare(b)
      })

      setUsedEmails(sortedEmails)

      setFailedNumbers(numbersRes.data.items || [])

      setFailedEmails(failedEmailsRes.data.items || [])

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

  const downloadFailedEmails = () => {

    window.open('/api/reports/failed-emails?download=1', '_blank')

  }

  const handleEditFailedEmails = async () => {

    try {

      const res = await axios.get('/api/reports/failed-emails', { withCredentials: true })

      setEditContent(res.data.content || '')

      setShowEditModal(true)

    } catch (err) {

      console.error('Error loading failed emails for editing:', err)

      setPopup({ type: 'error', message: err.response?.data?.error || 'Failed to load failed emails' })

    }

  }

  const handleSaveFailedEmails = async () => {

    setSaving(true)

    try {

      await axios.post('/api/reports/failed-emails', { content: editContent }, { withCredentials: true })

      setPopup({ type: 'success', message: 'Failed emails file updated successfully' })

      setShowEditModal(false)

      // Reload reports to show updated content

      loadReports({ silent: true })

    } catch (err) {

      console.error('Error saving failed emails:', err)

      setPopup({ type: 'error', message: err.response?.data?.error || 'Failed to save failed emails' })

    } finally {

      setSaving(false)

    }

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



        <div className="report-card">

          <div className="report-header">

            <h3>Failed Emails (use_first_mails.txt)</h3>

            <div style={{ display: 'flex', gap: '8px' }}>

              <button type="button" onClick={handleEditFailedEmails}>

                Edit

              </button>

              <button type="button" onClick={downloadFailedEmails}>

                Download

              </button>

            </div>

          </div>

          <div className="report-body">

            {failedEmails.length === 0 ? (

              <p className="muted">No failed emails recorded yet.</p>

            ) : (

              <ul className="report-list">

                {failedEmails.map((email, idx) => (

                  <li key={`${email}-${idx}`}>{email}</li>

                ))}

              </ul>

            )}

          </div>

        </div>

      </div>



      {showEditModal && (

        <div className="popup-overlay" style={{ zIndex: 1000 }}>

          <div className="popup" style={{ maxWidth: '600px', width: '90%' }}>

            <h3>Edit Failed Emails (use_first_mails.txt)</h3>

            <p style={{ marginBottom: '12px', fontSize: '14px', color: '#666' }}>

              Edit the content below. Each email should be on a separate line.

            </p>

            <textarea

              value={editContent}

              onChange={(e) => setEditContent(e.target.value)}

              style={{

                width: '100%',

                minHeight: '300px',

                padding: '12px',

                border: '1px solid #ddd',

                borderRadius: '4px',

                fontFamily: 'monospace',

                fontSize: '14px',

                resize: 'vertical',

              }}

              placeholder="Enter emails, one per line..."

            />

            <div style={{ marginTop: '16px', display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>

              <button

                type="button"

                onClick={() => {

                  setShowEditModal(false)

                  setEditContent('')

                }}

                style={{ background: '#c62828' }}

                disabled={saving}

              >

                Cancel

              </button>

              <button

                type="button"

                onClick={handleSaveFailedEmails}

                disabled={saving}

              >

                {saving ? 'Saving...' : 'Save'}

              </button>

            </div>

          </div>

        </div>

      )}

    </div>

  )

}

