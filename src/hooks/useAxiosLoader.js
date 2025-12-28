import { useEffect, useState } from 'react'
import axios from 'axios'

// Global state shared across all hook usages
let activeRequests = 0
let subscribers = []
let initialized = false
let requestCounter = 0

function notifySubscribers() {
  subscribers.forEach((fn) => {
    try {
      fn(activeRequests)
    } catch (e) {
      // ignore subscriber errors
    }
  })
}

function formatHeaders(headers) {
  // Filter out sensitive headers for logging
  const sensitiveHeaders = ['authorization', 'cookie', 'x-api-key']
  const filtered = {}
  Object.keys(headers).forEach(key => {
    const lowerKey = key.toLowerCase()
    if (sensitiveHeaders.some(sh => lowerKey.includes(sh))) {
      filtered[key] = '***REDACTED***'
    } else {
      filtered[key] = headers[key]
    }
  })
  return filtered
}

function initInterceptors() {
  if (initialized) return
  initialized = true

  axios.interceptors.request.use(
    (config) => {
      // Generate unique request ID
      const requestId = ++requestCounter
      const timestamp = new Date().toISOString()
      config.metadata = { requestId, startTime: Date.now() }

      // Log request details
      console.group(`🚀 [API REQUEST #${requestId}] ${config.method?.toUpperCase() || 'GET'} ${config.url || config.baseURL}`)
      console.log('📅 Timestamp:', timestamp)
      console.log('🔗 Full URL:', config.url || `${config.baseURL}${config.url}`)
      console.log('📤 Headers:', formatHeaders(config.headers || {}))
      
      // Log request data (if present)
      if (config.data) {
        if (config.data instanceof FormData || config.data instanceof URLSearchParams) {
          console.log('📦 Data:', config.data.toString().substring(0, 200) + (config.data.toString().length > 200 ? '...' : ''))
        } else {
          console.log('📦 Data:', typeof config.data === 'string' ? config.data.substring(0, 200) : config.data)
        }
      }
      
      if (config.params) {
        console.log('🔍 Query Params:', config.params)
      }
      
      console.log('⚙️ Config:', {
        timeout: config.timeout,
        withCredentials: config.withCredentials,
        skipLoader: config.skipLoader
      })
      console.groupEnd()

      // Opt-out flag: skip global loader for this request
      if (!config.skipLoader) {
        activeRequests += 1
        notifySubscribers()
      }
      return config
    },
    (error) => {
      const requestId = error.config?.metadata?.requestId || 'unknown'
      console.error(`❌ [API REQUEST ERROR #${requestId}]`, error.message)
      console.error('Error details:', error)
      activeRequests = Math.max(0, activeRequests - 1)
      notifySubscribers()
      return Promise.reject(error)
    }
  )

  axios.interceptors.response.use(
    (response) => {
      const cfg = response.config || {}
      const metadata = cfg.metadata || {}
      const requestId = metadata.requestId || 'unknown'
      const duration = metadata.startTime ? Date.now() - metadata.startTime : 0
      const timestamp = new Date().toISOString()

      // Log response details
      console.group(`✅ [API RESPONSE #${requestId}] ${cfg.method?.toUpperCase() || 'GET'} ${cfg.url || cfg.baseURL}`)
      console.log('📅 Timestamp:', timestamp)
      console.log('⏱️ Duration:', `${duration}ms`)
      console.log('📊 Status:', `${response.status} ${response.statusText}`)
      console.log('📥 Response Headers:', formatHeaders(response.headers || {}))
      
      // Log response data (truncate if too large)
      // Handle different response types safely
      try {
        if (typeof response.data === 'string') {
          // For text responses (like log files), show truncated preview
          if (response.data.length > 500) {
            console.log('📦 Response Data (text):', response.data.substring(0, 500) + '...')
            console.log('📏 Data Size:', `${(response.data.length / 1024).toFixed(2)} KB`)
          } else {
            console.log('📦 Response Data (text):', response.data)
          }
        } else {
          // For JSON responses
          const dataStr = JSON.stringify(response.data)
          if (dataStr.length > 500) {
            console.log('📦 Response Data:', JSON.parse(dataStr.substring(0, 500) + '..."'))
            console.log('📏 Data Size:', `${(dataStr.length / 1024).toFixed(2)} KB`)
          } else {
            console.log('📦 Response Data:', response.data)
          }
        }
      } catch (e) {
        // Fallback if JSON.stringify fails
        console.log('📦 Response Data (raw):', response.data)
      }
      console.groupEnd()

      if (!cfg.skipLoader) {
        activeRequests = Math.max(0, activeRequests - 1)
        notifySubscribers()
      }
      return response
    },
    (error) => {
      const cfg = error.config || {}
      const metadata = cfg.metadata || {}
      const requestId = metadata.requestId || 'unknown'
      const duration = metadata.startTime ? Date.now() - metadata.startTime : 0
      const timestamp = new Date().toISOString()

      // Log error details
      console.group(`❌ [API ERROR #${requestId}] ${cfg.method?.toUpperCase() || 'GET'} ${cfg.url || cfg.baseURL}`)
      console.log('📅 Timestamp:', timestamp)
      console.log('⏱️ Duration:', `${duration}ms`)
      
      if (error.response) {
        // Server responded with error status
        console.error('📊 Status:', `${error.response.status} ${error.response.statusText}`)
        console.error('📥 Response Headers:', formatHeaders(error.response.headers || {}))
        console.error('📦 Error Data:', error.response.data)
        console.error('🔗 Request URL:', error.config?.url || error.config?.baseURL)
        console.error('📤 Request Method:', error.config?.method?.toUpperCase())
      } else if (error.request) {
        // Request was made but no response received
        console.error('⚠️ No response received from server')
        console.error('🔗 Request URL:', error.config?.url || error.config?.baseURL)
        console.error('📤 Request Method:', error.config?.method?.toUpperCase())
        console.error('Request object:', error.request)
      } else {
        // Error in request setup
        console.error('⚠️ Error setting up request:', error.message)
      }
      
      console.error('🔍 Full Error:', error)
      if (error.stack) {
        console.error('📚 Stack Trace:', error.stack)
      }
      console.groupEnd()

      if (!cfg.skipLoader) {
        activeRequests = Math.max(0, activeRequests - 1)
        notifySubscribers()
      }
      return Promise.reject(error)
    }
  )
}

// Hook to expose a simple boolean: is any axios request in-flight?
export function useAxiosLoader() {
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    initInterceptors()

    const subscriber = (count) => {
      setIsLoading(count > 0)
    }

    subscribers.push(subscriber)
    // Initial sync
    subscriber(activeRequests)

    return () => {
      subscribers = subscribers.filter((fn) => fn !== subscriber)
    }
  }, [])

  return isLoading
}
