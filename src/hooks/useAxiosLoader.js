import { useEffect, useState } from 'react'
import axios from 'axios'

// Global state shared across all hook usages
let activeRequests = 0
let subscribers = []
let initialized = false

function notifySubscribers() {
  subscribers.forEach((fn) => {
    try {
      fn(activeRequests)
    } catch (e) {
      // ignore subscriber errors
    }
  })
}

function initInterceptors() {
  if (initialized) return
  initialized = true

  axios.interceptors.request.use(
    (config) => {
      // Opt-out flag: skip global loader for this request
      if (!config.skipLoader) {
        activeRequests += 1
        notifySubscribers()
      }
      return config
    },
    (error) => {
      activeRequests = Math.max(0, activeRequests - 1)
      notifySubscribers()
      return Promise.reject(error)
    }
  )

  axios.interceptors.response.use(
    (response) => {
      const cfg = response.config || {}
      if (!cfg.skipLoader) {
        activeRequests = Math.max(0, activeRequests - 1)
        notifySubscribers()
      }
      return response
    },
    (error) => {
      const cfg = error.config || {}
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
