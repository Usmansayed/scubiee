import useInteractionManager from './useInteractionManager';
import { useOptimisticUpdate } from './useOptimisticUpdate';
import { usePostInteractions } from './usePostInteractions';

export { useInteractionManager };
export { useOptimisticUpdate };
export { usePostInteractions };

// Also export as default exports to maintain backward compatibility
export default {
  useInteractionManager,
  useOptimisticUpdate,
  usePostInteractions
};
