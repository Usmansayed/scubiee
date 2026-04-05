import React, { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { fetchNotifications, initializeUnreadCount, addRealTimeNotification } from '../Slices/NotificationSlice';

/**
 * Component responsible for listening to real-time notification events
 * and keeping the notification state in sync with the server.
 */
const NotificationListener = () => {
  const dispatch = useDispatch();
  const { userData } = useSelector((state) => state.user);
  const { notifications } = useSelector((state) => state.notification);
  const isLoggedIn = !!userData;
  const initialized = useRef(false);
  const initialFetchDone = useRef(false);
  const cloud = import.meta.env.VITE_CLOUD_URL;

  // Debug notifications array when it changes
  useEffect(() => {
    if (notifications?.length > 0) {
      console.log("NotificationListener: notifications in Redux store:", notifications.length);
    }
  }, [notifications]);

  // CRITICAL FIX: Process any pending notifications when user data becomes available
  useEffect(() => {
    if (isLoggedIn && userData?.id && window.pendingNotifications?.length > 0) {
      console.log('Processing pending notifications:', window.pendingNotifications.length);
      
      const pendingToProcess = [...window.pendingNotifications];
      window.pendingNotifications = []; // Clear pending queue
      
      pendingToProcess.forEach(data => {
        // Format the notification properly
        const notification = {
          id: `${data.type}_${data.senderId || data.sender_id}_${Date.now()}`,
          type: data.type,
          sender_id: data.senderId || data.sender_id,
          user_id: userData.id,
          reference_id: data.referenceId || data.reference_id || data.postId || data.post_id,
          reference_type: data.referenceType || data.reference_type || 'post',
          post_id: data.postId || data.post_id,
          message: data.message || '',
          is_read: false,
          createdAt: data.timestamp || new Date().toISOString(),
          isShort: !!data.isShort,
          sender: data.sender || null
        };
        
        console.log('Processing pending notification:', notification);
        dispatch(addRealTimeNotification(notification));
      });
    }
  }, [isLoggedIn, userData?.id, dispatch]);

  // CRITICAL FIX: Make sure notifications is an array
  useEffect(() => {
    // Only run this once
    if (!initialized.current && isLoggedIn) {
      // Make sure notifications is an array
      if (!Array.isArray(notifications)) {
        console.log("Initializing notifications array in Redux store");
        dispatch({ 
          type: 'notification/setNotifications',
          payload: [] 
        });
      }
      initialized.current = true;
    }
  }, [isLoggedIn, notifications, dispatch]);

  // REMOVED: Periodic notification checking
  // This removes the timed-based refresh

  useEffect(() => {
    // Only set up if the user is logged in
    if (isLoggedIn) {
      // Initialize unread count from loaded notifications
      if (Array.isArray(notifications) && notifications.length > 0 && !initialized.current) {
        console.log("Initializing unread count from loaded notifications");
        dispatch(initializeUnreadCount());
        initialized.current = true;
      }
      
      // Perform initial notification fetch on mount
      if (!initialFetchDone.current) {
        console.log("Performing initial notification fetch");
        dispatch(fetchNotifications(1));
        initialFetchDone.current = true;
      }
    }
  }, [isLoggedIn, dispatch, notifications]);

  // Re-initialize unread count when notifications change significantly
  useEffect(() => {
    if (Array.isArray(notifications) && notifications.length > 0) {
      dispatch(initializeUnreadCount());
    }
  }, [notifications, dispatch]);

  // This component doesn't render anything
  return null;
};

export default NotificationListener;
