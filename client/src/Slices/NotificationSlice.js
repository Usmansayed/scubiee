import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';

const initialState = {
  activeNotification: null,       // The notification that was clicked
  loading: false,                 // Loading state for notification context
  error: null,                    // Error if fetching context fails
  notificationType: null,         // Type of notification ('like', 'comment', 'reply', etc.)
  
  // For comment/reply context:
  commentContext: {
    comments: [],                 // List of surrounding comments
    parentComment: null,          // Parent comment (for replies)
    replies: [],                  // List of replies (for reply notifications)
    targetCommentId: null,        // ID of the comment that was interacted with
    context: null                 // 'comment' or 'reply'
  },
  
  // For post context:
  postContext: {
    post: null                    // Post data if needed
  },
  
  // Common fields:
  postId: null,                   // ID of the related post
  referenceId: null,              // ID of the reference object (comment, reply, etc.)
  
  // Added states for notification list:
  notifications: [],              // List of all notifications
  unreadCount: 0,                 // Count of unread notifications
  page: 1,                        // Current page for pagination
  hasMore: true,                  // If there are more notifications to load
  fetchLoading: false,            // Loading state for notifications fetching
  fetchError: null                // Error if fetching notifications fails
};

const notificationSlice = createSlice({
  name: 'notification',
  initialState,
  reducers: {
    setActiveNotification: (state, action) => {
      state.activeNotification = action.payload;
      // Extract common fields from the notification
      if (action.payload) {
        state.notificationType = action.payload.type;
        state.postId = action.payload.post_id;
        state.referenceId = action.payload.reference_id;
      }
    },
    
    setLoading: (state, action) => {
      state.loading = action.payload;
    },
    
    setError: (state, action) => {
      state.error = action.payload;
    },
    
    // For storing comment context from notification-comment endpoint
    setCommentContext: (state, action) => {
      // Handle both comment and reply contexts
      const { comments, parentComment, replies, targetCommentId, context } = action.payload;
      
      state.commentContext = {
        comments: comments || [],
        parentComment: parentComment || null,
        replies: replies || [],
        targetCommentId,
        context
      };
    },
    
    // For storing post context if needed
    setPostContext: (state, action) => {
      state.postContext.post = action.payload;
    },
    
    // Reset all state when navigating away
    clearNotificationContext: (state) => {
      return initialState;
    },
    
    // New reducers for notification list:
    setNotifications: (state, action) => {
      state.notifications = action.payload;
      state.unreadCount = action.payload.filter(notification => !notification.is_read).length;
    },
    
    addNotifications: (state, action) => {
      // First check if we received any new notifications
      if (!action.payload || action.payload.length === 0) {
        // If we get an empty array, mark that we've reached the end
        state.hasMore = false;
        return;
      }
      
      // For non-empty arrays, append the new notifications
      // Make sure we're adding them to the end since pagination goes from newest to oldest
      state.notifications = [...state.notifications, ...action.payload];
      
      // If we received fewer notifications than expected, we're at the end
      // Server sends 16 notifications per page after page 1
      if (action.payload.length < 16) {
        state.hasMore = false;
      }
    },
    
    setPage: (state, action) => {
      state.page = action.payload;
    },
    
    setHasMore: (state, action) => {
      state.hasMore = action.payload;
    },
    
    setFetchLoading: (state, action) => {
      state.fetchLoading = action.payload;
    },
    
    setFetchError: (state, action) => {
      state.fetchError = action.payload;
    },
    
    addRealTimeNotification: (state, action) => {
      console.log('💾 Adding notification to Redux store:', action.payload);
      
      try {
        // Make sure we have a valid payload
        if (!action.payload || !action.payload.type) {
          console.error('Invalid notification payload:', action.payload);
          return;
        }
        
        // CRITICAL FIX: Initialize the notifications array if needed
        if (!Array.isArray(state.notifications)) {
          console.log('💾 Initializing empty notifications array');
          state.notifications = [];
        }
        
        // IMPROVED CHECK: More reliably determine if user is on notifications page
        // Check both the window flag and the current URL path
        const isOnNotificationPage = typeof window !== 'undefined' && (
          window.isOnNotificationPage === true || 
          (window.location.pathname && window.location.pathname.includes('/notifications'))
        );
        
        console.log('💾 Is user on notifications page?', isOnNotificationPage);
        
        // Create consistent notification object
        const newNotification = {
          id: action.payload.id || `${action.payload.type}_${action.payload.sender_id || action.payload.senderId}_${Date.now()}`,
          type: action.payload.type,
          sender_id: action.payload.sender_id || action.payload.senderId,
          user_id: action.payload.user_id,
          reference_id: action.payload.reference_id || action.payload.referenceId,
          reference_type: action.payload.reference_type || action.payload.referenceType || 'post',
          post_id: action.payload.post_id || action.payload.postId,
          message: action.payload.message || '',
          // CRITICAL: Override is_read from payload if user is on notifications page
          is_read: isOnNotificationPage ? true : !!action.payload.is_read,
          createdAt: action.payload.createdAt || action.payload.timestamp || new Date().toISOString(),
          isShort: !!action.payload.isShort,
          sender: action.payload.sender || null
        };
        
        // Check if the notification already exists
        const existingIndex = state.notifications.findIndex(n => {
          if (!n) return false;
          
          // For follow notifications, check type and sender only
          if (newNotification.type === 'follow') {
            return n.type === newNotification.type && 
                  n.sender_id === newNotification.sender_id;
          }
          
          // For other notifications, check type, sender, and reference
          return n.type === newNotification.type && 
                n.sender_id === newNotification.sender_id &&
                n.reference_id === newNotification.reference_id;
        });
        
        // DEBUGGING OUTPUT
        console.log(`💾 Before update: ${state.notifications.length} notifications`);
        
        if (existingIndex !== -1) {
          // Update existing notification instead of removing and reinserting
          // This ensures we don't lose the read status if it was already read
          const existingNotification = state.notifications[existingIndex];
          
          // Only update the timestamp and set is_read if on notifications page
          state.notifications[existingIndex] = { 
            ...existingNotification,
            // CRITICAL: Only override is_read if on notifications page or if explicitly set in payload
            is_read: isOnNotificationPage ? true : existingNotification.is_read,
            createdAt: new Date().toISOString()
          };
          
          // If the notification is not at the top, move it to the top
          if (existingIndex > 0) {
            // Remove from current position
            const notification = state.notifications.splice(existingIndex, 1)[0];
            // Add to beginning
            state.notifications.unshift(notification);
          }
          
          console.log(`💾 Updated existing notification at index ${existingIndex} (is_read: ${state.notifications[0].is_read})`);
        } else {
          // Add new notification at the beginning
          state.notifications.unshift(newNotification);
          console.log(`💾 Added new notification at top (is_read: ${newNotification.is_read})`);
        }
        
        // Emit event to signal a new notification was received
        // This allows components to update without a full refresh
        setTimeout(() => {
          try {
            const event = new CustomEvent('new-notification-received', { 
              detail: { 
                notification: newNotification,
                isOnNotificationPage: isOnNotificationPage
              }
            });
            window.dispatchEvent(event);
          } catch (error) {
            console.error('Error dispatching new-notification-received event:', error);
          }
        }, 0);
        
        // Update unread count (count unread notifications)
        state.unreadCount = state.notifications.filter(n => !n.is_read).length;
        
        console.log(`💾 After update: ${state.notifications.length} notifications, ${state.unreadCount} unread`);
      } catch (error) {
        console.error('Error in addRealTimeNotification reducer:', error);
      }
    },
    
    // Add a new action to mark individual notifications as read
    markNotificationAsRead: (state, action) => {
      const notificationId = action.payload;
      const notification = state.notifications.find(n => n.id === notificationId);
      
      if (notification && !notification.is_read) {
        notification.is_read = true;
        state.unreadCount = Math.max(0, state.unreadCount - 1);
      }
    },
    
    removeNotification: (state, action) => {
      // Find and remove notification based on type, sender_id and reference
      const { type, senderId, referenceId } = action.payload;
      const index = state.notifications.findIndex(notification => 
        notification.type === type && 
        notification.sender_id === senderId &&
        (referenceId ? notification.reference_id === referenceId : true)
      );
      
      if (index !== -1) {
        // If the notification was unread, decrement the counter
        if (!state.notifications[index].is_read) {
          state.unreadCount -= 1;
        }
        // Remove the notification
        state.notifications.splice(index, 1);
      }
    },
    
    markNotificationsAsRead: (state) => {
      state.notifications = state.notifications.map(notification => ({
        ...notification,
        is_read: true
      }));
      state.unreadCount = 0;
    },
    
    incrementUnreadCount: (state) => {
      state.unreadCount += 1;
      state.hasUnread = true;
    },
    
    setUnreadCount: (state, action) => {
      state.unreadCount = action.payload;
    },

    // Fix: recompute unread count from notifications
    initializeUnreadCount: (state) => {
      if (state.notifications && Array.isArray(state.notifications)) {
        state.unreadCount = state.notifications.filter(n => !n.is_read).length;
      } else {
        state.unreadCount = 0;
      }
    },

    // Modified to make sure read status is updated
    markAllNotificationsAsRead: (state) => {
      let anyUpdated = false;
      
      state.notifications = state.notifications.map(notification => {
        if (!notification.is_read) {
          anyUpdated = true;
          return {
            ...notification,
            is_read: true
          };
        }
        return notification;
      });
      
      // Update unread count
      state.unreadCount = 0;
      
      // Dispatch an API call to update server state if any notifications were updated
      if (anyUpdated && typeof window !== 'undefined') {
        // Use a custom event to trigger the API call
        setTimeout(() => {
          try {
            const event = new CustomEvent('notifications-marked-read');
            window.dispatchEvent(event);
          } catch (error) {
            console.error('Error dispatching notifications-marked-read event:', error);
          }
        }, 0);
      }
    },
  },
});

// Create an async thunk to fetch unread notification count
export const fetchUnreadNotificationCount = createAsyncThunk(
  'notification/fetchUnreadCount',
  async (_, { getState, rejectWithValue }) => {
    try {
      // Make API call to get unread notification count
      // Fix the typo in the URL path - change 'notifcations' to 'notifications'
      const api = import.meta.env.VITE_API_URL || '';
      const response = await axios.get(`${api}/user/unread-notifications`, { 
        withCredentials: true 
      });
      
      return response.data;
    } catch (error) {
      console.error('Error fetching unread notifications:', error);
      return rejectWithValue(error.message);
    }
  }
);

export const {
  setActiveNotification,
  setLoading,
  setError,
  setCommentContext,
  setPostContext,
  clearNotificationContext,
  setNotifications,
  addNotifications,
  setPage,
  setHasMore,
  setFetchLoading,
  setFetchError,
  addRealTimeNotification,
  removeNotification,
  markNotificationsAsRead,
  incrementUnreadCount,
  setUnreadCount,
  initializeUnreadCount,
  markNotificationAsRead
} = notificationSlice.actions;

// Thunks
export const fetchNotificationContext = (notification) => async (dispatch, getState) => {
  if (!notification) return;

  dispatch(setLoading(true));
  dispatch(setActiveNotification(notification));
  
  try {
    const api = import.meta.env.VITE_API_URL || '';
    
    // Extract needed information from notification
    const notificationType = notification.type;
    const postId = notification.post_id;
    const referenceId = notification.reference_id;
    
    if (!postId) {
      throw new Error('Post ID is missing in the notification');
    }
    
    // For comment-related notifications, fetch comment context
    if (['comment', 'reply', 'comment_like'].includes(notificationType) && referenceId) {
      const isReply = notificationType === 'reply';
      
      const response = await axios.get(
        `${api}/user-interactions/notification-comment/${postId}`, 
        { 
          params: { 
            commentId: referenceId,
            isReply: isReply
          },
          withCredentials: true 
        }
      );
      
      if (response.data) {
        dispatch(setCommentContext(response.data));
      }
    }
  } catch (error) {
    console.error('Error fetching notification context:', error);
    dispatch(setError(error.message || 'Failed to fetch notification context'));
  } finally {
    dispatch(setLoading(false));
  }
};

// New thunk to fetch notifications with better error handling and debugging
export const fetchNotifications = (pageNum, options = {}) => async (dispatch, getState) => {
  // Extract options with defaults
  const { skipIfDataExists = true, forceRefresh = false } = options;
  const { notifications } = getState().notification;
  
  // Check if we're on the initial page load or browser refresh
  const isInitialPageLoad = typeof window !== 'undefined' && 
    window.performance && 
    window.performance.navigation && 
    (window.performance.navigation.type === 0 || window.performance.navigation.type === 1);
  
  // CRITICAL: Skip fetch if we have data and skipIfDataExists is true and it's not a forced refresh
  // AND we're not on the initial page load/refresh
  if (skipIfDataExists && pageNum === 1 && notifications.length > 0 && !forceRefresh && !isInitialPageLoad) {
    console.log(`Skipping notification fetch - using ${notifications.length} cached notifications`);
    // Just recompute unread count to ensure consistency
    dispatch(initializeUnreadCount());
    return;
  }
  
  try {
    dispatch(setFetchLoading(true));
    dispatch(setFetchError(null));
    
    const api = import.meta.env.VITE_API_URL || '';
    // Add debug info to help with troubleshooting
    console.log(`Fetching notifications page ${pageNum} from ${api}/user-interactions/notifications`);
    
    const response = await axios.get(`${api}/user-interactions/notifications?page=${pageNum}`, {
      withCredentials: true,
    });
    
    // Safely handle the response data
    const newNotifications = response.data?.notifications || [];
    const pagination = response.data?.pagination || { hasMore: false };
    
    // Enhanced logging with more details
    console.log(`Received ${newNotifications.length} notifications for page ${pageNum}`);
    console.log(`Server says hasMore: ${pagination.hasMore}`);
    
    if (pageNum === 1) {
      // First page - replace all notifications
      dispatch(setNotifications(newNotifications));
      // Initialize unread count based on the fetched notifications
      dispatch(initializeUnreadCount());
    } else {
      // Additional pages - append to existing notifications
      if (newNotifications.length > 0) {
        console.log(`Adding ${newNotifications.length} notifications to existing ${notifications.length}`);
        dispatch(addNotifications(newNotifications));
      } else {
        console.log("No new notifications received - marking hasMore as false");
        dispatch(setHasMore(false));
      }
    }
    
    // Update hasMore flag from server response
    dispatch(setHasMore(pagination.hasMore || false));
  } catch (error) {
    console.error("Error fetching notifications:", error);
    dispatch(setFetchError("Failed to load notifications. Please try again later."));
  } finally {
    dispatch(setFetchLoading(false));
  }
};

// New thunk to mark notifications as read
export const markAllNotificationsAsRead = () => async (dispatch) => {
  try {
    const api = import.meta.env.VITE_API_URL || '';
    await axios.post(`${api}/user-interactions/read-all-notifications`, {}, {
      withCredentials: true,
    });
    
    dispatch(markNotificationsAsRead());
  } catch (error) {
    console.error("Error marking notifications as read:", error);
  }
};

export default notificationSlice.reducer;