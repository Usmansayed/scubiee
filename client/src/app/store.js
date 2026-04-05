import { configureStore, combineReducers } from '@reduxjs/toolkit';
import { persistReducer, persistStore, FLUSH, REHYDRATE, PAUSE, PERSIST, PURGE, REGISTER } from 'redux-persist';
import storage from 'redux-persist/lib/storage'; // localStorage
import userReducer from '../Slices/userSlice';
import chatReducer from '../Slices/chatSlice';
import widgetReducer from '../Slices/WidgetSlice';
import notificationReducer from '../Slices/NotificationSlice';
import profileReducer from '../Slices/profileSlice'; // Add import for the new profile slice
import homeReducer from '../Slices/HomeSlice'; // Add import for home slice
import shortsReducer from '../Slices/ShortsSlice'; // Add this import
import { setupReduxDebugging } from '../utils/ReduxDebugger';

// User persistence config - only store minimal user identifying information
const userPersistConfig = {
  key: 'user',
  storage,
  whitelist: ['socketUserId'], // Only persist the socket user ID, not the full userData
  blacklist: ['userData', 'loading', 'error'],
  debug: true,
};

// No persistence for widget - don't store these in localStorage
const widgetPersistConfig = {
  key: 'widget',
  storage,
  whitelist: [], // Don't persist any widget data - empty whitelist
  debug: true,
};

// No persistence for notifications - rely on server
const notificationPersistConfig = {
  key: 'notification',
  storage,
  whitelist: [], // Don't persist notifications
  debug: true,
};

// No persistence for profile data - rely on server
const profilePersistConfig = {
  key: 'profile',
  storage,
  whitelist: [], // Don't persist profile data at all
  debug: true,
};

// No persistence for home feed - rely on server
const homePersistConfig = {
  key: 'home',
  storage,
  whitelist: [], // Don't persist home data at all
  debug: true,
};

// Create the root reducer with modified persistence
const rootReducer = combineReducers({
  user: persistReducer(userPersistConfig, userReducer),
  chat: chatReducer, // Chat doesn't need persistence
  widget: persistReducer(widgetPersistConfig, widgetReducer),
  notification: persistReducer(notificationPersistConfig, notificationReducer),
  profile: persistReducer(profilePersistConfig, profileReducer),
  home: persistReducer(homePersistConfig, homeReducer), // Add home reducer
  shorts: shortsReducer, // Add the shorts reducer
});

// Configure the store
export const store = configureStore({
  reducer: rootReducer,
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        ignoredActions: [
          FLUSH, REHYDRATE, PAUSE, PERSIST, PURGE, REGISTER, 
          'notification/addRealTimeNotification',
          // Add profile actions to ignored actions list
          'profile/fetchProfileInfo/fulfilled',
          'profile/fetchUserPosts/fulfilled', 
          'profile/fetchUserShorts/fulfilled',
          // Add home actions to ignored actions list
          'home/fetchFeedPosts/fulfilled',
          'home/loadMorePosts/fulfilled'
        ],
        // Add specific notification action types to ignore serialization checks
        ignoredActionPaths: ['payload.sender', 'meta.arg', 'payload.timestamp'],
        // CRITICAL FIX: Ignore serialization for these paths to avoid errors
        ignoredPaths: [
          'chat.onlineUsers', 
          'notification.notifications.sender',
          'profile.profileInfo.socialLinks',
          'home.posts' // Add this to avoid serialization errors
        ]
      },
    }),
});

// Set up a change listener to debug notification updates
store.subscribe(() => {
  const state = store.getState();
  const notificationCount = state.notification?.notifications?.length || 0;
  const unreadCount = state.notification?.unreadCount || 0;
  
  // Throttle console logs to avoid flooding
  if (window.lastStoreLog && Date.now() - window.lastStoreLog < 1000) {
    return;
  }
  
  console.log(`Store updated: ${notificationCount} notifications (${unreadCount} unread)`);
  window.lastStoreLog = Date.now();
});

// Set up Redux debugging tools
setupReduxDebugging(store);

// Add a global debug function to inspect notifications
window.debugNotifications = () => {
  const state = store.getState();
  console.log('Current notifications:', state.notification.notifications);
  return state.notification.notifications;
};

// CRITICAL FIX: Create a dedicated function to handle notification updates
window.updateNotificationInRedux = (notification) => {
  try {
    if (!notification) return false;
    
    const currentState = store.getState();
    const userId = currentState.user?.userData?.id;
    
    // Make sure we have a user ID
    if (!userId) {
      console.warn("No user ID found, can't add notification");
      return false;
    }
    
    // Make sure notification has a user ID
    if (!notification.user_id) {
      notification.user_id = userId;
    }
    
    // Dispatch notification to Redux
    store.dispatch({
      type: 'notification/addRealTimeNotification',
      payload: notification
    });
    
    return true;
  } catch (error) {
    console.error("Error updating notification in Redux:", error);
    return false;
  }
};

// Add a simple way to force reload notifications
window.reloadNotifications = () => {
  store.dispatch({
    type: 'notification/fetchNotifications',
    payload: 1
  });
  return "Reloading notifications...";
};

// Add a global debug function to inspect profile state
window.debugProfile = () => {
  const state = store.getState();
  console.log('Current profile state:', state.profile);
  return state.profile;
};

// Add a global debug function to inspect all Redux state
window.debugReduxState = () => {
  const state = store.getState();
  console.log('Current Redux state:', state);
  // Log specific profile state details
  console.log('Profile slice exists:', state.hasOwnProperty('profile'));
  if (state.profile) {
    console.log('Profile state:', state.profile);
  } else {
    console.log('Profile slice is not found in the Redux store!');
    console.log('Available slices:', Object.keys(state));
  }
  return state;
};

// Add specific check to verify profile persistence is working
export const persistor = persistStore(store, null, () => {
  console.log("Redux state rehydration completed");
  const state = store.getState();
  
  // Log what was actually persisted
  console.log("Persisted state keys:", Object.keys(state));
  console.log("User data persisted:", state.user?.socketUserId ? "Only socketUserId" : "None");
  console.log("Profile data persisted:", "None - Using server data on refresh");
  console.log("Widget data persisted:", "None - Using server data on refresh");
  console.log("Notifications persisted:", "None - Using server data on refresh");
  
  // CRITICAL: Set a global flag to indicate rehydration completed
  window.reduxRehydrated = true;
  
  // CRITICAL: Dispatch an event that components can listen for
  try {
    window.dispatchEvent(new Event('redux-persist-rehydrated'));
    console.log("Redux rehydration event dispatched");
  } catch (err) {
    console.error("Error dispatching rehydration event:", err);
  }
});

export default store;
