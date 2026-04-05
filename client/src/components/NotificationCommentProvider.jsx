import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { fetchNotificationContext } from '../Slices/NotificationSlice';

/**
 * This component acts as a wrapper that automatically fetches and manages
 * notification contexts for comment-related notifications.
 * It doesn't render anything itself.
 */
const NotificationCommentProvider = () => {
  const notification = useSelector(state => state.notification.activeNotification);
  const dispatch = useDispatch();
  
  useEffect(() => {
    // If there's an active notification related to comments
    if (notification && ['comment', 'reply', 'comment_like'].includes(notification.type)) {
      // Dispatch the thunk to fetch the notification context
      dispatch(fetchNotificationContext(notification));
    }
  }, [notification, dispatch]);
  
  // This component doesn't render anything
  return null;
};

export default NotificationCommentProvider;
