import { io } from 'socket.io-client';

const api = import.meta.env.VITE_API_URL || '';
const SOCKET_URL = api.replace(/\/api$/, ''); // Remove '/api' if present

// Create a Set to track online users
let onlineUsersSet = new Set();
// Add callback registry for components to subscribe to online status changes
const onlineStatusCallbacks = new Set();

// Configure socket with robust connection settings
// Create socket without requiring user ID upfront
const socket = io(SOCKET_URL, {
  reconnectionAttempts: 10,
  reconnectionDelay: 1000,
  reconnectionDelayMax: 10000,
  timeout: 20000,
  autoConnect: true,
  withCredentials: true
});

// Track connection state to avoid duplicate event handlers
let initialized = false;

// Track if we've already sent online status to prevent duplicates
let onlineStatusSent = false;
let currentUserId = null;

// Initialize socket event handlers
const initializeSocket = () => {
  if (initialized) return;
  
  // Add connection state logging
  socket.on('connect', () => {
    console.log('Socket connected with ID:', socket.id);
    
    // If we have a user ID, emit online status
    if (currentUserId) {
      emitUserOnline(currentUserId);
    }
    
    // Request current online users on connect/reconnect
    socket.emit('requestOnlineUsers');
  });

  socket.on('disconnect', (reason) => {
    console.warn('Socket disconnected:', reason);
    onlineStatusSent = false;
  });

  socket.on('initialOnlineUsers', ({ users }) => {
    console.log('Received initialOnlineUsers:', users);
    // Update our local online users set - use strings instead of parsing as integers
    onlineUsersSet = new Set(users.map(id => 
      typeof id === 'object' ? String(id.id) : String(id)
    ));
    
    // Notify all subscribers of the change
    notifyOnlineStatusChange();
  });

  socket.on('userOnline', ({ userId }) => {
    console.log('User came online:', userId);
    // Add user to online set - as string
    onlineUsersSet.add(String(userId));
    
    // Notify all subscribers
    notifyOnlineStatusChange();
  });

  socket.on('userOffline', ({ userId }) => {
    console.log('User went offline:', userId);
    // Remove user from online set - as string
    onlineUsersSet.delete(String(userId));
    
    // Notify all subscribers
    notifyOnlineStatusChange();
  });

  // Mark as initialized to prevent duplicate handlers
  initialized = true;
}

// Initialize immediately
initializeSocket();

// Helper function to emit online status only when needed
function emitUserOnline(userId) {
  // Only emit if we haven't already sent it or if the user ID changed
  if (!onlineStatusSent) {
    socket.emit('userOnline', { userId });
    onlineStatusSent = true;
    console.log('Emitted userOnline for ID:', userId);
  }
}

// Function to subscribe to online status changes
export const subscribeToOnlineStatus = (callback) => {
  onlineStatusCallbacks.add(callback);
  
  // Immediately provide current online users to the new subscriber
  callback(new Set(onlineUsersSet));
  
  // Return unsubscribe function
  return () => {
    onlineStatusCallbacks.delete(callback);
  };
};

// Function to notify all subscribers of online status changes
const notifyOnlineStatusChange = () => {
  onlineStatusCallbacks.forEach(callback => {
    callback(new Set(onlineUsersSet));
  });
};

// Function to check if a user is online - compare as strings
export const isUserOnline = (userId) => {
  return onlineUsersSet.has(String(userId));
};

// Function to update socket with user ID - will be called from App.jsx
export const updateSocketWithUserId = (userId) => {
  if (!userId) return;
  
  currentUserId = userId;
  
  if (socket.connected) {
    emitUserOnline(userId);
  }
  // If not connected, the connect event handler will emit when connection is established
};

// Function to explicitly set user offline (only used on logout)
export const setUserOffline = (userId) => {
  if (userId && socket.connected) {
    socket.emit('userOffline', { userId });
    onlineStatusSent = false;
    console.log('Set user offline:', userId);
  }
};

// Expose socket connection status for components
export const getSocketStatus = () => ({
  connected: socket.connected,
  connecting: socket.connecting,
});

// Re-export the socket event and emit functions to prevent direct manipulation of socket
export const onSocketEvent = (event, callback) => {
  socket.on(event, callback);
  return () => socket.off(event, callback);
};

export const emitSocketEvent = (event, data, callback) => {
  socket.emit(event, data, callback);
};

export default socket;