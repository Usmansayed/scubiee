/**
 * Socket Connection Manager
 * 
 * This utility handles socket connections and online status changes,
 * preventing too frequent reconnections and status updates.
 */

class SocketManager {
  constructor() {
    this.isOnline = navigator.onLine;
    this.lastStatusChange = Date.now();
    this.statusChangeThrottleMs = 60000; // 1 minute minimum between status changes
    this.isThrottled = false;
    this.pendingReconnect = null;
    this.handlers = new Set();
    this.setupListeners();
  }

  setupListeners() {
    // Override the default online/offline behavior
    window.addEventListener('online', this.handleOnlineEvent.bind(this), { capture: true });
    window.addEventListener('offline', this.handleOfflineEvent.bind(this), { capture: true });
  }

  handleOnlineEvent(event) {
    // Allow the first online event after page load
    if (Date.now() - this.lastStatusChange < this.statusChangeThrottleMs && this.isThrottled) {
      console.log('🔌 Online event throttled');
      event.stopImmediatePropagation();
      return;
    }
    
    this.isOnline = true;
    this.lastStatusChange = Date.now();
    this.isThrottled = true;
    
    // Notify registered handlers (if any)
    this.notifyHandlers('online');
    
    console.log('🟢 Online status registered');
    
    // Re-enable after throttle period
    if (this.pendingReconnect) {
      clearTimeout(this.pendingReconnect);
    }
    
    this.pendingReconnect = setTimeout(() => {
      this.isThrottled = false;
      this.pendingReconnect = null;
    }, this.statusChangeThrottleMs);
  }

  handleOfflineEvent(event) {
    if (Date.now() - this.lastStatusChange < this.statusChangeThrottleMs && this.isThrottled) {
      console.log('🔌 Offline event throttled');
      event.stopImmediatePropagation();
      return;
    }
    
    this.isOnline = false;
    this.lastStatusChange = Date.now();
    this.isThrottled = true;
    
    // Notify registered handlers (if any)
    this.notifyHandlers('offline');
    
    console.log('🔴 Offline status registered');
    
    // Re-enable after throttle period
    if (this.pendingReconnect) {
      clearTimeout(this.pendingReconnect);
    }
    
    this.pendingReconnect = setTimeout(() => {
      this.isThrottled = false;
      this.pendingReconnect = null;
    }, this.statusChangeThrottleMs);
  }

  registerStatusHandler(handler) {
    if (typeof handler === 'function') {
      this.handlers.add(handler);
      return () => this.handlers.delete(handler);
    }
    return () => {};
  }

  notifyHandlers(status) {
    for (const handler of this.handlers) {
      try {
        handler(status);
      } catch (error) {
        console.error('Error in status handler:', error);
      }
    }
  }
}

// Create singleton instance
const socketManager = new SocketManager();
export default socketManager;
