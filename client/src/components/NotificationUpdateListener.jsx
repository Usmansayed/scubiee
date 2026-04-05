import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { fetchNotifications, markAllNotificationsAsRead, setNotifications } from '../Slices/NotificationSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

/**
 * Component that listens for notification updates and ensures the notifications page
 * gets refreshed when necessary
 */
const NotificationUpdateListener = () => {
  const dispatch = useDispatch();
  const location = useLocation();
  const navigate = useNavigate();
  const [lastRefreshTime, setLastRefreshTime] = useState(Date.now());
  const { notifications } = useSelector(state => state.notification);
  
  // Set the global flag when on notifications page
  useEffect(() => {
    const isOnNotificationPage = location.pathname.includes('/notifications');
    
    console.log(`📱 Navigation detected - isOnNotificationPage: ${isOnNotificationPage}`);
    window.isOnNotificationPage = isOnNotificationPage;
    
    // Mark all as read when on notification page - BUT ONLY ONCE when navigating
    if (isOnNotificationPage) {
      console.log('📱 Marking all notifications as read on page navigation');
      dispatch(markAllNotificationsAsRead());
      
      // Keep the throttled refresh logic if needed, but remove time-based refresh
      const now = Date.now();
      if (now - lastRefreshTime > 5000000) { // Limit to once every 5 seconds
        console.log('📱 Refreshing notifications list');
        // Only fetch if we don't have notifications
        if (!notifications || !Array.isArray(notifications) || notifications.length === 0) {
          dispatch(fetchNotifications(1));
          setLastRefreshTime(now);
        } else {
          console.log('📱 Using existing notifications data');
        }
      }
    }
    
    return () => {
      if (isOnNotificationPage) {
        // Cleanup logic if needed
      }
    };
  }, [location.pathname, dispatch]);
  
  // Listen for custom notification update events - keep this
  useEffect(() => {
    const handleNotificationUpdate = (event) => {
      console.log('📢 Notification update event received:', event.detail);
      
      // Handle notification update events...
    };
    
    const handleNewNotification = (event) => {
      console.log('📢 New notification received event:', event.detail);
      
      // Handle new notification events...
    };
    
    // Add event listeners
    window.addEventListener('notifications-updated', handleNotificationUpdate);
    window.addEventListener('new-notification-received', handleNewNotification);
    
    // Cleanup
    return () => {
      window.removeEventListener('notifications-updated', handleNotificationUpdate);
      window.removeEventListener('new-notification-received', handleNewNotification);
    };
  }, [location.pathname, dispatch, lastRefreshTime]);

  return null; // This component doesn't render anything
};

export default NotificationUpdateListener;
