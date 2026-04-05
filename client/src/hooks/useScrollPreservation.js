import { useEffect, useRef, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';
import { setScrollPosition, clearScrollPosition } from '../Slices/HomeSlice';

/**
 * Custom hook for preserving scroll position on the home page
 * Simplified approach that works better with touch devices and infinite scroll
 * Only operates when on the home page (location.pathname === '/')
 */
export const useScrollPreservation = ({
  posts = [],
  loading = false,
  loadingMore = false,
  isContentReady = false
}) => {
  const dispatch = useDispatch();
  const location = useLocation();
  const savedScrollPosition = useSelector(state => state.home.scrollPosition);
  
  // Only operate on the home page
  const isHomePage = location.pathname === '/';
  
  // Simplified pause flag - less aggressive
  if (typeof window !== 'undefined') {
    if (window.scrollPreservationPaused === undefined) {
      window.scrollPreservationPaused = false;
    }
  }
  
  // Refs to manage scroll restoration state
  const scrollRestorationAttempted = useRef(false);
  const scrollRestorationCompleted = useRef(false);
  const isRestoringScroll = useRef(false);
  const lastPostCount = useRef(0);
  const restorationTimeoutRef = useRef(null);
  const scrollSaveTimeoutRef = useRef(null);
  const lastSavedPosition = useRef(0);
  const navigationInProgress = useRef(false);
  const preciseScrollPosition = useRef(0); // Track more precise position
  
  // Debug log when savedScrollPosition changes with more details
  useEffect(() => {
    console.log('=== SCROLL PRESERVATION DEBUG ===');
    console.log('Saved scroll position changed:', savedScrollPosition);
    console.log('Current page state:', {
      isContentReady,
      loading,
      postsLength: posts.length,
      currentScrollY: window.scrollY,
      documentHeight: document.documentElement.scrollHeight,
      windowHeight: window.innerHeight
    });
    console.log('Restoration state:', {
      scrollRestorationAttempted: scrollRestorationAttempted.current,
      scrollRestorationCompleted: scrollRestorationCompleted.current,
      isRestoringScroll: isRestoringScroll.current
    });
    console.log('=== END DEBUG ===');  }, [savedScrollPosition, isContentReady, loading, posts.length]);  // More precise scroll saver with better duplicate prevention and fast scroll handling
  const saveScrollPosition = useCallback((position) => {
    // Save scroll position even if it's 0, but respect pause flag
    if (isHomePage && 
        position >= 0 && // Allow saving position 0
        !isRestoringScroll.current && 
        !loadingMore && 
        !navigationInProgress.current &&
        !window.scrollPreservationPaused && // Respect global pause flag
        Math.abs(position - lastSavedPosition.current) > 20) { // Increased threshold to be less aggressive
      
      // Don't save if user is very close to bottom (likely fast scrolling to load more)
      const documentHeight = document.documentElement.scrollHeight;
      const windowHeight = window.innerHeight;
      const distanceFromBottom = documentHeight - (position + windowHeight);
      
      if (distanceFromBottom < 300) { // Increased from 100 to 300
        console.log('User is very close to bottom, skipping position save to avoid fast scroll issues');
        return;
      }
      
      console.log(`Saving scroll position: ${position}px (previous: ${lastSavedPosition.current}px)`);
      lastSavedPosition.current = position;
      preciseScrollPosition.current = position; // Store precise position
      
      dispatch(setScrollPosition({
        position: Math.round(position), // Round to avoid sub-pixel issues
        timestamp: Date.now(),
        postCount: posts.length
      }));
    }
  }, [isHomePage, dispatch, posts.length, loadingMore]);
  
  // More throttled scroll event handler
  const handleScroll = useCallback(() => {
    // Don't save scroll position during restoration, while loading more content, when not on home page,
    // or when scroll preservation is paused
    if (isRestoringScroll.current || 
        loadingMore || 
        !isHomePage || 
        window.scrollPreservationPaused) {
      return;
    }
    
    const currentPosition = window.scrollY;
    
    // Additional check: if we're near the bottom and posts are loading, be extra conservative
    const documentHeight = document.documentElement.scrollHeight;
    const windowHeight = window.innerHeight;
    const distanceFromBottom = documentHeight - (currentPosition + windowHeight);
    
    // If user is very close to bottom (within 300px), don't save position
    // This helps prevent saving position during rapid scrolling that might trigger load more
    if (distanceFromBottom < 300) {
      return;
    }
    
    // Use requestAnimationFrame to throttle scroll events more effectively
    if (!scrollSaveTimeoutRef.current) {
      scrollSaveTimeoutRef.current = requestAnimationFrame(() => {
        // Save position even if it's 0 (top of page) but check for meaningful changes
        if (currentPosition === 0 || Math.abs(currentPosition - preciseScrollPosition.current) > 10) {
          saveScrollPosition(currentPosition);
        }
        scrollSaveTimeoutRef.current = null;
      });
    }
  }, [saveScrollPosition, loadingMore, isHomePage]);
  // Enhanced restore scroll position with better precision
  const restoreScrollPosition = useCallback(async () => {
    if (savedScrollPosition?.position === undefined || 
        scrollRestorationCompleted.current) {
      console.log('No valid scroll position to restore or already restored');
      return;
    }
    
    const targetPosition = Math.round(savedScrollPosition.position); // Ensure integer position
    const savedPostCount = savedScrollPosition.postCount || 0;
    
    console.log(`Restoring scroll to position: ${targetPosition}px`);
    console.log('Current conditions:', {
      isContentReady,
      loading,
      postsLength: posts.length,
      savedPostCount,
      documentHeight: document.documentElement.scrollHeight,
      windowHeight: window.innerHeight
    });
    
    isRestoringScroll.current = true;
    
    try {
      // More precise restoration with better error handling
      await new Promise((resolve) => {
        let attempts = 0;
        const maxAttempts = 5; // Increased attempts for better accuracy
        
        const attemptScroll = () => {
          attempts++;
          console.log(`Scroll attempt ${attempts}/${maxAttempts} to ${targetPosition}px`);
          
          // Use more precise scrolling
          window.scrollTo({
            top: targetPosition,
            left: 0,
            behavior: 'instant'
          });
          
          // Wait for the scroll to complete and check position
          requestAnimationFrame(() => {
            requestAnimationFrame(() => { // Double RAF for better precision
              const currentPosition = Math.round(window.scrollY);
              const threshold = 2; // Much tighter threshold
              const documentHeight = document.documentElement.scrollHeight;
              const maxScrollPosition = documentHeight - window.innerHeight;
              
              console.log(`Scroll attempt ${attempts} result:`, {
                currentPosition,
                targetPosition,
                documentHeight,
                maxScrollPosition,
                difference: Math.abs(currentPosition - targetPosition)
              });
              
              // Check if we're close enough to target or at max scroll
              if (Math.abs(currentPosition - targetPosition) <= threshold || 
                  currentPosition >= maxScrollPosition - 5) {
                console.log(`✅ Scroll restored successfully to ${currentPosition}px`);
                scrollRestorationCompleted.current = true;
                preciseScrollPosition.current = currentPosition; // Update precise position
                resolve();
              } else if (attempts < maxAttempts) {
                // Try again after a very short delay
                setTimeout(attemptScroll, 50);
              } else {
                console.log(`Max attempts reached, final position: ${currentPosition}px`);
                scrollRestorationCompleted.current = true;
                preciseScrollPosition.current = currentPosition;
                resolve();
              }
            });
          });
        };
        
        // Start the scroll attempts
        attemptScroll();
      });
    } catch (error) {
      console.error('Error during scroll restoration:', error);
      scrollRestorationCompleted.current = true;
    } finally {
      // Clear the restoration flag after a very short delay
      setTimeout(() => {
        isRestoringScroll.current = false;
      }, 100);
    }
  }, [savedScrollPosition, isContentReady, loading, posts.length]);
  // Enhanced immediate scroll restoration effect
  useEffect(() => {
    // Only attempt restoration on home page with valid saved position
    if (!isHomePage || savedScrollPosition?.position === undefined) {
      console.log('No valid scroll position to restore or not on home page');
      return;
    }

    if (scrollRestorationCompleted.current) {
      console.log('Scroll restoration already completed');
      return;
    }

    if (scrollRestorationAttempted.current) {
      console.log('Scroll restoration already attempted');
      return;
    }

    // Additional check: ensure the saved position is recent (within last 5 minutes)
    const timeSinceSaved = Date.now() - (savedScrollPosition.timestamp || 0);
    if (timeSinceSaved > 5 * 60 * 1000) { // 5 minutes
      console.log('Saved scroll position is too old, skipping restoration');
      return;
    }

    console.log('IMMEDIATE scroll restoration on mount:', {
      savedPosition: savedScrollPosition.position,
      currentScrollY: window.scrollY,
      timestamp: savedScrollPosition.timestamp,
      timeSinceSaved: timeSinceSaved
    });

    // Mark as attempted immediately
    scrollRestorationAttempted.current = true;
    isRestoringScroll.current = true;

    // Enhanced immediate synchronous scroll restoration
    try {
      const targetPosition = Math.round(savedScrollPosition.position); // Ensure integer
      
      // Disable smooth scrolling temporarily
      document.documentElement.style.scrollBehavior = 'auto';
      
      // Set scroll position immediately with maximum precision
      window.scrollTo({
        top: targetPosition,
        left: 0,
        behavior: 'instant'
      });
      
      // Force a layout recalculation
      document.documentElement.offsetHeight;
      
      console.log(`Immediate scroll set to: ${targetPosition}px, actual: ${window.scrollY}px`);
      
      // Verify restoration in next frame with better precision
      requestAnimationFrame(() => {
        requestAnimationFrame(() => { // Double RAF for better precision
          const currentPosition = Math.round(window.scrollY);
          const difference = Math.abs(currentPosition - targetPosition);
          
          if (difference <= 2) { // Much tighter threshold
            console.log(`✅ Immediate scroll restoration successful: ${currentPosition}px`);
            scrollRestorationCompleted.current = true;
            preciseScrollPosition.current = currentPosition;
          } else {
            console.log(`⚠️ Immediate restoration needs adjustment: target=${targetPosition}, actual=${currentPosition}`);
            // Schedule fine-tuning after content loads
            restorationTimeoutRef.current = setTimeout(() => {
              if (!scrollRestorationCompleted.current) {
                restoreScrollPosition();
              }
            }, 300); // Shorter timeout
          }
          
          // Re-enable smooth scrolling
          document.documentElement.style.scrollBehavior = '';
          
          // Clear restoration flag after a short delay
          setTimeout(() => {
            isRestoringScroll.current = false;
          }, 150);
        });
      });
      
    } catch (error) {
      console.error('Error in immediate scroll restoration:', error);
      isRestoringScroll.current = false;
      // Re-enable smooth scrolling on error
      document.documentElement.style.scrollBehavior = '';
    }
    
    return () => {
      if (restorationTimeoutRef.current) {
        clearTimeout(restorationTimeoutRef.current);
      }
    };
  }, [isHomePage, savedScrollPosition]);
  // Secondary restoration effect for fine-tuning after content loads
  useEffect(() => {
    if (!isHomePage || 
        savedScrollPosition?.position === undefined ||
        scrollRestorationCompleted.current ||
        !isContentReady) {
      return;
    }

    // Fine-tune scroll position after content is ready (if needed)
    const currentPosition = window.scrollY;
    const targetPosition = savedScrollPosition.position;
    const difference = Math.abs(currentPosition - targetPosition);
    
    if (difference > 50) {
      console.log('Fine-tuning scroll position after content load');
      restoreScrollPosition();
    }
  }, [isHomePage, isContentReady, savedScrollPosition, restoreScrollPosition]);  // Effect to handle new content loading (infinite scroll) with better timing
  useEffect(() => {
    const currentPostCount = posts.length;
    
    // If we're loading more posts, completely avoid any scroll position interference
    if (loadingMore) {
      console.log('Loading more posts - preventing any scroll position saving');
      // Set the global pause flag
      window.scrollPreservationPaused = true;
      return;
    }
    
    // If we have new posts loaded and scroll restoration was completed,
    // let the browser handle the natural scroll position
    if (currentPostCount > lastPostCount.current && scrollRestorationCompleted.current) {
      console.log(`New posts loaded (${currentPostCount} vs ${lastPostCount.current}), maintaining scroll naturally`);
      
      // Keep scroll preservation paused for a longer time during content integration
      // This prevents interference with native scroll anchor preservation
      window.scrollPreservationPaused = true;
      
      // Longer delay to ensure DOM updates and scroll adjustments are complete
      const preventSaveTimeout = setTimeout(() => {
        console.log('New posts fully integrated, scroll saving re-enabled');
        window.scrollPreservationPaused = false;
      }, 2000); // Increased to 2 seconds to avoid interference
      
      return () => {
        clearTimeout(preventSaveTimeout);
        // Ensure pause flag is cleared if component unmounts
        window.scrollPreservationPaused = false;
      };
    }
    
    // Ensure pause flag is cleared if not loading more
    if (!loadingMore && currentPostCount === lastPostCount.current) {
      window.scrollPreservationPaused = false;
    }
    
    lastPostCount.current = currentPostCount;
  }, [posts.length, loadingMore]);// Save scroll position when navigating away from home page via React Router
  useEffect(() => {
    return () => {
      // This cleanup runs when location changes or component unmounts
      // Only save once during navigation with flag protection
      if (isHomePage && location.pathname === '/' && !navigationInProgress.current) {
        const currentPosition = Math.round(window.scrollY); // Ensure integer
        if (currentPosition > 50 && 
            !isRestoringScroll.current && 
            !loadingMore &&
            Math.abs(currentPosition - lastSavedPosition.current) > 5) { // Tighter threshold
          
          navigationInProgress.current = true;
          console.log(`React Router navigation cleanup - saving scroll position: ${currentPosition}px`);
          lastSavedPosition.current = currentPosition;
          preciseScrollPosition.current = currentPosition;
          
          dispatch(setScrollPosition({
            position: currentPosition,
            timestamp: Date.now(),
            postCount: posts.length
          }));
          
          // Reset navigation flag after a delay
          setTimeout(() => {
            navigationInProgress.current = false;
          }, 1000);
        }
      }
    };
  }, [isHomePage, location, dispatch, posts.length, loadingMore]);

  // Clear scroll position when navigating to other pages to ensure they start from top
  useEffect(() => {
    // If we're not on the home page, ensure we start from the top
    if (location.pathname !== '/') {
      console.log('Not on home page, ensuring page starts from top');
      window.scrollTo({ top: 0, behavior: 'instant' });
    }
  }, [location.pathname]);  // Effect to attach scroll listener and navigation event handlers - only on home page
  useEffect(() => {
    // Only attach listeners when on home page
    if (!isHomePage) {
      return;
    }    // Function to save scroll position before navigation with duplicate prevention
    const saveScrollBeforeNavigation = () => {
      // Only save if we're currently on the home page and conditions are right
      if (!isHomePage || location.pathname !== '/' || navigationInProgress.current) {
        return;
      }
      
      const currentPosition = Math.round(window.scrollY); // Ensure integer
      if (currentPosition > 50 && 
          !isRestoringScroll.current && 
          !loadingMore &&
          Math.abs(currentPosition - lastSavedPosition.current) > 5) { // Tighter threshold
        
        navigationInProgress.current = true;
        console.log(`Navigation detected - saving scroll position: ${currentPosition}px (previous: ${lastSavedPosition.current}px)`);
        lastSavedPosition.current = currentPosition;
        preciseScrollPosition.current = currentPosition;
        
        dispatch(setScrollPosition({
          position: currentPosition,
          timestamp: Date.now(),
          postCount: posts.length
        }));
        
        // Reset navigation flag after a delay
        setTimeout(() => {
          navigationInProgress.current = false;
        }, 1000);
      }
    };
    
    // Function to clear scroll position when navigating away from home
    const clearScrollOnNavigation = (targetPath) => {
      // If navigating away from home page, clear saved position
      // so that when user comes back, they start fresh
      if (location.pathname === '/' && targetPath !== '/') {
        console.log('Navigating away from home page, clearing scroll position for fresh start');
        dispatch(clearScrollPosition());
      }
    };

    // Browser navigation event handlers
    const handleBeforeUnload = (event) => {
      saveScrollBeforeNavigation();
    };

    const handlePopState = (event) => {
      // Save before the navigation happens
      saveScrollBeforeNavigation();
    };

    const handlePageHide = (event) => {
      // Page is being hidden (tab switch, browser close, navigation)
      saveScrollBeforeNavigation();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        saveScrollBeforeNavigation();
      }
    };

    // Handle focus loss (when user clicks address bar or switches tabs)
    const handleBlur = () => {
      saveScrollBeforeNavigation();
    };

    // Handle clicks on navigation elements
    const handleNavigationClick = (event) => {
      // Check if the clicked element or its parent is a navigation link
      const clickedElement = event.target;
      const isNavigationClick = 
        clickedElement.tagName === 'A' ||
        clickedElement.closest('a') ||
        clickedElement.closest('[data-navigation]') ||
        clickedElement.closest('.nav-item') ||
        clickedElement.closest('nav');
      
      if (isNavigationClick) {
        // Get the target URL to determine navigation destination
        const linkElement = clickedElement.tagName === 'A' ? clickedElement : clickedElement.closest('a');
        const targetPath = linkElement?.getAttribute('href') || linkElement?.pathname;
        
        console.log('Navigation click detected, target:', targetPath);
        
        if (targetPath && targetPath !== '/') {
          // Navigating away from home - save position but don't clear it yet
          saveScrollBeforeNavigation();
        }
      }
    };

    // Attach scroll listener after a delay to ensure restoration is handled first
    const attachScrollListener = () => {
      console.log('Attaching scroll listener and navigation handlers on home page');
      window.addEventListener('scroll', handleScroll, { passive: true });
      
      // Add navigation event listeners
      window.addEventListener('beforeunload', handleBeforeUnload);
      window.addEventListener('popstate', handlePopState);
      window.addEventListener('pagehide', handlePageHide);
      window.addEventListener('blur', handleBlur);
      document.addEventListener('visibilitychange', handleVisibilityChange);
      
      // Add click handler for navigation elements
      document.addEventListener('click', handleNavigationClick, { capture: true });
    };
    
    const timeoutId = setTimeout(attachScrollListener, 1000); // Wait 1 second before attaching
    
    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener('scroll', handleScroll);
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('popstate', handlePopState);
      window.removeEventListener('pagehide', handlePageHide);
      window.removeEventListener('blur', handleBlur);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      document.removeEventListener('click', handleNavigationClick, { capture: true });
      if (scrollSaveTimeoutRef.current) {
        cancelAnimationFrame(scrollSaveTimeoutRef.current);
      }
    };
  }, [isHomePage, handleScroll, dispatch, posts.length, loadingMore]);

  // Enhanced cleanup function
  const cleanup = useCallback(() => {
    // Only save if we're on home page and it's a meaningful position
    if (isHomePage && location.pathname === '/') {
      const currentPosition = Math.round(window.scrollY); // Ensure integer
      
      // Save final scroll position if it's meaningful and we're not in any loading state
      if (currentPosition > 50 && !loadingMore && !isRestoringScroll.current) {
        console.log(`Final cleanup - saving scroll position: ${currentPosition}px`);
        dispatch(setScrollPosition({
          position: currentPosition,
          timestamp: Date.now(),
          postCount: posts.length
        }));
      }
    }
      // Clear any pending timeouts
    if (restorationTimeoutRef.current) {
      clearTimeout(restorationTimeoutRef.current);
    }
    if (scrollSaveTimeoutRef.current) {
      cancelAnimationFrame(scrollSaveTimeoutRef.current);
    }    // Clear the global pause flag on cleanup
    if (typeof window !== 'undefined') {
      window.scrollPreservationPaused = false;
    }
  }, [isHomePage, location.pathname, dispatch, posts.length, loadingMore]);
  
  // Function to clear saved scroll position (useful for manual refresh)
  const clearSavedPosition = useCallback(() => {
    console.log('Clearing saved scroll position');
    dispatch(clearScrollPosition());
    scrollRestorationCompleted.current = false;
    scrollRestorationAttempted.current = false;
  }, [dispatch]);
    return {
    cleanup,
    clearSavedPosition,
    manualRestoreScroll: restoreScrollPosition,
    isScrollRestoring: isRestoringScroll.current,
    scrollRestorationCompleted: scrollRestorationCompleted.current,
    savedPosition: savedScrollPosition?.position || 0
  };
};

export default useScrollPreservation;
