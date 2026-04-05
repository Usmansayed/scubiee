// filepath: /c:/Users/usman/Videos/Real Projects/client/src/Slices/WidgetSlice.js
import { createSlice } from '@reduxjs/toolkit';

const initialState = {
  showWidget: false,
  postContent: null,
  parentId: null,
  storyPostId: null,
  isCommentOpen: false,
  stories: [],
  storiesLoading: false,
  selectedUserId: null,
  showDisplayStory: false,
  prefetchedUserIds: [], // Track which users' stories have been prefetched
  viewedStoryIds: [], // Track which stories have been viewed
  lastStoriesFetch: null, // New field to track when stories were last fetched
  storiesExpiry: 3600000, // Stories expire after 1 hour (in milliseconds)
  // Updated form fields
  formData: null,
  showCategorySelector: false,
  selectedCategories: [],
  formType: null, // 'post' or 'short' to track which form is being submitted
};

const widgetSlice = createSlice({
  name: 'widget',
  initialState,
  reducers: {
    setShowWidget: (state, action) => {
      state.showWidget = action.payload;
      // Reset form-related states if closing widget
      if (!action.payload) {
        state.formData = null;
        state.showCategorySelector = false;
        state.selectedCategories = [];
        state.formType = null;
      }
    },
    setPostContent: (state, action) => {
      state.postContent = action.payload;
    },
    setParentId: (state, action) => {
      state.parentId = action.payload;
    },
    setStoryPostId: (state, action) => {
      state.storyPostId = action.payload;
    },
    setIsCommentOpen: (state, action) => {
      state.isCommentOpen = action.payload;
    },
    setStories: (state, action) => {
      state.stories = action.payload;
      state.lastStoriesFetch = Date.now(); // Record the time when stories were fetched
    },
    setStoriesLoading: (state, action) => {
      state.storiesLoading = action.payload;
    },
    setSelectedUserId: (state, action) => {
      state.selectedUserId = action.payload;
    },
    setShowDisplayStory: (state, action) => {
      state.showDisplayStory = action.payload;
    },
    addPrefetchedUserId: (state, action) => {
      if (!state.prefetchedUserIds.includes(action.payload)) {
        state.prefetchedUserIds.push(action.payload);
      }
    },
    updateStoryViewed: (state, action) => {
      const { userId, storyId } = action.payload;
      
      // Add to viewed story IDs array
      if (!state.viewedStoryIds.includes(storyId)) {
        state.viewedStoryIds.push(storyId);
      }
      
      // Update the story in the stories array
      const userIndex = state.stories.findIndex(user => user.userId === userId);
      if (userIndex !== -1) {
        const storyIndex = state.stories[userIndex].stories.findIndex(story => story.storyId === storyId);
        if (storyIndex !== -1) {
          state.stories[userIndex].stories[storyIndex].viewed = true;
          
          // If all stories are now viewed, update viewedAll flag
          if (state.stories[userIndex].stories.every(story => story.viewed)) {
            state.stories[userIndex].viewedAll = true;
          }
        }
      }
    },
    // Updated setFormData to handle the new structure
    setFormData: (state, action) => {
      state.formData = action.payload;
    },
    setShowCategorySelector: (state, action) => {
      state.showCategorySelector = action.payload;
    },
    setSelectedCategories: (state, action) => {
      state.selectedCategories = action.payload;
    },
    setFormType: (state, action) => {
      state.formType = action.payload;
    },
    resetForm: (state) => {
      state.formData = null;
      state.showCategorySelector = false;
      state.selectedCategories = [];
      state.formType = null;
    },
    resetStoryViews: (state) => {
      state.viewedStoryIds = [];
    },
    // Update the setStoriesNeedRefresh reducer to be smarter about offline state
    setStoriesNeedRefresh: (state, action) => {
      const forceRefresh = action.payload;
      const isOffline = !navigator.onLine;
      
      // If we're offline, don't clear stories regardless of age
      if (isOffline) {
        return; // Keep using cached stories when offline
      }
      
      // Only refresh if online and either forced or expired
      if (forceRefresh || 
          !state.lastStoriesFetch || 
          Date.now() - state.lastStoriesFetch > state.storiesExpiry) {
        state.stories = [];
        state.prefetchedUserIds = [];
      }
    },
    // Add a new reducer to handle adding a created story
    addCreatedStory: (state, action) => {
      const { userId, storyData } = action.payload;
      
      // Find if the user already exists in stories array
      const userIndex = state.stories.findIndex(user => String(user.userId) === String(userId));
      
      if (userIndex !== -1) {
        // User already exists, update their story status and count
        state.stories[userIndex].hasStories = true;
        state.stories[userIndex].viewedAll = false;
        state.stories[userIndex].storyCount = (state.stories[userIndex].storyCount || 0) + 1;
        
        // If stories array exists, add the new story
        if (state.stories[userIndex].stories && Array.isArray(state.stories[userIndex].stories)) {
          state.stories[userIndex].stories.unshift(storyData);
        } else {
          // Initialize stories array if it doesn't exist
          state.stories[userIndex].stories = [storyData];
        }
      } else if (userId) {
        // User doesn't exist in stories, add them with the new story
        // This should only happen if there's a mismatch between server and client data
        // In practice, the user should always exist in the stories array
        console.warn('User not found in stories array when adding created story');
      }

      // We also need to ensure the prefetchedUserIds includes the user
      if (!state.prefetchedUserIds.includes(userId)) {
        state.prefetchedUserIds.push(userId);
      }
    },
  },
});

export const { 
  setShowWidget, 
  setPostContent, 
  setParentId, 
  setStoryPostId, 
  setIsCommentOpen, 
  setStories, 
  setStoriesLoading,
  setSelectedUserId,
  setShowDisplayStory,
  addPrefetchedUserId,
  updateStoryViewed,
  setFormData, 
  setShowCategorySelector, 
  setSelectedCategories,
  setFormType,
  resetForm,
  resetStoryViews,
  setStoriesNeedRefresh,
  addCreatedStory
} = widgetSlice.actions;

export default widgetSlice.reducer;