import { useState, useCallback } from 'react';

/**
 * Custom hook for optimistic UI updates with rollback on failure
 * 
 * @param {function} updateFn - Function to perform the actual data update (returns a Promise)
 * @param {function} onSuccess - Optional callback for successful updates
 * @param {function} onError - Optional callback for failed updates
 * @returns {Object} - Object containing update function and loading state
 */
export const useOptimisticUpdate = (updateFn, onSuccess, onError) => {
  const [isUpdating, setIsUpdating] = useState(false);
  
  const performUpdate = useCallback(async (optimisticData, id, options = {}) => {
    // Skip if already updating the same item
    if (isUpdating) return;
    
    setIsUpdating(true);
    
    try {
      // Execute the update function
      const result = await updateFn(id, options);
      
      // Call success callback with the result if provided
      if (onSuccess && typeof onSuccess === 'function') {
        onSuccess(result, id);
      }
      
      setIsUpdating(false);
      return result;
    } catch (error) {
      console.error('Optimistic update failed:', error);
      
      // Call error callback if provided
      if (onError && typeof onError === 'function') {
        onError(error, id, optimisticData);
      }
      
      setIsUpdating(false);
      throw error;
    }
  }, [updateFn, onSuccess, onError, isUpdating]);
  
  return {
    performUpdate,
    isUpdating
  };
};

// Add a default export to fix the import issue
export default useOptimisticUpdate;
