import { addRealTimeNotification, removeNotification } from '../Slices/NotificationSlice';

// Create a middleware that connects socket events to Redux actions
const createSocketMiddleware = () => {
  let socket = null;
  
  return store => next => action => {
    // Special action to set the socket instance
    if (action.type === 'socket/set') {
      socket = action.payload;
      console.log('🔵 Socket instance set in middleware');
      return next(action);
    }
    
    // Special action for when socket connects
    if (action.type === 'socket/connected' && socket) {
      console.log('🔵 Socket connected, setting up listeners in middleware');
      setupSocketListeners(socket, store);
      return next(action);
    }
    
    return next(action);
  };
};

// Setup socket listeners in a separate function
const setupSocketListeners = (socket, store) => {
  // CRITICAL FIX: Properly remove and register listeners
  console.log('🔵 Setting up socket listeners in middleware');
  
  // First remove any existing listeners
  socket.off('notification');
  socket.off('notification_remove');
  
  // Listen for new notifications
  socket.on('notification', data => {
    console.log('🔴 Socket middleware received notification:', data);
    
    // Make sure we have a valid user ID
    const userId = store.getState()?.user?.userData?.id;
    if (!userId) {
      console.warn('No user ID found in store, skipping notification processing in middleware');
      return;
    }
    
    // Make sure we have the minimum required fields
    if (!data.type || (!data.senderId && !data.sender_id)) {
      console.error('Notification missing required fields in middleware:', data);
      return;
    }
    
    // Create a properly formatted notification with ALL fields Redux expects
    const notification = {
      id: `${data.type}_${data.senderId || data.sender_id}_${Date.now()}`,
      type: data.type,
      sender_id: data.senderId || data.sender_id,
      user_id: userId, // Critical for proper handling
      reference_id: data.referenceId || data.reference_id || data.postId || data.post_id || data.commentId,
      reference_type: data.referenceType || data.reference_type || 'post',
      post_id: data.postId || data.post_id,
      message: data.message || '',
      is_read: false,
      createdAt: data.timestamp || new Date().toISOString(),
      timestamp: data.timestamp || new Date().toISOString(),
      isShort: !!data.isShort,
      sender: data.sender || null
    };
    
    console.log('🔴 SOCKET MIDDLEWARE: Dispatching notification to Redux:', notification);
    
    // CRITICAL FIX: Directly invoke the reducer using action.type
    try {
      store.dispatch(addRealTimeNotification(notification));
      
      // Log state after dispatch
      setTimeout(() => {
        const state = store.getState();
        const count = state.notification?.notifications?.length || 0;
        console.log(`🔴 After middleware dispatch: ${count} notifications in Redux`);
      }, 50);
    } catch (error) {
      console.error('Error dispatching notification in middleware:', error);
      
      // Fallback: try direct dispatch with type
      try {
        store.dispatch({
          type: 'notification/addRealTimeNotification',
          payload: notification
        });
      } catch (err) {
        console.error('Even fallback dispatch failed:', err);
      }
    }
  });
  
  // Listen for notification removals
  socket.on('notification_remove', data => {
    console.log('Socket middleware received notification removal:', data);
    try {
      store.dispatch(removeNotification({
        type: data.type,
        senderId: data.senderId || data.sender_id,
        referenceId: data.postId || data.post_id || data.commentId || data.referenceId || data.reference_id
      }));
    } catch (error) {
      console.error('Error handling notification removal:', error);
    }
  });
  
  // Confirm listeners are set up
  console.log('🔵 Socket listeners successfully set up in middleware');
};

// Export the middleware creator function
export default createSocketMiddleware();
