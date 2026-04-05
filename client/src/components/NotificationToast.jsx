import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toast, ToastContainer, Slide } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import { store } from '../app/store';
import { markNotificationAsRead } from '../Slices/NotificationSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

const DefaultPicture = "/logos/DefaultPicture.png";
const api = import.meta.env.VITE_API_URL;

// Helper to get notification message based on type
const getNotificationMessage = (notification) => {
  const username = notification.sender?.username || 'Someone';
  
  switch(notification.type) {
    case 'like':
      return notification.isShort 
        ? `${username} liked your short`
        : `${username} liked your post`;
      
    case 'comment':
      return notification.isShort
        ? `${username} commented on your short`
        : `${username} commented on your post`;
      
    case 'follow':
      return `${username} started following you`;
      
    case 'reply':
      return `${username} replied to your comment`;
      
    case 'comment_like':
      return `${username} liked your comment`;
      
    case 'reply_like':
      return `${username} liked your reply`;
      
    default:
      return notification.message || 'You have a new notification';
  }
};

// Custom toast component for notifications
export const NotificationToast = ({ notification }) => {
  const navigate = useNavigate();
  
  const handleClick = () => {
    // Mark notification as read in Redux when toast is clicked
    if (notification.id) {
      store.dispatch(markNotificationAsRead(notification.id));
    }
    
    // Navigation logic based on notification type
    if (notification.type === 'follow' && notification.sender) {
      navigate(`/${notification.sender.username}`);
    } else if (['comment', 'reply', 'comment_like', 'reply_like', 'like'].includes(notification.type)) {
      if (notification.isShort) {
        navigate(`/shorts/${notification.post_id || notification.reference_id}`);
      } else {
        navigate(`/viewpost/${notification.post_id || notification.reference_id}`);
      }
    }
    
    // Dismiss the toast when clicked
    toast.dismiss();
  };

  // Display the correct message
  const displayMessage = notification.message || getNotificationMessage(notification);
  
  return (
    <div 
      className="flex items-center p-2 cursor-pointer hover:bg-gray-800 rounded"
      onClick={handleClick}
    >
      <div className="h-10 w-10 rounded-full overflow-hidden mr-3">
        <img
          className="w-full h-full object-cover"
          src={
            notification.sender?.profilePicture
              ? `${cloud}/cloudofscubiee/profilePic/${notification.sender.profilePicture}`
              : DefaultPicture
          }
          alt={notification.sender?.username || 'User'}
        />
      </div>
      <div>
        <p className="font-medium text-sm">{notification.sender?.username || 'Someone'}</p>
        <p className="text-sm text-gray-300">{displayMessage}</p>
      </div>
    </div>
  );
};

// Function to display the notification toast - DISABLED for now
export const showNotificationToast = (notification) => {
  // Disable toast notifications
  return;
  
  /* Original code:
  // Only show toast if we have the minimum required data
  if (!notification || !notification.type) {
    console.error('Invalid notification data for toast', notification);
    return;
  }
  
  // Ensure proper field mappings (handle both camelCase and snake_case)
  const processedNotification = {
    ...notification,
    id: notification.id || `${notification.type}_${notification.sender_id || notification.senderId}_${Date.now()}`,
    sender_id: notification.sender_id || notification.senderId,
    post_id: notification.post_id || notification.postId,
    reference_id: notification.reference_id || notification.referenceId,
    is_read: notification.is_read || false
  };
  
  console.log("🔔 Showing toast for notification:", processedNotification);
  
  // Generate a unique ID for this toast based on notification content
  const toastId = `notification-${processedNotification.type}-${processedNotification.sender_id}-${processedNotification.reference_id || Date.now()}`;
  
  // Check if this toast already exists to avoid duplicates
  if (!toast.isActive(toastId)) {
    toast(<NotificationToast notification={processedNotification} />, {
      position: "top-right",
      autoClose: 5000,
      hideProgressBar: false,
      closeOnClick: true,
      pauseOnHover: true,
      draggable: true,
      transition: Slide,
      className: "bg-gray-900 text-white",
      toastId: toastId
    });
  }
  */
};

// Toast container component to be used in App.jsx
export const NotificationToastContainer = () => {
  return (
    <ToastContainer
      position="top-right"
      autoClose={5000}
      hideProgressBar={false}
      newestOnTop
      closeOnClick
      rtl={false}
      pauseOnFocusLoss
      draggable
      pauseOnHover
      theme="dark"
    />
  );
};
