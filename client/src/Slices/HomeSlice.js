import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';
import { toast } from 'react-toastify';

const api = import.meta.env.VITE_API_URL;

// Fetch feed posts with pagination
export const fetchFeedPosts = createAsyncThunk(
  'home/fetchFeedPosts',
  async (page = 1, { rejectWithValue, getState }) => {
    try {
      const state = getState();
      const homePosts = state?.home?.posts;
      
      // If we're offline and have cached data, use the cache
      if (!navigator.onLine && homePosts?.length > 0) {
        console.log('Offline - using cached feed data');
        return {
          posts: homePosts,
          pagination: state.home.pagination,
          _fromCache: true
        };
      }
      
      console.log(`Fetching feed posts for page ${page}`);
      const response = await axios.get(`${api}/post/feed`, {
        params: { page, limit: 10 },
        withCredentials: true
      });
      
      // Process the posts to ensure all required fields are present
      const processedPosts = response.data.posts.map(post => {
        // Extract the userInteraction data if available
        const userInteraction = post.userInteraction || {};
        
        return {
          ...post,
          author: {
            ...post.author,
            followedByMe: userInteraction.isFollowing || false
          },
          interactions: {
            liked: userInteraction.liked || false,
            saved: userInteraction.saved || false
          }
        };
      });
      
      return {
        posts: processedPosts,
        pagination: response.data.pagination
      };
    } catch (error) {
      console.error('Error fetching feed:', error);
      
      // Get current state to check if we have cached data to fall back to
      const state = getState();
      const { posts } = state.home || {};
      
      // If we have cached data and the error is network-related, use cached data
      if (posts?.length > 0 && (error.message.includes('Network') || !navigator.onLine)) {
        console.log('Network error occurred - using cached feed data');
        return {
          posts,
          pagination: state.home.pagination,
          _fromCache: true,
          _offlineMode: true
        };
      }
      
      return rejectWithValue(error.response?.data || error.message || 'Failed to load feed');
    }
  }
);

// Load more posts (next page)
export const loadMorePosts = createAsyncThunk(
  'home/loadMorePosts',
  async (_, { getState, rejectWithValue, dispatch }) => {
    try {
      const state = getState();
      const { pagination, posts } = state.home;
      
      // If we're at the last page, don't try to fetch more
      if (!pagination.hasMore) {
        return { posts: [], pagination: { ...pagination, hasMore: false } };
      }
      
      // Collect all existing post IDs to avoid duplicates
      const existingPostIds = posts.map(post => post.id).join(',');
      
      const response = await axios.get(`${api}/post/feed`, {
        params: {
          page: pagination.nextPage,
          excludeIds: existingPostIds, // Send existing IDs to exclude
          limit: 10 // Ensure consistent page size
        },
        withCredentials: true
      });

      // Return response data with additional flag
      return {
        ...response.data,
        _isLoadMoreOperation: true // Flag to identify this as a loadMore operation
      };
    } catch (error) {
      return rejectWithValue(error.response?.data?.error || 'Failed to load more posts');
    }
  }
);

export const toggleLikePost = createAsyncThunk(
  'home/toggleLikePost',
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
  'home/toggleSavePost',
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

// Delete post
export const deletePost = createAsyncThunk(
  'home/deletePost',
  async (postId, { rejectWithValue }) => {
    try {
      // Fix the API endpoint to match the correct route in server/routes/Post.js
      const response = await axios.delete(`${api}/post/${postId}`, {
        withCredentials: true
      });
      
      if (response.data.success) {
        toast.success("Post deleted successfully");
        return { postId };
      }
      return rejectWithValue('Failed to delete post');
    } catch (error) {
      console.error('Error deleting post:', error);
      toast.error("Failed to delete post");
      return rejectWithValue(error.response?.data || 'Failed to delete post');
    }
  }
);

// Add a new async thunk for fetching suggested users
export const fetchSuggestedUsers = createAsyncThunk(
  'home/fetchSuggestedUsers',
  async (limit = 5, { rejectWithValue, getState }) => {
    try {
      const state = getState();
      const suggestedUsers = state?.home?.suggestedUsers;
      
      // If we're offline and have cached data, use the cache
      if (!navigator.onLine && suggestedUsers?.length > 0) {
        console.log('Offline - using cached suggested users');
        return {
          suggestions: suggestedUsers,
          _fromCache: true
        };
      }
      
      console.log(`Fetching suggested users with limit ${limit}`);
      const response = await axios.get(`${api}/user/suggestions`, {
        params: { limit },
        withCredentials: true
      });
      
      return {
        suggestions: response.data.suggestions,
        success: response.data.success
      };
    } catch (error) {
      console.error('Error fetching suggested users:', error);
      
      // Get current state to check if we have cached data to fall back to
      const state = getState();
      const { suggestedUsers } = state.home || {};
      
      // If we have cached data and the error is network-related, use cached data
      if (suggestedUsers?.length > 0 && (error.message.includes('Network') || !navigator.onLine)) {
        console.log('Network error occurred - using cached suggested users');
        return {
          suggestions: suggestedUsers,
          _fromCache: true,
          _offlineMode: true
        };
      }
      
      return rejectWithValue(error.response?.data || error.message || 'Failed to load suggestions');
    }
  }
);

// Initial state
const initialState = {
  posts: [],
  likedPosts: {},
  savedPosts: {},
  expandedTexts: {},
  shortMediaIndexes: {},
  playingVideos: {},
  loading: false,
  loadingMore: false,
  error: null,
  pagination: {
    page: 1,
    limit: 10,
    totalCount: 0,
    totalPages: 0,
    hasMore: false
  },  isOnline: navigator.onLine,
  lastFetched: null,
  scrollPosition: null, // Store scroll position with metadata
  suggestedUsers: [],
  suggestionsLoading: false,
  suggestionsError: null,
  suggestionsLastFetched: null
};

// Create the home slice
const homeSlice = createSlice({
  name: 'home',
  initialState,
  reducers: {
    // Toggle text expansion for posts
    toggleExpandText(state, action) {
      const postId = action.payload;
      state.expandedTexts[postId] = !state.expandedTexts[postId];
    },
    
    // Update short media index
    setShortMediaIndex(state, action) {
      const { postId, index } = action.payload;
      state.shortMediaIndexes[postId] = index;
    },
    
    // Set video playing status
    setVideoPlaying(state, action) {
      const { postId, videoUrl, isPlaying } = action.payload;
      const videoKey = `${postId}-${videoUrl}`;
      
      if (isPlaying) {
        state.playingVideos[videoKey] = true;
      } else {
        delete state.playingVideos[videoKey];
      }
    },
    
    // Set online status
    setOnlineStatus(state, action) {
      state.isOnline = action.payload;
    },
    
    // Reset state
    resetHomeState() {
      return initialState;
    },
    
    // Add a new reducer to remove posts from unfollowed users
    removeUnfollowedUserPosts(state, action) {
      const userId = action.payload;
      // Filter out posts from the unfollowed user
      state.posts = state.posts.filter(post => post.author.id !== userId);
    },
      // Set scroll position with metadata
    setScrollPosition(state, action) {
      const { position, timestamp, postCount } = action.payload;
      state.scrollPosition = {
        position,
        timestamp,
        postCount,
        savedAt: Date.now()
      };
    },
    
    // Clear scroll position
    clearScrollPosition(state) {
      state.scrollPosition = null;
    },
    
    // Add a new reducer to clear suggested users if needed
    clearSuggestedUsers(state) {
      state.suggestedUsers = [];
      state.suggestionsLastFetched = null;
    },
  },
  extraReducers: (builder) => {
    builder
      // Handle fetchFeedPosts
      .addCase(fetchFeedPosts.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchFeedPosts.fulfilled, (state, action) => {
        state.loading = false;
        state.posts = action.payload.posts;
        state.pagination = action.payload.pagination;
        state.lastFetched = Date.now(); // Set the timestamp when posts were last fetched
        state._lastUpdated = Date.now();
        
        // Initialize liked and saved status from post interactions
        const newLikedPosts = {};
        const newSavedPosts = {};
        
        action.payload.posts.forEach(post => {
          // IMPORTANT: Make sure we capture the correct interaction state from each post
          newLikedPosts[post.id] = post.interactions?.liked || post.userInteraction?.liked || false;
          newSavedPosts[post.id] = post.interactions?.saved || post.userInteraction?.saved || false;
        });
        
        // Replace the current state entirely to ensure we don't have stale data
        state.likedPosts = newLikedPosts;
        state.savedPosts = newSavedPosts;
      })
      .addCase(fetchFeedPosts.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload || 'Failed to fetch feed';
      })
      
      // Handle loadMorePosts
      .addCase(loadMorePosts.pending, (state) => {
        state.loadingMore = true;
        state.error = null;
      })
      .addCase(loadMorePosts.fulfilled, (state, action) => {
        state.loadingMore = false;
        
        // Add new posts to existing posts
        state.posts = [...state.posts, ...action.payload.posts];
        state.pagination = action.payload.pagination;
        
        // Update liked and saved status for new posts
        if (action.payload.posts && action.payload.posts.length > 0) {
          const newLikedPosts = {};
          const newSavedPosts = {};
          
          action.payload.posts.forEach(post => {
            // Match the same structure as fetchFeedPosts for consistency
            newLikedPosts[post.id] = post.interactions?.liked || post.userInteraction?.liked || false;
            newSavedPosts[post.id] = post.interactions?.saved || post.userInteraction?.saved || false;
          });
          
          state.likedPosts = {...state.likedPosts, ...newLikedPosts};
          state.savedPosts = {...state.savedPosts, ...newSavedPosts};
        }
      })
      .addCase(loadMorePosts.rejected, (state, action) => {
        state.loadingMore = false;
        state.error = action.payload || 'Failed to load more posts';
      })
      
      // Handle toggleLikePost
      .addCase(toggleLikePost.fulfilled, (state, action) => {
        const { postId, newState, likesCount } = action.payload;
        
        // Set the liked status in the state
        state.likedPosts[postId] = newState;
        
        // Find and update the post in the posts array
        const postIndex = state.posts.findIndex(post => post.id === postId);
        if (postIndex !== -1) {
          state.posts[postIndex].likes = likesCount !== undefined 
            ? likesCount 
            : state.posts[postIndex].likes;
        }
      })
      
      // Handle toggleSavePost
      .addCase(toggleSavePost.fulfilled, (state, action) => {
        const { postId, newState } = action.payload;
        state.savedPosts[postId] = newState;
      })
      
      // Handle deletePost
      .addCase(deletePost.fulfilled, (state, action) => {
        const { postId } = action.payload;
        
        // Remove the post from posts array
        state.posts = state.posts.filter(post => post.id !== postId);
        
        // Clean up related state
        delete state.likedPosts[postId];
        delete state.savedPosts[postId];
        delete state.expandedTexts[postId];
        delete state.shortMediaIndexes[postId];
        
        // Clean up video playback states
        Object.keys(state.playingVideos).forEach(key => {
          if (key.startsWith(`${postId}-`)) {
            delete state.playingVideos[key];
          }
        });
      })
      
      // Handle removePost
      .addCase('home/removePost', (state, action) => {
        return {
          ...state,
          posts: state.posts.filter(post => post.id !== action.payload),
        };
      })
      
      // Handle fetchSuggestedUsers
      .addCase(fetchSuggestedUsers.pending, (state) => {
        state.suggestionsLoading = true;
        state.suggestionsError = null;
      })
      .addCase(fetchSuggestedUsers.fulfilled, (state, action) => {
        state.suggestionsLoading = false;
        state.suggestedUsers = action.payload.suggestions;
        state.suggestionsLastFetched = Date.now(); 
      })
      .addCase(fetchSuggestedUsers.rejected, (state, action) => {
        state.suggestionsLoading = false;
        state.suggestionsError = action.payload || 'Failed to fetch suggestions';
      });
  }
});

export const { 
  toggleExpandText, 
  setShortMediaIndex, 
  setVideoPlaying,
  setOnlineStatus,
  resetHomeState,
  removeUnfollowedUserPosts,
  setScrollPosition,
  clearScrollPosition,
  clearSuggestedUsers  // Export the new action
} = homeSlice.actions;

export default homeSlice.reducer;
