import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import socketManager from '../utils/SocketManager';
import { addRealTimeNotification, fetchNotifications } from '../Slices/NotificationSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

/**
 * Component that ensures socket is properly connected and synchronized with Redux
 * This helps with timing issues where notifications might be received before the user is logged in
 */
const SocketListener = () => {
  const dispatch = useDispatch();
  const userData = useSelector(state => state.user.userData);
  const { notifications } = useSelector(state => state.notification);
  
  // When user logs in, ensure socket is connected with proper user ID
  useEffect(() => {
    if (userData?.id) {
      console.log('SocketListener: User logged in, ensuring socket connection', userData.id);
      
      // Save user ID to localStorage for socket reconnects
      try {
        localStorage.setItem('userId', userData.id);
      } catch (e) {
        console.error('Could not save userId to localStorage:', e);
      }
      
      // Ensure socket is connected
      if (!socketManager.connected) {
        socketManager.connect();
      }
      
      // Ensure store is set
      if (socketManager.store) {
        // Join notification room with userId
        if (socketManager.socket) {
          socketManager.socket.emit('join_notification_room', { userId: userData.id });
        }
        
        // Process any pending notifications
        if (window.pendingNotifications?.length > 0) {
          console.log('Processing pending notifications in SocketListener:', window.pendingNotifications.length);
          const pending = [...window.pendingNotifications];
          window.pendingNotifications = [];
          
          pending.forEach(pendingData => {
            const notification = {
              id: `${pendingData.type}_${pendingData.senderId || pendingData.sender_id}_${Date.now()}`,
              type: pendingData.type,
              sender_id: pendingData.senderId || pendingData.sender_id,
              user_id: userData.id,
              reference_id: pendingData.referenceId || pendingData.reference_id || pendingData.postId || pendingData.post_id,
              reference_type: pendingData.referenceType || pendingData.reference_type || 'post',
              post_id: pendingData.postId || pendingData.post_id,
              message: pendingData.message || '',
              is_read: false,
              createdAt: pendingData.timestamp || new Date().toISOString(),
              isShort: !!pendingData.isShort,
              sender: pendingData.sender || null
            };
            
            // Dispatch to Redux
            dispatch(addRealTimeNotification(notification));
          });
        }
      }
    }
  }, [userData?.id, dispatch]);
  
  // Set up a listener to detect when we're on the notifications page
  // and ensure we have latest data
  useEffect(() => {
    if (!userData?.id) return;
    
    // Check if we're currently on the notifications page
    const isOnNotificationsPage = window.location.pathname === '/notifications';
    
    // If we're on the notifications page and notifications were updated elsewhere
    // (like a new notification coming in), ensure the page data is fresh
    if (isOnNotificationsPage) {
      const handleVisibilityChange = () => {
        if (document.visibilityState === 'visible') {
          console.log('Tab became visible on notifications page, refreshing data');
          dispatch(fetchNotifications(1));
        }
      };

      // Listen for visibility changes (tab focus/unfocus)
      document.addEventListener('visibilitychange', handleVisibilityChange);
      
      return () => {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      };
    }
  }, [userData?.id, dispatch]);

  return null; // This component doesn't render anything
};

export default SocketListener;
