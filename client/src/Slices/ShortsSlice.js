import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';

// Add a new thunk to check for new shorts
export const checkForNewShorts = createAsyncThunk(
  'shorts/checkForNewShorts',
  async (_, { dispatch }) => {
    // Force clear and refresh shorts feed
    dispatch(clearShortsFeed());
    return dispatch(fetchShortsFeed()).unwrap();
  }
);

// Thunk for fetching initial shorts feed
export const fetchShortsFeed = createAsyncThunk(
  'shorts/fetchShortsFeed',
  async (params = {}, { rejectWithValue, signal, getState }) => {
    try {
      const api = import.meta.env.VITE_API_URL;
      
      // Get current state to check if we should force refresh
      const { forceRefresh } = params;
      const state = getState().shorts;
      
      // Create a timeout that will abort the request after 10 seconds
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      
      // Connect redux-thunk signal to our controller
      if (signal) {
        signal.addEventListener('abort', () => {
          controller.abort();
          clearTimeout(timeoutId);
        });
      }
      
      try {
        // Add firstShortId to the request parameters if it's provided
        const { firstShortId } = params;
        const queryParams = {};
        
        if (firstShortId) {
          console.log(`Including firstShortId ${firstShortId} in request`);
          queryParams.firstShortId = firstShortId;
        }
        
        // Add the new hybrid fetch parameters
        if (state.lastSeenShortTimestamp && !forceRefresh) {
          console.log(`Including lastSeenShortTimestamp: ${state.lastSeenShortTimestamp}`);
          queryParams.lastSeenShortTimestamp = state.lastSeenShortTimestamp;
          queryParams.mode = params.mode || state.recommendedMode || 'hybrid';
        }
        
        // Add a cache-busting parameter if forceRefresh is true
        if (forceRefresh) {
          queryParams._t = Date.now();
          queryParams.mode = 'hybrid'; // Reset to hybrid mode on forced refresh
        }
        
        const response = await axios.get(`${api}/post/shorts-feed`, {
          params: queryParams,
          withCredentials: true,
          signal: controller.signal,
          timeout: 10000
        });
        
        clearTimeout(timeoutId);
        
        // Validate response data
        if (!response.data || !response.data.shorts) {
          return rejectWithValue({
            error: 'Invalid response format from server',
            status: 'INVALID_RESPONSE'
          });
        }
        
        return response.data;
      } catch (error) {
        clearTimeout(timeoutId);
        throw error;
      }
    } catch (error) {
      console.error('Error in fetchShortsFeed thunk:', error);
      
      if (error.name === 'AbortError' || error.code === 'ECONNABORTED') {
        return rejectWithValue({
          error: 'Request timed out. Please try again.',
          status: 'TIMEOUT'
        });
      }
      
      // Handle network errors separately
      if (!navigator.onLine || error.message === 'Network Error') {
        return rejectWithValue({
          error: 'You appear to be offline. Please check your internet connection.',
          status: 'OFFLINE'
        });
      }
      
      return rejectWithValue(error.response?.data || {
        error: error.message || 'Failed to fetch shorts feed',
        status: error.code || 'UNKNOWN_ERROR'
      });
    }
  }
);

// Thunk for loading more shorts (pagination)
export const fetchMoreShorts = createAsyncThunk(
  'shorts/fetchMoreShorts',
  async (pagination, { rejectWithValue, signal, getState }) => {
    try {
      const api = import.meta.env.VITE_API_URL;
      const { lastScore, lastCreatedAt, lastSeenShortTimestamp } = pagination;
      const state = getState().shorts;
      
      // Create a timeout that will abort the request after 10 seconds
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      
      // Connect redux-thunk signal to our controller
      if (signal) {
        signal.addEventListener('abort', () => {
          controller.abort();
          clearTimeout(timeoutId);
        });
      }
      
      try {
        const response = await axios.get(`${api}/post/shorts-feed`, {
          params: { 
            lastScore, 
            lastCreatedAt, 
            lastSeenShortTimestamp: lastSeenShortTimestamp || state.lastSeenShortTimestamp,
            limit: 10,
            mode: pagination.mode || state.recommendedMode || 'hybrid'
          },
          withCredentials: true,
          signal: controller.signal,
          timeout: 10000
        });
        
        clearTimeout(timeoutId);
        return response.data;
      } catch (error) {
        clearTimeout(timeoutId);
        throw error;
      }
    } catch (error) {
      if (error.name === 'AbortError' || error.code === 'ECONNABORTED') {
        return rejectWithValue({
          error: 'Request timed out. Please try again.',
          status: 'TIMEOUT'
        });
      }
      return rejectWithValue(error.response?.data || {
        error: 'Failed to fetch more shorts',
        status: error.code || 'UNKNOWN_ERROR'
      });
    }
  }
);

// Add deleteShort thunk
export const deleteShort = createAsyncThunk(
  'shorts/deleteShort',
  async (shortId, { rejectWithValue }) => {
    try {
      const api = import.meta.env.VITE_API_URL;
      const response = await axios.delete(`${api}/post/${shortId}`, {
        withCredentials: true
      });
      
      if (response.data.success) {
        return { shortId };
      }
      return rejectWithValue('Failed to delete short');
    } catch (error) {
      console.error('Error deleting short:', error);
      return rejectWithValue(error.response?.data || 'Failed to delete short');
    }
  }
);

export const toggleLikePost = createAsyncThunk(
  'shorts/toggleLikePost',
  async (params, { rejectWithValue, getState }) => {
    const { postId, finalState, action } = typeof params === 'object' 
      ? params 
      : { postId: params, finalState: null, action: null };
      
    try {
      const api = import.meta.env.VITE_API_URL;
      
      // If finalState is provided, use it; otherwise toggle current state
      const state = getState();
      const currentLiked = state.shorts.likedShorts[postId] || false;
      const targetState = finalState !== null ? finalState : !currentLiked;
      
      // Make the API call with explicit action parameter
      const response = await axios.post(
        `${api}/user-interactions/like/${postId}`, 
        { action: action || (targetState ? 'like' : 'unlike') }, 
        { withCredentials: true }
      );
      
      // Return the likesCount from the API response
      return { 
        postId, 
        newState: targetState,
        likesCount: response.data.likesCount
      };
    } catch (error) {
      return rejectWithValue(error.response?.data || 'Failed to toggle like');
    }
  }
);
const shortsSlice = createSlice({
  name: 'shorts',
  initialState: {
    shorts: [],
    currentShortIndex: 0,
    pagination: {
      hasMore: true,
      nextCursor: null
    },
    loading: false,
    loadingMore: false,
    error: null,
    currentUserId: null,
    lastFetched: null,
    lastUpdated: null,
    lastSeenShortTimestamp: null, // Add this to track when user last saw shorts
    recommendedMode: 'hybrid',    // Track recommended mode for next fetch
    contentStats: {              // Track the different types of content
      fresh: 0,
      standardUnviewed: 0,
      viewed: 0
    },
    likedShorts: {}, // Add this to track liked shorts separate from the shorts array
    isOnline: navigator.onLine // Add online status tracking
  },
  reducers: {
    setCurrentShortIndex: (state, action) => {
      const newIndex = action.payload;
      if (newIndex >= 0 && newIndex < state.shorts.length) {
        state.currentShortIndex = newIndex;
      }
    },
    setCurrentUser: (state, action) => {
      state.currentUserId = action.payload;
    },
    resetShortsError: (state) => {
      state.error = null;
    },
    updateShortInteraction: (state, action) => {
      const { shortId, type, value, likesCount } = action.payload;
      const shortIndex = state.shorts.findIndex(short => short.id === shortId);
      
      if (shortIndex !== -1) {
        // Ensure userInteraction exists
        if (!state.shorts[shortIndex].userInteraction) {
          state.shorts[shortIndex].userInteraction = {};
        }
        
        if (type === 'like') {
          state.shorts[shortIndex].userInteraction.liked = value;
          state.likedShorts[shortId] = value; // Update the separate tracking state
          
          // Use the provided likesCount if available, otherwise calculate
          if (likesCount !== undefined) {
            state.shorts[shortIndex].likes = likesCount;
          } else {
            // Update likes count based on action
            state.shorts[shortIndex].likes = value 
              ? (state.shorts[shortIndex].likes || 0) + 1 
              : Math.max(0, (state.shorts[shortIndex].likes || 0) - 1);
          }
        }
        else if (type === 'save') {
          state.shorts[shortIndex].userInteraction.saved = value;
        }
        else if (type === 'follow') {
          // Get the author ID of the current short
          const authorId = state.shorts[shortIndex].author.id;
          
          // Prevent self-follow: check if author is the current user
          if (authorId === state.currentUserId) {
            return;
          }
          
          // Update isFollowing for all shorts by the same author
          state.shorts.forEach(short => {
            if (short.author?.id === authorId) {
              if (!short.userInteraction) {
                short.userInteraction = {};
              }
              short.userInteraction.isFollowing = value;
            }
          });
        }
      }
    },
    validateCurrentIndex: (state) => {
      // Safety check to ensure currentShortIndex is valid
      if (state.shorts.length === 0) {
        state.currentShortIndex = 0;
      } else if (state.currentShortIndex >= state.shorts.length) {
        state.currentShortIndex = state.shorts.length - 1;
      }
    },
    // Update the clearShortsFeed action to reset timestamps
    clearShortsFeed: (state) => {
      state.shorts = [];
      state.currentShortIndex = 0;
      state.pagination = {
        hasMore: true,
        nextCursor: null
      };
      state.error = null;
      state.lastFetched = null;
    },
    // Add a new action to mark when shorts content has been updated
    markShortsUpdated: (state) => {
      state.lastUpdated = Date.now();
    },
    // Add a new action to update lastSeenShortTimestamp manually
    updateLastSeenTimestamp: (state) => {
      state.lastSeenShortTimestamp = new Date().toISOString();
    },    // Add action to set recommended mode
    setRecommendedMode: (state, action) => {
      state.recommendedMode = action.payload;
    },
    // Set online status
    setOnlineStatus: (state, action) => {
      state.isOnline = action.payload;
    }
  },
  extraReducers: (builder) => {
    builder
      // Handle fetchShortsFeed
      .addCase(fetchShortsFeed.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchShortsFeed.fulfilled, (state, action) => {
        state.loading = false;
        // Remove duplicates by ID
        const uniqueShorts = [];
        const seenIds = new Set();
        for (const short of (action.payload.shorts || [])) {
          if (!seenIds.has(short.id)) {
            uniqueShorts.push(short);
            seenIds.add(short.id);
          }
        }
        state.shorts = uniqueShorts;
        state.pagination = action.payload.pagination || { hasMore: false };
        state.currentShortIndex = 0;
        state.lastFetched = Date.now();
        // Store the last seen timestamp for tracking
        if (action.payload.pagination?.nextCursor?.lastSeenShortTimestamp) {
          state.lastSeenShortTimestamp = action.payload.pagination.nextCursor.lastSeenShortTimestamp;
        }
        
        // Store recommended mode for next fetch
        if (action.payload.pagination?.recommendedMode) {
          state.recommendedMode = action.payload.pagination.recommendedMode;
        }
        
        // Store content stats
        if (action.payload.stats) {
          state.contentStats = {
            fresh: action.payload.stats.totalFresh || 0,
            standardUnviewed: action.payload.stats.totalStandardUnviewed || 0,
            viewed: action.payload.stats.totalViewed || 0
          };
        }
        
        // Validate the state after receiving data
        if (state.shorts.length === 0) {
          state.error = "No shorts available right now";
        }
      })
      .addCase(fetchShortsFeed.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload || 'Failed to fetch shorts feed';
      })
      
      // Handle fetchMoreShorts
      .addCase(fetchMoreShorts.pending, (state) => {
        state.loadingMore = true;
      })
      .addCase(fetchMoreShorts.fulfilled, (state, action) => {
        state.loadingMore = false;
        // Merge and deduplicate shorts by ID
        const allShorts = [...state.shorts, ...(action.payload.shorts || [])];
        const uniqueShorts = [];
        const seenIds = new Set();
        for (const short of allShorts) {
          if (!seenIds.has(short.id)) {
            uniqueShorts.push(short);
            seenIds.add(short.id);
          }
        }
        state.shorts = uniqueShorts;
        state.pagination = action.payload.pagination;
        // Update the last seen timestamp for tracking
        if (action.payload.pagination?.nextCursor?.lastSeenShortTimestamp) {
          state.lastSeenShortTimestamp = action.payload.pagination.nextCursor.lastSeenShortTimestamp;
        }
        
        // Update recommended mode for next fetch
        if (action.payload.pagination?.recommendedMode) {
          state.recommendedMode = action.payload.pagination.recommendedMode;
        }
        
        // Update content stats
        if (action.payload.stats) {
          // Add to existing stats
          state.contentStats.fresh += action.payload.stats.totalFresh || 0;
          state.contentStats.standardUnviewed += action.payload.stats.totalStandardUnviewed || 0;
          state.contentStats.viewed += action.payload.stats.totalViewed || 0;
        }
      })
      .addCase(fetchMoreShorts.rejected, (state, action) => {
        state.loadingMore = false;
        state.error = action.payload || 'Failed to fetch more shorts';
      })
      
      // Add case for deleteShort
      .addCase(deleteShort.fulfilled, (state, action) => {
        const { shortId } = action.payload;
        
        // Remove the deleted short from the array
        state.shorts = state.shorts.filter(short => short.id !== shortId);
        
        // If we're at the end of the list, adjust currentShortIndex
        if (state.currentShortIndex >= state.shorts.length && state.currentShortIndex > 0) {
          state.currentShortIndex = Math.max(0, state.currentShortIndex - 1);
        }
      })
      
      .addCase(toggleLikePost.fulfilled, (state, action) => {
        const { postId, newState, likesCount } = action.payload;
        
        // Set the liked state in our separate tracking object
        state.likedShorts[postId] = newState;
        
        // Update the shorts array using the same pattern as profileSlice
        const updateLikesCount = (short) => {
          if (short.id === postId) {
            // Ensure userInteraction exists
            if (!short.userInteraction) {
              short.userInteraction = {};
            }
            
            // Update like status
            short.userInteraction.liked = newState;
            
            // Use the likesCount directly from the API response
            if (likesCount !== undefined) {
              return {
                ...short,
                likes: likesCount
              };
            } else {
              // Fallback to calculation if API doesn't return count
              const oldState = state.likedShorts[postId] === undefined ? false : state.likedShorts[postId];
              const likeDelta = newState === oldState ? 0 : (newState ? 1 : -1);
              
              return {
                ...short,
                likes: Math.max(0, (short.likes || 0) + likeDelta)
              };
            }
          }
          return short;
        };
        
        state.shorts = state.shorts.map(updateLikesCount);
        state._lastLikeUpdated = Date.now();
      })
  }
});

export const { 
  setCurrentShortIndex, 
  updateShortInteraction,
  setCurrentUser, 
  resetShortsError,
  validateCurrentIndex,
  clearShortsFeed,
  markShortsUpdated,
  updateLastSeenTimestamp,
  setRecommendedMode,
  setOnlineStatus
} = shortsSlice.actions;

export default shortsSlice.reducer;
