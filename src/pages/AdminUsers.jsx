import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { Skeleton, SkeletonTable } from '../components/Skeleton'
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
  const [message, setMessage] = useState('')

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
    setMessage('')

    try {
      await axios.post('/api/admin/users', formData, { withCredentials: true })
      setMessage('User created successfully')
      setFormData({ username: '', password: '', role: 'user', expiry_days: '' })
      loadUsers()
    } catch (error) {
      setMessage(error.response?.data?.error || 'Failed to create user')
    }
  }

  const handleDelete = async (userId) => {
    if (!window.confirm('Are you sure you want to delete this user?')) return

    try {
      await axios.delete(`/api/admin/users/${userId}`, { withCredentials: true })
      setMessage('User deleted successfully')
      loadUsers()
    } catch (error) {
      setMessage(error.response?.data?.error || 'Failed to delete user')
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
      {message && (
        <div className={message.includes('success') ? 'success' : 'error'}>
          {message}
        </div>
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
                <button
                  onClick={() => handleDelete(user.id)}
                  className="delete-button"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
