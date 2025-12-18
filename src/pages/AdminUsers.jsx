import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Skeleton, SkeletonTable } from '../components/Skeleton'
import StatusPopup from '../components/StatusPopup'
import './AdminUsers.css'

export default function AdminUsers() {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [formData, setFormData] = useState({
    username: '',
    password: '',
    role: 'user',
    expiry_days: ''
  })
  const [popup, setPopup] = useState({ type: null, message: '' })

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

  const handleSubmit = async (e) => {
    e.preventDefault()
    setPopup({ type: null, message: '' })

    try {
      await axios.post('/api/admin/users', formData, { withCredentials: true })
      setPopup({ type: 'success', message: 'User created successfully' })
      setFormData({ username: '', password: '', role: 'user', expiry_days: '' })
      loadUsers()
    } catch (error) {
      setPopup({
        type: 'error',
        message: error.response?.data?.error || 'Failed to create user',
      })
    }
  }

  const handleDelete = async (userId) => {
    if (!window.confirm('Are you sure you want to delete this user?')) return

    try {
      await axios.delete(`/api/admin/users/${userId}`, { withCredentials: true })
      setPopup({ type: 'success', message: 'User deleted successfully' })
      loadUsers()
    } catch (error) {
      setPopup({
        type: 'error',
        message: error.response?.data?.error || 'Failed to delete user',
      })
    }
  }

  const changeExpiry = async (userId, deltaDays) => {
    try {
      const res = await axios.patch(
        `/api/admin/users/${userId}/expiry`,
        { delta_days: deltaDays },
        { withCredentials: true }
      )
      setPopup({
        type: 'success',
        message: `Expiry updated to ${res.data.expiry_date || 'Never'}`,
      })
      loadUsers()
    } catch (error) {
      setPopup({
        type: 'error',
        message: error.response?.data?.error || 'Failed to update expiry',
      })
    }
  }

  if (loading) {
    return (
      <div className="admin-users-page">
        <h2>User Management</h2>
        <Skeleton height="300px" />
        <SkeletonTable rows={5} cols={5} />
      </div>
    )
  }

  return (
    <div className="admin-users-page">
      <h2>User Management</h2>
      {popup.message && (
        <StatusPopup
          type={popup.type}
          message={popup.message}
          onClose={() => setPopup({ type: null, message: '' })}
        />
      )}
      <h3>Add New User</h3>
      <form onSubmit={handleSubmit} className="user-form">
        <div className="form-group">
          <label>Username:</label>
          <input
            type="text"
            value={formData.username}
            onChange={(e) => setFormData({ ...formData, username: e.target.value })}
            required
          />
        </div>
        <div className="form-group">
          <label>Password:</label>
          <input
            type="password"
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
            required
          />
        </div>
        <div className="form-group">
          <label>Role:</label>
          <select
            value={formData.role}
            onChange={(e) => setFormData({ ...formData, role: e.target.value })}
          >
            <option value="user">User</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div className="form-group">
          <label>Expiry Days (optional):</label>
          <input
            type="number"
            value={formData.expiry_days}
            onChange={(e) => setFormData({ ...formData, expiry_days: e.target.value })}
            min="1"
          />
        </div>
        <button type="submit">Create User</button>
      </form>
      <h3 style={{ marginTop: '30px' }}>Existing Users</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Role</th>
            <th>Expiry Date</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id}>
              <td>{user.id}</td>
              <td>{user.username}</td>
              <td>{user.role}</td>
              <td>{user.expiry_date || 'Never'}</td>
              <td>
                <div className="actions-cell">
                  <div className="expiry-controls">
                    <button
                      type="button"
                      className="expiry-btn"
                      onClick={() => changeExpiry(user.id, 1)}
                    >
                      +1 day
                    </button>
                    <button
                      type="button"
                      className="expiry-btn"
                      onClick={() => changeExpiry(user.id, -1)}
                    >
                      -1 day
                    </button>
                  </div>
                  <button
                    onClick={() => handleDelete(user.id)}
                    className="delete-button"
                    type="button"
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
