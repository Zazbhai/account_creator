import React from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Launcher from './pages/Launcher'
import IMAPSettings from './pages/IMAPSettings'
import Reports from './pages/Reports'
import Logs from './pages/Logs'
import AddFunds from './pages/AddFunds'
import AdminDashboard from './pages/AdminDashboard'
import AdminUsers from './pages/AdminUsers'
import AdminApi from './pages/AdminApi'
import Layout from './components/Layout'
import GlobalLoader from './components/GlobalLoader'
import { useAuth } from './hooks/useAuth'
import './App.css'

function App() {
  const { isAuthenticated, isLoading, user } = useAuth()

  if (isLoading) {
    return <div className="app-loader">Loading...</div>
  }

  const isAdmin = user?.role === 'admin'

  return (
    <Router>
      <GlobalLoader />
      <Routes>
        <Route path="/login" element={!isAuthenticated ? <Login /> : <Navigate to={isAdmin ? "/admin/dashboard" : "/"} />} />
        <Route path="/" element={isAuthenticated ? (isAdmin ? <Navigate to="/admin/dashboard" /> : <Layout><Launcher /></Layout>) : <Navigate to="/login" />} />
        <Route path="/imap" element={isAuthenticated ? (isAdmin ? <Navigate to="/admin/dashboard" /> : <Layout><IMAPSettings /></Layout>) : <Navigate to="/login" />} />
        <Route path="/reports" element={isAuthenticated ? (isAdmin ? <Navigate to="/admin/dashboard" /> : <Layout><Reports /></Layout>) : <Navigate to="/login" />} />
        <Route path="/logs" element={isAuthenticated ? (isAdmin ? <Navigate to="/admin/dashboard" /> : <Layout><Logs /></Layout>) : <Navigate to="/login" />} />
        <Route path="/funds" element={isAuthenticated ? (isAdmin ? <Navigate to="/admin/dashboard" /> : <Layout><AddFunds /></Layout>) : <Navigate to="/login" />} />
        <Route path="/admin/dashboard" element={isAuthenticated ? (isAdmin ? <Layout><AdminDashboard /></Layout> : <Navigate to="/" />) : <Navigate to="/login" />} />
        <Route path="/admin/api" element={isAuthenticated ? (isAdmin ? <Layout><AdminApi /></Layout> : <Navigate to="/" />) : <Navigate to="/login" />} />
        <Route path="/admin/users" element={isAuthenticated ? (isAdmin ? <Layout><AdminUsers /></Layout> : <Navigate to="/" />) : <Navigate to="/login" />} />
      </Routes>
    </Router>
  )
}

export default App
