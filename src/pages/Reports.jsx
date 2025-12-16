import React from 'react'
import { Skeleton } from '../components/Skeleton'
import './Reports.css'

export default function Reports() {
  return (
    <div className="reports-page">
      <h2>Reports</h2>
      <Skeleton height="200px" />
      <p style={{ marginTop: '20px', color: '#666' }}>
        Reports functionality coming soon.
      </p>
    </div>
  )
}
