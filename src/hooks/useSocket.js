import { useEffect, useRef, useState } from 'react'
import { io } from 'socket.io-client'

export function useSocket(userId) {
  const [socket, setSocket] = useState(null)
  const [isConnected, setIsConnected] = useState(false)
  const socketRef = useRef(null)

  useEffect(() => {
    if (!userId) return

    const newSocket = io(window.location.origin.replace(':3000', ':5000'), {
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
