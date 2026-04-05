import React, { useState, useEffect } from 'react';
import socketManager from '../utils/SocketManager';
const cloud = import.meta.env.VITE_CLOUD_URL;

/**
 * Component to monitor and debug socket connection status
 * Only shown in development mode
 */
const SocketDebugger = () => {
  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState('');
  const [showDebugger, setShowDebugger] = useState(false);
  
  useEffect(() => {
    // Only run in development environment
    if (process.env.NODE_ENV !== 'development') return;
    
    // Check socket connection
    const checkConnection = () => {
      const connected = socketManager.socket?.connected || false;
      setIsConnected(connected);
    };
    
    // Subscribe to socket events
    const setupListeners = () => {
      if (!socketManager.socket) return;
      
      socketManager.socket.on('connect', () => {
        setIsConnected(true);
        setLastEvent('Connected');
      });
      
      socketManager.socket.on('disconnect', () => {
        setIsConnected(false);
        setLastEvent('Disconnected');
      });
      
      socketManager.socket.on('notification', () => {
        setLastEvent('Notification received');
      });
    };
    
    // Initial check
    checkConnection();
    setupListeners();
    
    // Periodic check
    const interval = setInterval(checkConnection, 5000);
    
    return () => {
      clearInterval(interval);
      
      if (socketManager.socket) {
        socketManager.socket.off('connect');
        socketManager.socket.off('disconnect');
        socketManager.socket.off('notification');
      }
    };
  }, []);
  
  // Only run in development environment
  if (process.env.NODE_ENV === 'development') {
    // This is invisible by default - only shows when explicitly enabled in the code
    return null;
  }
  
  // Don't render anything in other environments
  return null;
};

export default SocketDebugger;
