/**
 * Redux Debugging Utility
 * 
 * This file provides utility functions to help debug Redux state issues
 */

// Add redux state debugging to the window object for console access
export const setupReduxDebugging = (store) => {
  if (!window) return;
  
  // Add global access to debug Redux state
  window.reduxDebug = {
    // Get notification state
    getNotifications: () => {
      const state = store.getState();
      return state.notification?.notifications || [];
    },
    
    // Get notification count
    getNotificationCount: () => {
      const state = store.getState();
      return state.notification?.notifications?.length || 0;
    },
    
    // Get unread notification count
    getUnreadCount: () => {
      const state = store.getState();
      return state.notification?.unreadCount || 0;
    },
    
    // Manually add a test notification
    addTestNotification: () => {
      const testNotification = {
        id: `test_notification_${Date.now()}`,
        type: 'test',
        sender_id: 1,
        reference_id: 1,
        post_id: 1,
        message: 'Test notification',
        is_read: false,
        createdAt: new Date().toISOString(),
      };
      
      store.dispatch({
        type: 'notification/addRealTimeNotification',
        payload: testNotification
      });
      
      return "Test notification added";
    },
    
    // Print notification state to console
    printNotifications: () => {
      const state = store.getState();
      const notifications = state.notification?.notifications || [];
      console.table(notifications.map(n => ({
        id: n.id,
        type: n.type,
        sender: n.sender_id,
        reference: n.reference_id,
        isRead: n.is_read,
        date: n.createdAt
      })));
      return `${notifications.length} notifications printed to console`;
    },
    
    // Clear all notifications (for testing)
    clearNotifications: () => {
      store.dispatch({
        type: 'notification/setNotifications',
        payload: []
      });
      return "Notifications cleared";
    },
    
    // Fix notifications array if needed
    fixNotifications: () => {
      const state = store.getState();
      const notifications = state.notification?.notifications;
      
      // Check if notifications is not an array or is null
      if (!Array.isArray(notifications)) {
        console.log('Fixing broken notifications state - initializing empty array');
        store.dispatch({
          type: 'notification/setNotifications',
          payload: []
        });
        return 'Notifications fixed - initialized empty array';
      }
      
      return `Notifications array looks OK with ${notifications.length} items`;
    },
    
    // Force reload notifications from server
    reloadNotifications: async () => {
      console.log('Forcing reload of notifications from server');
      
      // First reset the page
      store.dispatch({
        type: 'notification/setPage',
        payload: 1
      });
      
      // Then fetch notifications
      store.dispatch({
        type: 'notification/fetchNotifications',
        payload: 1
      });
      
      return 'Notifications reload initiated';
    }
  };
  
  console.log("Redux debugging tools available. Access with window.reduxDebug");
};
