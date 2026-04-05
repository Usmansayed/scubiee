import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { markAllNotificationsAsRead } from '../Slices/NotificationSlice';

/**
 * Component dedicated to tracking when user is on the notifications page
 * and ensuring notifications are properly marked as read
 */
const NotificationPageTracker = ({ children }) => {
  const location = useLocation();
  const dispatch = useDispatch();
  const [isOnNotificationsPages, setIsOnNotificationsPages] = useState(false);
  const cloud = import.meta.env.VITE_CLOUD_URL;

  // Track page navigation and update global status
  useEffect(() => {
    const currentPath = location.pathname;
    const isOnNotificationsPage = currentPath.includes('/notifications');
    setIsOnNotificationsPages(isOnNotificationsPage);
    
    console.log(`🔍 NotificationPageTracker: Path changed to ${currentPath}`);
    console.log(`🔍 Is on notifications page: ${isOnNotificationsPage}`);
    
    // Set global flag for other components to check
    window.isOnNotificationPage = isOnNotificationsPage;
    
    // If navigating to notifications page, mark all as read
    if (isOnNotificationsPage) {
      console.log('🔍 Marking all notifications as read due to navigation');
      dispatch(markAllNotificationsAsRead());
      
      // Dispatch custom event to notify other components
      try {
        const event = new CustomEvent('notifications-page-entered', {
          detail: { timestamp: Date.now() }
        });
        window.dispatchEvent(event);
      } catch (error) {
        console.error('Error dispatching notifications-page-entered event:', error);
      }
    } else if (window.isOnNotificationPage !== isOnNotificationsPage) {
      // If navigating away from notifications page, notify components
      try {
        const event = new CustomEvent('notifications-page-exited', {
          detail: { timestamp: Date.now() }
        });
        window.dispatchEvent(event);
      } catch (error) {
        console.error('Error dispatching notifications-page-exited event:', error);
      }
    }
    
    // Cleanup when component unmounts
    return () => {
      if (isOnNotificationsPage) {
        window.isOnNotificationPage = false;
      }
    };
  }, [location.pathname, dispatch]);
  
  // Monitor URL changes from browser navigation (back/forward buttons)
  useEffect(() => {
    const handlePopState = () => {
      const currentPath = window.location.pathname;
      const isOnNotificationsPage = currentPath.includes('/notifications');
      
      console.log(`🔍 PopState detected: ${currentPath}`);
      console.log(`🔍 Is on notifications page: ${isOnNotificationsPage}`);
      
      // Update global flag
      window.isOnNotificationPage = isOnNotificationsPage;
      
      // If on notifications page, mark as read
      if (isOnNotificationsPage) {
        dispatch(markAllNotificationsAsRead());
      }
    };
    
    window.addEventListener('popstate', handlePopState);
    
    return () => {
      window.removeEventListener('popstate', handlePopState);
    };
  }, [dispatch]);
  

  return (
    <>
      {/* Pass the isOnNotificationsPages value to children if needed */}
      {children}
    </>
  );
};

export default NotificationPageTracker;
