import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';

const api = import.meta.env.VITE_API_URL;

// Async thunks for fetching profile data
// OPTIMIZED: Add selective state updates for better performance
export const fetchProfileInfo = createAsyncThunk(
  'profile/fetchProfileInfo',
  async (options = {}, { rejectWithValue, getState }) => {
    try {
      // Get current state
      const state = getState();
      const profileInfo = state?.profile?.profileInfo;
      const forceRefresh = options?.forceRefresh || false;
      
      // Skip redundant fetches
      if (profileInfo?.id && !forceRefresh) {
        // Check if data is still fresh (within 5 minutes)
        const lastFetchTime = state?.profile?.lastFetch || 0;
        const isFresh = Date.now() - lastFetchTime < 5 * 60 * 1000;
        
        if (isFresh) {
          console.log('Using cached profile data (fresh)');
          return {
            ...profileInfo,
            _fromCache: true
          };
        }
        
        console.log('Cached data stale, fetching fresh profile data');
      }
      
      // Use AbortController to allow cancelling requests
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);
      
      console.log('Fetching fresh profile data from server');
      const { data } = await axios.get(`${api}/user/profile-info`, {
        withCredentials: true,
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (data.user) {
        return {
          id: data.user.id,
          fullName: `${data.user.firstName} ${data.user.lastName}`,
          verified: data.user.Verified,
          badges: data.user.badges || {},
          username: data.user.username,
          bio: data.user.Bio || "",
          posts: data.user.posts || 0,
          followers: data.user.followers || 0,
          following: data.user.following || 0,
          socialLinks: JSON.parse(data.user.SocialMedia || "{}"),
          profilePicture: data.user.profilePicture,
          coverImage: data.user.coverImage || "",
          _fromCache: false
        };
      }
      return null;
    } catch (error) {
      console.error("Error fetching profile data:", error.message);
      
      // Handle specific error scenarios better
      if (error.name === 'AbortError') {
        return rejectWithValue('Request timeout, please try again');
      }
      
      // Get current state to check if we have cached data to fall back to
      const state = getState();
      const { profileInfo } = state.profile || {};
      
      // If we have cached data and the error is network-related, use cached data
      if (profileInfo?.id && (error.message.includes('Network') || !navigator.onLine)) {
        console.log('Network error occurred - using cached profile data');
        return {
          ...profileInfo,
          _fromCache: true,
          _offlineMode: true
        };
      }
      
      return rejectWithValue(error.response?.data || error.message || 'Failed to load profile data');
    }
  }
);

// Similarly update fetchUserPosts with a forceRefresh parameter
export const fetchUserPosts = createAsyncThunk(
  'profile/fetchUserPosts',
  async (userId, { rejectWithValue, getState }) => {
    try {
      console.log('Fetching posts data from server for userId:', userId);
      const response = await axios.get(
        `${api}/post/post/details/${userId}?isShort=false`,
        { withCredentials: true }
      );
      return response.data || [];
    } catch (error) {
      console.error("Error fetching posts:", error.message);
      
      // Get current state to check if we have cached data to fall back to
      const state = getState();
      const { userPosts } = state.profile || {};
      
      // If we have cached posts and the error is network-related, use cached data
      if (userPosts?.length > 0 && (error.message.includes('Network') || !navigator.onLine)) {
        console.log('Network error occurred - using cached posts data');
        return userPosts;
      }
      
      return rejectWithValue(error.response?.data || error.message || 'Failed to load posts');
    }
  }
);

// Update fetchUserShorts to always fetch fresh data
export const fetchUserShorts = createAsyncThunk(
  'profile/fetchUserShorts',
  async (userId, { rejectWithValue }) => {
    try {
      console.log('Fetching shorts data from server for userId:', userId);
      const response = await axios.get(
        `${api}/post/post/details/${userId}?isShort=true`,
        { withCredentials: true }
      );
      return response.data || [];
    } catch (error) {
      return rejectWithValue(error.response?.data || 'Failed to load shorts');
    }
  }
);

export const fetchMoreContent = createAsyncThunk(
  'profile/fetchMoreContent',
  async ({ isShort, lastItemId }, { rejectWithValue }) => {
    try {
      const response = await axios.post(
        `${api}/post/more-posts`,
        { isShort, postId: lastItemId },
        { withCredentials: true }
      );
      return { 
        isShort, 
        posts: response.data?.posts || [] 
      };
    } catch (error) {
      return rejectWithValue(error.response?.data || `Failed to load more ${isShort ? 'shorts' : 'posts'}`);
    }
  }
);

export const toggleLikePost = createAsyncThunk(
  'profile/toggleLikePost',
  async (params, { rejectWithValue }) => {
    const { postId, finalState, action } = typeof params === 'object' 
      ? params 
      : { postId: params, finalState: null, action: null };
      
    try {
      const api = import.meta.env.VITE_API_URL;
      
      // Make the API call with action parameter
      const response = await axios.post(
        `${api}/user-interactions/like/${postId}`, 
        { action: action || (finalState ? 'like' : 'unlike') }, 
        { withCredentials: true }
      );
      
      // Return the likesCount from the API response
      return { 
        postId, 
        newState: finalState,
        likesCount: response.data.likesCount
      };
    } catch (error) {
      console.error('Error toggling like:', error);
      return rejectWithValue(error.response?.data || 'Failed to toggle like');
    }
  }
);

// Toggle save on a post with debouncing managed at component level
export const toggleSavePost = createAsyncThunk(
  'profile/toggleSavePost',
  async (params, { rejectWithValue }) => {
    const { postId, finalState, action } = typeof params === 'object' 
      ? params 
      : { postId: params, finalState: null, action: null };
      
    try {
      const response = await axios.post(
        `${api}/user-interactions/save/${postId}`,
        { action: action || (finalState ? 'save' : 'unsave') },
        { withCredentials: true }
      );
      
      // Return the result properly
      return { 
        postId, 
        success: !!response.data.success, 
        newState: finalState,
        action: response.data.action
      };
    } catch (error) {
      console.error('Error toggling save status:', error);
      // Silent failure - don't show toast since visual state is preserved regardless
      return rejectWithValue(error.response?.data || 'Failed to toggle save status');
    }
  }
);


export const deletePost = createAsyncThunk(
  'profile/deletePost',
  async (postId, { rejectWithValue }) => {
    try {
      // Fix: Changed API endpoint from /post/delete/${postId} to /post/${postId}
      // to match the actual server endpoint
      const response = await axios.delete(`${api}/post/${postId}`, {
        withCredentials: true
      });
      
      if (response.data.success) {
        return { postId };
      }
      return rejectWithValue('Failed to delete post');
    } catch (error) {
      console.error('Error deleting post:', error);
      return rejectWithValue(error.response?.data || 'Failed to delete post');
    }
  }
);

// Initial state for the profile slice
const initialState = {
  profileInfo: null,
  userPosts: [],
  userShorts: null, // null means not loaded yet
  likedPosts: {},
  savedPosts: {},
  expandedTexts: {},
  shortMediaIndexes: {},
  playingVideos: {},
  loading: false,
  postsLoading: false,
  shortsLoading: false,
  loadingMore: false,
  hasMorePosts: true,
  hasMoreShorts: true,
  error: null,
  lastFetch: null
};

// Create a new reducer action to handle REHYDRATE event specially
const profileSlice = createSlice({
  name: 'profile',
  initialState,
  reducers: {
    toggleExpandText: (state, action) => {
      const postId = action.payload;
      state.expandedTexts[postId] = !state.expandedTexts[postId];
    },
    setShortMediaIndex: (state, action) => {
      const { postId, index } = action.payload;
      state.shortMediaIndexes[postId] = index;
    },
    setVideoPlaying: (state, action) => {
      const { postId, videoUrl, isPlaying } = action.payload;
      const videoKey = `${postId}-${videoUrl}`;
      if (isPlaying) {
        state.playingVideos[videoKey] = true;
      } else {
        delete state.playingVideos[videoKey];
      }
    },
    resetProfileState: () => initialState,
   
    // Add a new action to explicitly force refresh data when needed
    forceRefreshProfileData: (state) => {
      // Just mark the state as needing refresh, the component will handle the actual fetch
      state._needsRefresh = true;
    },
    
    // Add a utility function to perform shallow comparison
    // to avoid unnecessary state updates
    updateStateIfDifferent: (state, action) => {
      const { path, value } = action.payload;
      const pathParts = path.split('.');
      let currentObj = state;
      let currentValue = state;
      
      // Navigate to the target property
      for (let i = 0; i < pathParts.length; i++) {
        const part = pathParts[i];
        if (i === pathParts.length - 1) {
          // If the target value is different, update it
          if (JSON.stringify(currentObj[part]) !== JSON.stringify(value)) {
            currentObj[part] = value;
          }
          break;
        }
        
        if (!currentObj[part]) {
          currentObj[part] = {};
        }
        
        currentObj = currentObj[part];
        currentValue = currentValue[part];
      }
    }
  },
  extraReducers: (builder) => {
    builder
      // Handle fetchProfileInfo
      .addCase(fetchProfileInfo.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      
      .addCase(fetchProfileInfo.fulfilled, (state, action) => {
        state.loading = false;
        state.profileInfo = action.payload;
        state.lastFetch = Date.now();
      })
      .addCase(fetchProfileInfo.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload || 'Failed to fetch profile data';
      })
      
      // Handle fetchUserPosts
      .addCase(fetchUserPosts.pending, (state) => {
        state.postsLoading = true;
        state.error = null;
      })
      .addCase(fetchUserPosts.fulfilled, (state, action) => {
        state.postsLoading = false;
        state.userPosts = action.payload;
        state.hasMorePosts = action.payload && action.payload.length === 9;
        
        // Initialize liked and saved posts
        if (action.payload && action.payload.length > 0) {
          action.payload.forEach(post => {
            if (post.interactions) {
              state.likedPosts[post.id] = post.interactions.liked || false;
              state.savedPosts[post.id] = post.interactions.saved || false;
            }
          });
        }
        
        if (!state.lastFetch) {
          state.lastFetch = Date.now();
        }
      })
      .addCase(fetchUserPosts.rejected, (state, action) => {
        state.postsLoading = false;
        state.error = action.payload || 'Failed to fetch user posts';
      })
      
      // Handle fetchUserShorts
      .addCase(fetchUserShorts.pending, (state) => {
        state.shortsLoading = true;
        state.error = null;
      })
      .addCase(toggleLikePost.fulfilled, (state, action) => {
        const { postId, newState, likesCount } = action.payload;
        
        // Set the liked status in the state
        state.likedPosts[postId] = newState;
        
        // Find and update only the specific post in userPosts
        const postIndex = state.userPosts.findIndex(post => post.id === postId);
        if (postIndex !== -1) {
          state.userPosts[postIndex].likes = likesCount !== undefined
            ? likesCount
            : state.userPosts[postIndex].likes;
        }
        
        // Do the same for shorts if they exist
        if (state.userShorts) {
          const shortIndex = state.userShorts.findIndex(short => short.id === postId);
          if (shortIndex !== -1) {
            state.userShorts[shortIndex].likes = likesCount !== undefined
              ? likesCount
              : state.userShorts[shortIndex].likes;
          }
        }
      })
      .addCase(fetchUserShorts.fulfilled, (state, action) => {
        state.shortsLoading = false;
        // Always set userShorts to the payload, even if it's an empty array
        // This ensures we can distinguish between "not loaded" (null) and "loaded but empty" ([])
        state.userShorts = action.payload || [];
        state.hasMoreShorts = action.payload && action.payload.length === 9;
        
        // Initialize liked and saved posts for shorts
        if (action.payload && action.payload.length > 0) {
          action.payload.forEach(post => {
            if (post.interactions) {
              state.likedPosts[post.id] = post.interactions.liked || false;
              state.savedPosts[post.id] = post.interactions.saved || false;
            }
          });
        }
      })
      .addCase(fetchUserShorts.rejected, (state, action) => {
        state.shortsLoading = false;
        state.error = action.payload || 'Failed to fetch user shorts';
      })
      
      // Handle fetchMoreContent
      .addCase(fetchMoreContent.pending, (state) => {
        state.loadingMore = true;
        state.error = null;
      })
      .addCase(fetchMoreContent.fulfilled, (state, action) => {
        state.loadingMore = false;
        const { isShort, posts } = action.payload;
        
        if (posts.length > 0) {
          // Add the new posts to either userPosts or userShorts
          if (isShort) {
            state.userShorts = [...state.userShorts, ...posts];
            state.hasMoreShorts = posts.length === 9;
          } else {
            state.userPosts = [...state.userPosts, ...posts];
            state.hasMorePosts = posts.length === 9;
          }
          
          // Update liked and saved posts
          posts.forEach(post => {
            if (post.interactions) {
              state.likedPosts[post.id] = post.interactions.liked || false;
              state.savedPosts[post.id] = post.interactions.saved || false;
            }
          });
        } else {
          // No more posts to load
          if (isShort) {
            state.hasMoreShorts = false;
          } else {
            state.hasMorePosts = false;
          }
        }
      })
      .addCase(fetchMoreContent.rejected, (state, action) => {
        state.loadingMore = false;
        state.error = action.payload || 'Failed to fetch more content';
        // On error, assume no more content
        if (action.meta.arg.isShort) {
          state.hasMoreShorts = false;
        } else {
          state.hasMorePosts = false;
        }
      })
      
// In extraReducers section of profileSlice
.addCase(toggleSavePost.fulfilled, (state, action) => {
  const { postId, newState } = action.payload;
  state.savedPosts[postId] = newState;
})
      
      // Handle deletePost
      .addCase(deletePost.fulfilled, (state, action) => {
        const { postId } = action.payload;
        
        // Remove the post from both arrays
        state.userPosts = state.userPosts.filter(post => post.id !== postId);
        if (state.userShorts) {
          state.userShorts = state.userShorts.filter(post => post.id !== postId);
        }
        
        // Update the profile post count
        if (state.profileInfo) {
          state.profileInfo.posts = Math.max(0, state.profileInfo.posts - 1);
        }
        
        // Clean up related state
        delete state.likedPosts[postId];
        delete state.savedPosts[postId];
        delete state.expandedTexts[postId];
        delete state.shortMediaIndexes[postId];
        
        // Clean up any video playback states for this post
        Object.keys(state.playingVideos).forEach(key => {
          if (key.startsWith(`${postId}-`)) {
            delete state.playingVideos[key];
          }
        });
      })
      
      // OPTIMIZED: Make deleteShort action more efficient
      .addCase('profile/removeUserPost', (state, action) => {
        const postId = action.payload;
        
        // Check if the post exists before filtering (avoid unnecessary work)
        const postInPosts = state.userPosts.some(post => post.id === postId);
        const postInShorts = state.userShorts?.some(short => short.id === postId);
        
        // Only update arrays if needed
        if (postInPosts) {
          state.userPosts = state.userPosts.filter(post => post.id !== postId);
        }
        
        if (postInShorts && state.userShorts) {
          state.userShorts = state.userShorts.filter(short => short.id !== postId);
        }
        
        // Update profile post count only if a post was actually removed
        if ((postInPosts || postInShorts) && state.profileInfo) {
          state.profileInfo.posts = Math.max(0, state.profileInfo.posts - 1);
        }
        
        // Clean up related state if the post existed
        if (postInPosts || postInShorts) {
          delete state.likedPosts[postId];
          delete state.savedPosts[postId];
          delete state.expandedTexts[postId];
          delete state.shortMediaIndexes[postId];
          
          // Clean up any video playback states for this post
          Object.keys(state.playingVideos || {}).forEach(key => {
            if (key.startsWith(`${postId}-`)) {
              delete state.playingVideos[key];
            }
          });
        }
      })
      
      // OPTIMIZED: Rehydrate with careful state merging
      .addCase('persist/REHYDRATE', (state, action) => {
        if (action.payload && action.payload.profile) {
          console.log("Rehydrating profile state from storage");
          
          // Selectively merge state to avoid resetting everything
          return {
            ...state,
            profileInfo: action.payload.profile.profileInfo,
            userPosts: action.payload.profile.userPosts || [],
            userShorts: action.payload.profile.userShorts,
            likedPosts: action.payload.profile.likedPosts || {},
            savedPosts: action.payload.profile.savedPosts || {},
            expandedTexts: action.payload.profile.expandedTexts || {},
            shortMediaIndexes: action.payload.profile.shortMediaIndexes || {},
            // Reset mutable/transient state
            loading: false,
            postsLoading: false,
            shortsLoading: false,
            loadingMore: false,
            error: null,
            _rehydrated: true,
            lastFetch: action.payload.profile.lastFetch || null
          };
        }
        return state;
      });
  }
});

export const { 
  toggleExpandText, 
  setShortMediaIndex, 
  setVideoPlaying,
  resetProfileState,
  updateLastFetch,
  forceRefreshProfileData, // Export the new action
  updateStateIfDifferent // Export the new utility function
} = profileSlice.actions;

export default profileSlice.reducer;
