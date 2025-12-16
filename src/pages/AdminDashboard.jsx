import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Skeleton, SkeletonTable } from '../components/Skeleton'
import './AdminDashboard.css'

export default function AdminDashboard() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadUsers()
  }, [])

  const loadUsers = async () => {
    try {
      const response = await axios.get('/api/admin/users', { withCredentials: true })
      setUsers(response.data.users || [])
    } catch (error) {
      console.error('Error loading users:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="admin-dashboard-page">
        <h2>Dashboard</h2>
        <div className="info-pills">
          <Skeleton height="36px" width="150px" />
        </div>
        <SkeletonTable rows={5} cols={3} />
      </div>
    )
  }

  return (
    <div className="admin-dashboard-page">
      <h2>Dashboard</h2>
      <div className="info-pills">
        <span className="info-pill">Total Users: {users.length}</span>
      </div>
      <h3 style={{ marginTop: '30px' }}>Users</h3>
      <table>
        <thead>
          <tr>
            <th>Username</th>
            <th>Role</th>
            <th>Expiry Date</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td>{user.username}</td>
              <td>{user.role}</td>
              <td>{user.expiry_date || 'Never'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
