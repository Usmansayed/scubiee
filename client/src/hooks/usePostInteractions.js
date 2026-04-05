import { useState, useCallback } from 'react';
import { toast } from 'react-toastify';
import { postInteractionService } from '../services/postInteractionService';
import { useOptimisticUpdate } from './useOptimisticUpdate';

/**
 * Hook for managing post interactions with clean state management
 * 
 * @param {Object} initialState - Initial interaction states
 * @returns {Object} - Interaction state and handler functions
 */
export const usePostInteractions = (initialState = {}) => {
  // State for tracking interactions for each post/comment
  const [interactions, setInteractions] = useState({
    likes: initialState.likes || {},        // Post ID -> liked boolean
    likeCounts: initialState.likeCounts || {}, // Post ID -> count number
    saves: initialState.saves || {},        // Post ID -> saved boolean
    ...initialState
  });
  
  // Use optimistic update for liking posts
  const { performUpdate: performLikeUpdate, isUpdating: isLiking } = useOptimisticUpdate(
    postInteractionService.toggleLike,
    // Success callback
    (result, postId) => {
      console.log(`Like operation successful for ${postId}`);
    },
    // Error callback - revert on failure
    (error, postId, previousState) => {
      setInteractions(prev => ({
        ...prev,
        likes: {
          ...prev.likes,
          [postId]: previousState.liked
        },
        likeCounts: {
          ...prev.likeCounts,
          [postId]: previousState.count
        }
      }));
      toast.error("Failed to update like status");
    }
  );
  
  // Use optimistic update for saving posts
  const { performUpdate: performSaveUpdate, isUpdating: isSaving } = useOptimisticUpdate(
    postInteractionService.toggleSave,
    // Success callback
    (result, postId) => {
      console.log(`Save operation successful for ${postId}`);
    },
    // Error callback - revert on failure
    (error, postId, previousState) => {
      setInteractions(prev => ({
        ...prev,
        saves: {
          ...prev.saves,
          [postId]: previousState.saved
        }
      }));
      toast.error("Failed to update save status");
    }
  );
  
  // Handle like toggling
  const toggleLike = useCallback((postId) => {
    // Get current state for this post
    const isCurrentlyLiked = interactions.likes[postId] || false;
    const currentCount = interactions.likeCounts[postId] || 0;
    
    // Store previous state for potential rollback
    const previousState = {
      liked: isCurrentlyLiked,
      count: currentCount
    };
    
    // Update state optimistically
    setInteractions(prev => ({
      ...prev,
      likes: {
        ...prev.likes,
        [postId]: !isCurrentlyLiked
      },
      likeCounts: {
        ...prev.likeCounts,
        [postId]: isCurrentlyLiked 
          ? Math.max(0, currentCount - 1) 
          : currentCount + 1
      }
    }));
    
    // Perform actual update
    performLikeUpdate(previousState, postId);
  }, [interactions, performLikeUpdate]);
  
  // Handle save toggling
  const toggleSave = useCallback((postId) => {
    // Get current state for this post
    const isCurrentlySaved = interactions.saves[postId] || false;
    
    // Store previous state for potential rollback
    const previousState = {
      saved: isCurrentlySaved
    };
    
    // Update state optimistically
    setInteractions(prev => ({
      ...prev,
      saves: {
        ...prev.saves,
        [postId]: !isCurrentlySaved
      }
    }));
    
    // Perform actual update
    performSaveUpdate(previousState, postId)
      .then(() => {
        // Show toast only on successful save/unsave
        toast.success(isCurrentlySaved ? "Post removed from saved items" : "Post saved");
      })
      .catch(() => {
        // Error is handled by the optimistic update hook
      });
  }, [interactions, performSaveUpdate]);
  
  return {
    interactions,
    toggleLike,
    toggleSave,
    isLiking,
    isSaving,
    
    // Helper function to check if a post is liked
    isLiked: (postId) => interactions.likes[postId] || false,
    
    // Helper function to check if a post is saved
    isSaved: (postId) => interactions.saves[postId] || false,
    
    // Helper function to get like count
    getLikeCount: (postId) => interactions.likeCounts[postId] || 0
  };
};

// Add a default export to fix the import issue
export default usePostInteractions;
