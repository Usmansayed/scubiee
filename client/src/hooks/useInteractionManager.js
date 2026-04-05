import { useRef, useCallback, useEffect } from 'react';
import { toast } from 'react-toastify';
import axios from 'axios';

const api = import.meta.env.VITE_API_URL;

/**
 * Custom hook for managing post and comment interactions (like/unlike, save/unsave)
 * with debouncing, optimistic updates, and preventing duplicate requests
 */
const useInteractionManager = () => {
  // Track pending requests to prevent duplicates
  const pendingRequests = useRef(new Map());
  
  // Track debounce timers
  const debounceTimers = useRef(new Map());
  
  // Track actual states for each item
  const actualStates = useRef(new Map());
  
  // Track retry attempts
  const retryAttempts = useRef(new Map());

  // Clean up on unmount
  useEffect(() => {
    return () => {
      // Cancel all timers
      debounceTimers.current.forEach(timerId => clearTimeout(timerId));
      
      // Clear all maps
      debounceTimers.current.clear();
      pendingRequests.current.clear();
      actualStates.current.clear();
      retryAttempts.current.clear();
    };
  }, []);

  /**
   * Creates a like/unlike handler with debouncing and optimistic UI updates
   * 
   * @param {string|number} itemId - ID of the post/comment
   * @param {boolean} currentLikedState - Current liked state from Redux/component state
   * @param {function} updateUiState - Function to update UI state (usually Redux dispatch or setState)
   * @param {boolean} countMode - Whether to update a counter or just boolean state
   * @param {number} debounceTime - Time to wait before sending request (in ms)
   * @returns {function} Event handler function
   */
  const createLikeHandler = useCallback((
    itemId, 
    currentLikedState,
    updateUiState,
    countMode = true,
    debounceTime = 500 // Set to 800ms as requested
  ) => {
    return (e) => {
      if (e) e.stopPropagation();
      
      // Convert itemId to string for consistent Map keys
      const itemKey = itemId.toString();
      
      // Add visual feedback
      if (e && e.currentTarget) {
        requestAnimationFrame(() => {
          e.currentTarget.classList.add('scale-90');
          setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
        });
      }
      
      // Get the actual current state (may be different from passed state if multiple clicks)
      const actualCurrentState = actualStates.current.get(itemKey) ?? currentLikedState;
      
      // Calculate new state (toggle)
      const newState = !actualCurrentState;
      
      // Store the new state
      actualStates.current.set(itemKey, newState);
      
      // Update UI optimistically for boolean or count-based state
      if (countMode) {
        updateUiState(prev => {
          const likesCount = prev[`${itemKey}_count`] || 0;
          const newCount = newState ? likesCount + 1 : Math.max(0, likesCount - 1);
          
          return {
            ...prev,
            [itemKey]: newState,
            [`${itemKey}_count`]: newCount
          };
        });
      } else {
        updateUiState(prev => ({
          ...prev,
          [itemKey]: newState
        }));
      }
      
      // Update all UI elements with the same ID
      const updateDomElements = () => {
        // Handle like buttons
        document.querySelectorAll(`[data-like-button="${itemId}"]`).forEach(button => {
          const emptyHeart = button.querySelector('.empty-heart');
          const filledHeart = button.querySelector('.filled-heart');
          
          if (emptyHeart && filledHeart) {
            if (newState) {
              emptyHeart.style.display = 'none';
              filledHeart.style.display = 'block';
            } else {
              emptyHeart.style.display = 'block';
              filledHeart.style.display = 'none';
            }
          }
        });
      };
      
      // Update DOM immediately
      updateDomElements();
      
      // Clear existing timer - IMPORTANT: This ensures the debounce resets on each click
      if (debounceTimers.current.get(itemKey)) {
        clearTimeout(debounceTimers.current.get(itemKey));
      }
      
      // Set a new timer - this will reset the countdown on each click
      const timerId = setTimeout(async () => {
        // Set pending flag only when actually making the request
        pendingRequests.current.set(itemKey, true);
        
        try {
          console.log(`Making API request after ${debounceTime}ms debounce for like operation on ${itemKey}`);
          
          const response = await axios.post(
            `${api}/user-interactions/like/${itemId}`,
            {},
            {
              withCredentials: true,
              headers: { accessToken: localStorage.getItem("accessToken") }
            }
          );
          
          // Clear pending request
          pendingRequests.current.delete(itemKey);
          
          if (!response.data.success) {
            throw new Error('Server indicated failure');
          }
          
          // Reset retry counter on success
          retryAttempts.current.delete(itemKey);
          
          console.log(`Like operation successful for ${itemKey}`);
        } catch (error) {
          console.error(`Like operation failed for ${itemKey}:`, error);
          
          // Implement retry logic
          const attempts = retryAttempts.current.get(itemKey) || 0;
          
          if (attempts < 2) { // Max 2 retries
            console.log(`Retrying like operation for ${itemKey}, attempt ${attempts + 1}`);
            retryAttempts.current.set(itemKey, attempts + 1);
            
            // Retry after a delay (exponential backoff)
            setTimeout(() => {
              // Reset pending status for retry
              pendingRequests.current.delete(itemKey);
              
              // Get current actual state for retry
              const currentState = actualStates.current.get(itemKey);
              
              // Make a direct API call without going through the handler again
              axios.post(
                `${api}/user-interactions/like/${itemId}`,
                {},
                {
                  withCredentials: true,
                  headers: { accessToken: localStorage.getItem("accessToken") }
                }
              ).then(response => {
                console.log(`Retry successful for ${itemKey}`);
                retryAttempts.current.delete(itemKey);
              }).catch(retryError => {
                // If retry also fails, revert the UI
                if (attempts === 1) { // On the last retry
                  console.log(`Reverting UI state for ${itemKey} after failed retries`);
                  
                  // Revert actual state
                  actualStates.current.set(itemKey, actualCurrentState);
                  
                  // Revert UI state
                  if (countMode) {
                    updateUiState(prev => {
                      const currentCount = prev[`${itemKey}_count`] || 0;
                      const revertedCount = actualCurrentState 
                        ? currentCount + 1  // We unliked, so add one back
                        : Math.max(0, currentCount - 1); // We liked, so remove one
                      
                      return {
                        ...prev,
                        [itemKey]: actualCurrentState,
                        [`${itemKey}_count`]: revertedCount
                      };
                    });
                  } else {
                    updateUiState(prev => ({
                      ...prev,
                      [itemKey]: actualCurrentState
                    }));
                  }
                  
                  // Revert DOM elements
                  document.querySelectorAll(`[data-like-button="${itemId}"]`).forEach(button => {
                    const emptyHeart = button.querySelector('.empty-heart');
                    const filledHeart = button.querySelector('.filled-heart');
                    
                    if (emptyHeart && filledHeart) {
                      if (actualCurrentState) {
                        emptyHeart.style.display = 'none';
                        filledHeart.style.display = 'block';
                      } else {
                        emptyHeart.style.display = 'block';
                        filledHeart.style.display = 'none';
                      }
                    }
                  });
                  
                  // Show error toast
                  toast.error("Network error. Please try again.");
                  
                  // Clear retry counter
                  retryAttempts.current.delete(itemKey);
                }
              });
            }, 1000 * Math.pow(2, attempts)); // 1s, 2s, 4s
            
            return;
          }
          
          // If retries exhausted or not using retries, revert UI state
          console.log(`Reverting UI state for ${itemKey}`);
          
          // Revert actual state
          actualStates.current.set(itemKey, actualCurrentState);
          
          // Revert UI state
          if (countMode) {
            updateUiState(prev => {
              const currentCount = prev[`${itemKey}_count`] || 0;
              const revertedCount = actualCurrentState 
                ? currentCount + 1  // We unliked, so add one back
                : Math.max(0, currentCount - 1); // We liked, so remove one
              
              return {
                ...prev,
                [itemKey]: actualCurrentState,
                [`${itemKey}_count`]: revertedCount
              };
            });
          } else {
            updateUiState(prev => ({
              ...prev,
              [itemKey]: actualCurrentState
            }));
          }
          
          // Revert DOM elements
          const revertDomElements = () => {
            document.querySelectorAll(`[data-like-button="${itemId}"]`).forEach(button => {
              const emptyHeart = button.querySelector('.empty-heart');
              const filledHeart = button.querySelector('.filled-heart');
              
              if (emptyHeart && filledHeart) {
                if (actualCurrentState) {
                  emptyHeart.style.display = 'none';
                  filledHeart.style.display = 'block';
                } else {
                  emptyHeart.style.display = 'block';
                  filledHeart.style.display = 'none';
                }
              }
            });
          };
          
          revertDomElements();
          
          // Show error toast only if completely failed
          if (attempts >= 2) {
            toast.error("Network error. Please try again.");
          }
          
          // Clear pending status and retry counter
          pendingRequests.current.delete(itemKey);
          retryAttempts.current.delete(itemKey);
        }
      }, debounceTime);
      
      // Store timer ID for potential cancellation
      debounceTimers.current.set(itemKey, timerId);
      
      console.log(`Set debounce timer for ${itemKey} - will execute after ${debounceTime}ms unless interrupted`);
    };
  }, []);

  /**
   * Creates a save/unsave handler with debouncing and optimistic UI updates
   * 
   * @param {string|number} itemId - ID of the post/comment
   * @param {boolean} currentSavedState - Current saved state from Redux/component state
   * @param {function} updateUiState - Function to update UI state (Redux dispatch or setState)
   * @param {boolean} showToast - Whether to show toast notifications
   * @param {number} debounceTime - Time to wait before sending request (in ms)
   * @returns {function} Event handler function
   */
  const createSaveHandler = useCallback((
    itemId, 
    currentSavedState,
    updateUiState,
    showToast = true,
    debounceTime = 500 // Set to 800ms as requested
  ) => {
    return (e) => {
      if (e) e.stopPropagation();
      
      // Convert itemId to string for consistent Map keys
      const itemKey = `save_${itemId.toString()}`;
      
      // Add visual feedback
      if (e && e.currentTarget) {
        requestAnimationFrame(() => {
          e.currentTarget.classList.add('scale-90');
          setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
        });
      }
      
      // Get the actual current state
      const actualCurrentState = actualStates.current.get(itemKey) ?? currentSavedState;
      
      // Calculate new state (toggle)
      const newState = !actualCurrentState;
      
      // Store the new state
      actualStates.current.set(itemKey, newState);
      
      // Update UI optimistically
      updateUiState(prev => ({
        ...prev,
        [itemId]: newState
      }));
      
      // Update all UI elements with the same ID
      const updateDomElements = () => {
        document.querySelectorAll(`[data-save-button="${itemId}"]`).forEach(button => {
          const emptyBookmark = button.querySelector('.empty-bookmark');
          const filledBookmark = button.querySelector('.filled-bookmark');
          
          if (emptyBookmark && filledBookmark) {
            if (newState) {
              emptyBookmark.style.display = 'none';
              filledBookmark.style.display = 'block';
            } else {
              emptyBookmark.style.display = 'block';
              filledBookmark.style.display = 'none';
            }
          }
        });
      };
      
      // Update DOM immediately
      updateDomElements();
      
      // Show toast immediately
      if (showToast) {
        toast.success(newState ? "Post saved" : "Post removed from saved items");
      }
      
      // Clear existing timer - IMPORTANT: This ensures the debounce resets on each click
      if (debounceTimers.current.get(itemKey)) {
        clearTimeout(debounceTimers.current.get(itemKey));
      }
      
      // Set a new timer - this will reset the countdown on each click
      const timerId = setTimeout(async () => {
        // Set pending flag only when actually making the request
        pendingRequests.current.set(itemKey, true);
        
        try {
          console.log(`Making API request after ${debounceTime}ms debounce for save operation on ${itemKey}`);
          
          const response = await axios.post(
            `${api}/user-interactions/save/${itemId}`,
            {},
            {
              withCredentials: true,
              headers: { accessToken: localStorage.getItem("accessToken") }
            }
          );
          
          // Clear pending request
          pendingRequests.current.delete(itemKey);
          
          if (!response.data.success) {
            throw new Error('Server indicated failure');
          }
          
          // Reset retry counter on success
          retryAttempts.current.delete(itemKey);
          
          console.log(`Save operation successful for ${itemKey}`);
        } catch (error) {
          console.error(`Save operation failed for ${itemKey}:`, error);
          
          // Implement retry logic
          const attempts = retryAttempts.current.get(itemKey) || 0;
          
          if (attempts < 2) { // Max 2 retries
            console.log(`Retrying save operation for ${itemKey}, attempt ${attempts + 1}`);
            retryAttempts.current.set(itemKey, attempts + 1);
            
            // Retry after a delay (exponential backoff)
            setTimeout(() => {
              // Reset pending status for retry
              pendingRequests.current.delete(itemKey);
              
              // Get current actual state for retry
              const currentState = actualStates.current.get(itemKey);
              
              // Make a direct API call without going through the handler again
              axios.post(
                `${api}/user-interactions/save/${itemId}`,
                {},
                {
                  withCredentials: true,
                  headers: { accessToken: localStorage.getItem("accessToken") }
                }
              ).then(response => {
                console.log(`Retry successful for ${itemKey}`);
                retryAttempts.current.delete(itemKey);
              }).catch(retryError => {
                // If retry also fails, revert the UI
                if (attempts === 1) { // On the last retry
                  console.log(`Reverting UI state for ${itemKey} after failed retries`);
                  
                  // Revert actual state
                  actualStates.current.set(itemKey, actualCurrentState);
                  
                  // Revert UI state
                  updateUiState(prev => ({
                    ...prev,
                    [itemId]: actualCurrentState
                  }));
                  
                  // Revert DOM elements
                  document.querySelectorAll(`[data-save-button="${itemId}"]`).forEach(button => {
                    const emptyBookmark = button.querySelector('.empty-bookmark');
                    const filledBookmark = button.querySelector('.filled-bookmark');
                    
                    if (emptyBookmark && filledBookmark) {
                      if (actualCurrentState) {
                        emptyBookmark.style.display = 'none';
                        filledBookmark.style.display = 'block';
                      } else {
                        emptyBookmark.style.display = 'block';
                        filledBookmark.style.display = 'none';
                      }
                    }
                  });
                  
                  // Show error toast
                  if (showToast) {
                    toast.error("Network error. Please try again.");
                  }
                  
                  // Clear retry counter
                  retryAttempts.current.delete(itemKey);
                }
              });
            }, 1000 * Math.pow(2, attempts)); // 1s, 2s, 4s
            
            return;
          }
          
          // If retries exhausted or not using retries, revert UI state
          console.log(`Reverting UI state for ${itemKey}`);
          
          // Revert actual state
          actualStates.current.set(itemKey, actualCurrentState);
          
          // Revert UI state
          updateUiState(prev => ({
            ...prev,
            [itemId]: actualCurrentState
          }));
          
          // Revert DOM elements
          const revertDomElements = () => {
            document.querySelectorAll(`[data-save-button="${itemId}"]`).forEach(button => {
              const emptyBookmark = button.querySelector('.empty-bookmark');
              const filledBookmark = button.querySelector('.filled-bookmark');
              
              if (emptyBookmark && filledBookmark) {
                if (actualCurrentState) {
                  emptyBookmark.style.display = 'none';
                  filledBookmark.style.display = 'block';
                } else {
                  emptyBookmark.style.display = 'block';
                  filledBookmark.style.display = 'none';
                }
              }
            });
          };
          
          revertDomElements();
          
          // Show error toast only if completely failed
          if (attempts >= 2 && showToast) {
            toast.error("Network error. Please try again.");
          }
          
          // Clear pending status and retry counter
          pendingRequests.current.delete(itemKey);
          retryAttempts.current.delete(itemKey);
        }
      }, debounceTime);
      
      // Store timer ID for potential cancellation
      debounceTimers.current.set(itemKey, timerId);
      
      console.log(`Set debounce timer for ${itemKey} - will execute after ${debounceTime}ms unless interrupted`);
    };
  }, []);

  /**
   * Creates a handler for comment likes with debouncing and optimistic UI updates
   * 
   * @param {string|number} commentId - ID of the comment
   * @param {boolean} currentLikedState - Current liked state
   * @param {function} updateUiState - Function to update UI state (setState)
   * @param {function} updateLikesCount - Function to update like count display
   * @param {number} debounceTime - Time to wait before sending request (in ms)
   * @returns {function} Event handler function
   */
  const createCommentLikeHandler = useCallback((
    commentId,
    currentLikedState,
    updateUiState,
    updateLikesCount,
    debounceTime = 500 // Set to 800ms as requested
  ) => {
    return (e) => {
      if (e) e.stopPropagation();
      
      // Convert commentId to string for consistent Map keys
      const itemKey = `comment_${commentId.toString()}`;
      
      // Add visual feedback
      if (e && e.currentTarget) {
        requestAnimationFrame(() => {
          e.currentTarget.classList.add('scale-90');
          setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
        });
      }
      
      // Get the actual current state
      const actualCurrentState = actualStates.current.get(itemKey) ?? currentLikedState;
      
      // Calculate new state (toggle)
      const newState = !actualCurrentState;
      
      // Store the new state
      actualStates.current.set(itemKey, newState);
      
      // Update UI state immediately
      updateUiState(commentId, newState);
      
      // Update like count display (if provided)
      if (updateLikesCount) {
        updateLikesCount(commentId, newState);
      }
      
      // Clear existing timer - IMPORTANT: This ensures the debounce resets on each click
      if (debounceTimers.current.get(itemKey)) {
        clearTimeout(debounceTimers.current.get(itemKey));
      }
      
      // Set a new timer - this will reset the countdown on each click
      const timerId = setTimeout(async () => {
        // Set pending flag only when actually making the request
        pendingRequests.current.set(itemKey, true);
        
        try {
          console.log(`Making API request after ${debounceTime}ms debounce for comment like operation on ${itemKey}`);
          
          const response = await axios.post(
            `${api}/user-interactions/like-comment/${commentId}`,
            {},
            {
              withCredentials: true,
              headers: { accessToken: localStorage.getItem("accessToken") }
            }
          );
          
          // Clear pending request
          pendingRequests.current.delete(itemKey);
          
          if (!response.data.success) {
            throw new Error('Server indicated failure');
          }
          
          // Reset retry counter on success
          retryAttempts.current.delete(itemKey);
          
          console.log(`Comment like operation successful for ${itemKey}`);
        } catch (error) {
          console.error(`Comment like operation failed for ${itemKey}:`, error);
          
          // Implement retry logic
          const attempts = retryAttempts.current.get(itemKey) || 0;
          
          if (attempts < 2) { // Max 2 retries
            console.log(`Retrying comment like operation for ${itemKey}, attempt ${attempts + 1}`);
            retryAttempts.current.set(itemKey, attempts + 1);
            
            // Retry after a delay (exponential backoff)
            setTimeout(() => {
              // Reset pending status for retry
              pendingRequests.current.delete(itemKey);
              
              // Get current actual state for retry
              const currentState = actualStates.current.get(itemKey);
              
              // Make a direct API call without going through the handler again
              axios.post(
                `${api}/user-interactions/like-comment/${commentId}`,
                {},
                {
                  withCredentials: true,
                  headers: { accessToken: localStorage.getItem("accessToken") }
                }
              ).then(response => {
                console.log(`Retry successful for ${itemKey}`);
                retryAttempts.current.delete(itemKey);
              }).catch(retryError => {
                // If retry also fails, revert the UI
                if (attempts === 1) { // On the last retry
                  console.log(`Reverting UI state for ${itemKey} after failed retries`);
                  
                  // Revert actual state
                  actualStates.current.set(itemKey, actualCurrentState);
                  
                  // Revert UI state
                  updateUiState(commentId, actualCurrentState);
                  
                  // Revert like count display
                  if (updateLikesCount) {
                    updateLikesCount(commentId, actualCurrentState);
                  }
                  
                  // Show error toast
                  toast.error("Network error. Please try again.");
                  
                  // Clear retry counter
                  retryAttempts.current.delete(itemKey);
                }
              });
            }, 1000 * Math.pow(2, attempts)); // 1s, 2s, 4s
            
            return;
          }
          
          // If retries exhausted, revert UI state
          console.log(`Reverting comment UI state for ${itemKey}`);
          
          // Revert actual state
          actualStates.current.set(itemKey, actualCurrentState);
          
          // Revert UI state
          updateUiState(commentId, actualCurrentState);
          
          // Revert like count display
          if (updateLikesCount) {
            updateLikesCount(commentId, actualCurrentState);
          }
          
          // Show error toast only if completely failed
          if (attempts >= 2) {
            toast.error("Network error. Please try again.");
          }
          
          // Clear pending status and retry counter
          pendingRequests.current.delete(itemKey);
          retryAttempts.current.delete(itemKey);
        }
      }, debounceTime);
      
      // Store timer ID for potential cancellation
      debounceTimers.current.set(itemKey, timerId);
      
      console.log(`Set debounce timer for ${itemKey} - will execute after ${debounceTime}ms unless interrupted`);
    };
  }, []);

  return {
    createLikeHandler,
    createSaveHandler,
    createCommentLikeHandler
  };
};

export default useInteractionManager;
