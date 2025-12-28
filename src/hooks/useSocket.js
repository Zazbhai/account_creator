import { useEffect, useRef, useState } from 'react'
import { io } from 'socket.io-client'

export function useSocket(userId) {
  const [socket, setSocket] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const socketRef = useRef(null)

  useEffect(() => {
    if (!userId) return

    // Use environment variable for backend URL (supports tunneling URLs)
    // If VITE_BACKEND_URL is set, use it directly (for tunneling)
    // Otherwise, try to construct from current origin
    const socketUrl = import.meta.env.VITE_BACKEND_URL || (window.location.origin.includes(':7333') 
      ? window.location.origin.replace(':7333', ':6333')
      : window.location.origin)

    const newSocket = io(socketUrl, {
      transports: ['websocket', 'polling'],
      withCredentials: true,
      autoConnect: true
    })

    newSocket.on('connect', () => {
      setIsConnected(true)
      newSocket.emit('join', { userId })
    })

    newSocket.on('disconnect', () => {
      setIsConnected(false)
    })

    newSocket.on('connected', (data) => {
      console.log('Socket connected:', data)
    })

    socketRef.current = newSocket
    setSocket(newSocket)

    return () => {
      if (socketRef.current) {
        socketRef.current.disconnect()
        socketRef.current = null
      }
    }
  }, [userId])

  return { socket, isConnected }
}
