import axios from 'axios';

// Create an axios instance with default configuration
const axiosWithTimeout = (timeout = 30000) => {
  const instance = axios.create({
    timeout: timeout, // Default 30 second timeout
    withCredentials: true
  });

  // Add request interceptor to track pending requests
  instance.interceptors.request.use(config => {
    // Ensure the request has an ID
    config.id = config.id || Date.now().toString();
    return config;
  });

  return instance;
};

// Function to retry a failed request
const retryRequest = async (requestFn, maxRetries = 3, delay = 1000) => {
  let lastError;
  
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await requestFn();
    } catch (error) {
      console.warn(`Request failed (attempt ${attempt + 1}/${maxRetries}):`, error.message);
      lastError = error;
      
      // Only retry certain types of errors (network errors, timeouts)
      if (!error.isAxiosError || error.response) {
        throw error;
      }
      
      // Wait before retrying
      await new Promise(resolve => setTimeout(resolve, delay * (attempt + 1)));
    }
  }
  
  throw lastError;
};

// Cache implementation
const messageCache = {
  data: new Map(),
  set: (key, value, ttl = 300000) => { // Default TTL: 5 minutes
    const item = {
      value,
      expiry: Date.now() + ttl
    };
    messageCache.data.set(key, item);
  },
  get: (key) => {
    const item = messageCache.data.get(key);
    if (!item) return null;
    if (Date.now() > item.expiry) {
      messageCache.data.delete(key);
      return null;
    }
    return item.value;
  },
  clear: () => messageCache.data.clear()
};

export { axiosWithTimeout, retryRequest, messageCache };
