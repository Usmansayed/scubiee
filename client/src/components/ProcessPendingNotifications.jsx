import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { addRealTimeNotification } from '../Slices/NotificationSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

/**
 * Component dedicated to processing pending notifications
 */
const ProcessPendingNotifications = () => {
  const dispatch = useDispatch();
  const userData = useSelector(state => state.user.userData);
  
  // Function to check if user is currently on notifications page
  const isOnNotificationsPage = () => {
    // Multiple checks to ensure reliability
    return typeof window !== 'undefined' && (
      window.isOnNotificationPage === true || 
      (window.location.pathname && window.location.pathname.includes('/notifications'))
    );
  };
  
  // Function to format notification properly with consistent fields
  const formatNotification = (data, userId) => {
    try {
      const isOnNotifPage = isOnNotificationsPage();
      console.log(`⚡ Formatting notification while on notifications page: ${isOnNotifPage}`);
      
      return {
        id: `${data.type}_${data.senderId || data.sender_id}_${Date.now()}`,
        type: data.type,
        sender_id: data.senderId || data.sender_id,
        user_id: userId,
        reference_id: data.referenceId || data.reference_id || data.postId || data.post_id,
        reference_type: data.referenceType || data.reference_type || 'post',
        post_id: data.postId || data.post_id,
        message: data.message || '',
        // Mark as read if user is on notifications page
        is_read: isOnNotifPage,
        createdAt: data.timestamp || new Date().toISOString(),
        isShort: !!data.isShort,
        sender: data.sender || null
      };
    } catch (error) {
      console.error('⚡ Error formatting notification:', error, data);
      return null;
    }
  };

  // Process a batch of notifications
  const processNotifications = (pendingToProcess) => {
    pendingToProcess.forEach(data => {
      try {
        const notification = formatNotification(data, userData.id);
        if (notification) {
          console.log(`⚡ Dispatching notification (read: ${notification.is_read}):`, notification);
          
          // Use setTimeout to ensure proper execution order in event loop
          setTimeout(() => {
            dispatch(addRealTimeNotification(notification));
            
            // Dispatch custom event to notify components about new notification
            const event = new CustomEvent('new-notification-received', { 
              detail: { notification, isOnNotificationsPage: isOnNotificationsPage() }
            });
            window.dispatchEvent(event);
          }, 0);
        }
      } catch (error) {
        console.error('⚡ Error processing pending notification:', error, data);
      }
    });
  };
  
  useEffect(() => {
    // Only run when we have user data and pending notifications
    if (userData?.id && window.pendingNotifications?.length > 0) {
      console.log('⚡ Processing pending notifications:', window.pendingNotifications.length);
      
      // Make a copy to avoid mutation issues
      const pendingToProcess = [...window.pendingNotifications];
      
      // Clear the pending queue
      window.pendingNotifications = [];
      
      // Process notifications
      processNotifications(pendingToProcess);
    }
  }, [userData?.id, dispatch]);
  
  // Run this effect periodically to check for new pending notifications
  useEffect(() => {
    if (!userData?.id) return;
    
    const checkInterval = setInterval(() => {
      if (window.pendingNotifications?.length > 0) {
        console.log('⚡ Found new pending notifications in interval check');
        
        // Make a copy to avoid mutation issues
        const pendingToProcess = [...window.pendingNotifications];
        
        // Clear the pending queue
        window.pendingNotifications = [];
        
        // Process notifications
        processNotifications(pendingToProcess);
      }
    }, 2000); // Check every 2 seconds
    
    return () => clearInterval(checkInterval);
  }, [userData?.id, dispatch]);

  return null; // This component doesn't render anything
};

export default ProcessPendingNotifications;
