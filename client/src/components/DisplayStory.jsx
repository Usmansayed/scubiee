import React, { useState, useEffect, useLayoutEffect, useRef, useMemo } from "react";
import { FaChevronLeft, FaChevronRight } from "react-icons/fa6";
import axios from "axios";
const api = import.meta.env.VITE_API_URL;
import { IoMdMore } from "react-icons/io";
import { useSelector, useDispatch } from "react-redux";
import { IoEyeSharp } from "react-icons/io5";
import { IoMdClose } from "react-icons/io";
import { IoMdHeart } from "react-icons/io";
import { Heart } from 'lucide-react';
import { 
  setStories, 
  addPrefetchedUserId, 
  updateStoryViewed 
} from '../Slices/WidgetSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

const DisplayStory = ({ onClose, stories, selectedUserId, loggedInUser, onStoriesUpdate }) => {
  // Track current user index and current story index within that user
  const [currentUserIndex, setCurrentUserIndex] = useState(0);
  const [currentStoryIndex, setCurrentStoryIndex] = useState(0);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [videoRef, setVideoRef] = useState(null);
  const containerRef = useRef(null);
  const [bg, setBg] = useState("#0a0a0a");
  const [screenWidth, setScreenWidth] = useState(window.innerWidth);
  const [progress, setProgress] = useState(0);
  const [storyDuration, setStoryDuration] = useState(2); // default duration for non-video stories (in seconds)
  const [showMoreOptions, setShowMoreOptions] = useState(false);
  const userData = useSelector((state) => state.user.userData);
  const [viewers, setViewers] = useState([]);
  const [showViewersModal, setShowViewersModal] = useState(false);
  const [viewedStoryIds, setViewedStoryIds] = useState([]);
  const [storyLoaded, setStoryLoaded] = useState(false);
  const [assetsToLoad, setAssetsToLoad] = useState(0);
  const moreOptionsRef = useRef(null);
  const viewersModalRef = useRef(null);
  const progressRef = useRef(0);
  const pausedRef = useRef(false);
  const [isLoading, setIsLoading] = useState(false);
  const [processingNavigation, setProcessingNavigation] = useState(false);
  const lastNavigationRef = useRef(null);
  const [heartClicked, setHeartClicked] = useState(false);
  const localStoriesRef = useRef(null);
  const [touchStart, setTouchStart] = useState(null);
  const [touchEnd, setTouchEnd] = useState(null);
  const [swipeDistance, setSwipeDistance] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [transitionDirection, setTransitionDirection] = useState(null); // 'left' or 'right'
  const [previewUser, setPreviewUser] = useState(null);
  const [previewSide, setPreviewSide] = useState(null); // 'next' or 'prev'
  const [storiesForUI, setStoriesForUI] = useState(stories);
  const initializedRef = useRef(false);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const vcloud = import.meta.env.VITE_VIDEO_CLOUD_URL;

  const dispatch = useDispatch();
  // Get prefetched user IDs from Redux
  const prefetchedUserIdsList = useSelector(state => state.widget.prefetchedUserIds);
  // Convert to Set for easier lookups
  const prefetchedUserIds = useMemo(() => new Set(prefetchedUserIdsList), [prefetchedUserIdsList]);
  // Get viewed story IDs from Redux
  const viewedStoryIdsFromRedux = useSelector(state => state.widget.viewedStoryIds);
  
  // Sync local and Redux viewed story IDs
  useEffect(() => {
    setViewedStoryIds(viewedStoryIdsFromRedux);
  }, [viewedStoryIdsFromRedux]);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  const checkIsOffline = () => {
    return !navigator.onLine;
  };

  const navigateToStory = async (targetUserIndex, targetStoryIndex, options = {}) => {
    // Prevent navigation while already processing
    if (processingNavigation) {
      console.log("Navigation blocked: already processing");
      return false;
    }
    
    // Create unique ID for this navigation request
    const navigationId = `nav_${Date.now()}`;
    lastNavigationRef.current = navigationId;
    
    // Set processing flag
    setProcessingNavigation(true);
    console.log(`Starting navigation to user ${targetUserIndex}, story ${targetStoryIndex}`);
    
    try {
      // Check if target user has stories loaded
      const targetUser = stories[targetUserIndex];
      if (!targetUser) {
        console.error("Invalid user index:", targetUserIndex);
        return false;
      }
      
      // ** KEY CHANGE: Check if stories are already loaded, if so use them even if offline **
      const hasLoadedStories = targetUser.stories && 
                               targetUser.stories.length > 0;
                               
      // First check if we already have the stories loaded
      if (hasLoadedStories) {
        console.log("Stories already loaded for user, navigating directly");
        setCurrentUserIndex(targetUserIndex);
        // Use first story if the specified index is invalid
        const validStoryIndex = (targetStoryIndex < targetUser.stories.length) 
                              ? targetStoryIndex 
                              : 0;
        setCurrentStoryIndex(validStoryIndex);
        return true;
      }
      
      // If we need to fetch stories and we're offline, prevent navigation
      if (checkIsOffline()) {
        console.log("Offline, cannot fetch new stories");
        setIsLoading(false);
        toast.info("You're offline. Cannot load new stories right now.");
        return false;
      }
      
      // Load stories for target user
      setIsLoading(true);
      try {
        const response = await axios.get(`${api}/post/user-stories/${targetUser.userId}`, {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") },
          timeout: 8000 // 8-second timeout
        });
        
        // Verify this is still the most recent navigation request
        if (lastNavigationRef.current !== navigationId) {
          console.log("Navigation aborted: newer request in progress");
          return false;
        }
        
        if (response.data && response.data.stories && response.data.stories.length > 0) {
          // Update stories with fetched data
          const updatedStories = [...stories];
          updatedStories[targetUserIndex] = {
            ...updatedStories[targetUserIndex],
            stories: response.data.stories
          };
          
          // Process adjacent users if available
          if (response.data.adjacentUsers) {
            processAdjacentUsers(response.data.adjacentUsers);
          }
          
          // Update the stories via Redux
          dispatch(setStories(updatedStories));
          if (typeof onStoriesUpdate === "function") {
            onStoriesUpdate(updatedStories);
          }
          
          // Mark as prefetched in Redux
          dispatch(addPrefetchedUserId(targetUser.userId));
          
          // Now actually navigate to the target user/story
          setCurrentUserIndex(targetUserIndex);
          // Use first story if the specified index is invalid
          const validStoryIndex = (targetStoryIndex < response.data.stories.length) 
                                ? targetStoryIndex 
                                : 0;
          setCurrentStoryIndex(validStoryIndex);
          return true;
        } else {
          // No stories found for this user
          console.log(`No stories found for user ${targetUser.userId}`);
          return false;
        }
      } catch (error) {
        console.error("Error fetching story details:", error);
        if (checkIsOffline()) {
          toast.info("You're offline. Cannot load new stories right now.");
        } else {
          toast.error("Could not load stories");
        }
        return false;
      } finally {
        // Only clear loading if this is still the current navigation
        if (lastNavigationRef.current === navigationId) {
          setIsLoading(false);
        }
      }
    } finally {
      // Add a small delay before allowing the next navigation
      setTimeout(() => {
        if (lastNavigationRef.current === navigationId) {
          setProcessingNavigation(false);
          console.log("Navigation processing flag cleared");
        }
      }, 400); // Slightly longer delay to ensure stability
    }
  };


  const minSwipeDistance = useMemo(() => {
    // Responsive swipe threshold based on screen size
    return Math.min(window.innerWidth / 3.5, 150); // Cap at 150px max for large screens
  }, []);
  // Function to handle touch start
  const handleTouchStart = (e) => {
    // Don't start swipe if modals are open or we're already in a transition
    if (showMoreOptions || showViewersModal || isLoading || isTransitioning || processingNavigation) return;
    setTouchStart(e.targetTouches[0].clientX);
  };

  // Function to handle touch move
  const handleTouchMove = (e) => {
    if (touchStart === null || showMoreOptions || showViewersModal || isLoading || isTransitioning) return;
    const currentTouch = e.targetTouches[0].clientX;
    setTouchEnd(currentTouch);
    
    // Calculate and set the swipe distance for animation
    const distance = touchStart - currentTouch;
    setSwipeDistance(distance);
    
    // Prefetch the adjacent user's stories if swiping significantly
    if (Math.abs(distance) > minSwipeDistance / 2) {
      const nextUserId = distance > 0 
        ? adjacentUsers.right?.userId 
        : adjacentUsers.left?.userId;
        
      if (nextUserId && !prefetchedUserIds.has(nextUserId)) {
        prefetchAdjacentUserStories(nextUserId);
      }
    }
  };
  

  const handleTouchEnd = (e) => {
    if (touchStart === null || touchEnd === null || showMoreOptions || showViewersModal || isLoading || isTransitioning || processingNavigation) return;
    
    const distance = touchStart - touchEnd;
    const absDist = Math.abs(distance);
    
    // Only trigger if we've swiped at least 1/3 of the screen
    if (absDist > minSwipeDistance) {
      if (distance > 0) {
        // Swiped from right to left -> go to next user
        setIsTransitioning(true);
        setTransitionDirection('left');
        
        setTimeout(async () => {
          const success = await handleNextUser();
          console.log(`Next user navigation ${success ? 'succeeded' : 'failed'}`);
          setIsTransitioning(false);
          setTransitionDirection(null);
        }, 120); // Reduce from 300ms to 120ms to match faster animation
      } else {
        // Swiped from left to right -> go to previous user
        setIsTransitioning(true); 
        setTransitionDirection('right');
        
        setTimeout(async () => {
          const success = await handlePrevUser();
          console.log(`Previous user navigation ${success ? 'succeeded' : 'failed'}`);
          setIsTransitioning(false);
          setTransitionDirection(null);
        }, 120); // Reduce from 300ms to 120ms
      }
    }
    
    // Reset values
    setTouchStart(null);
    setTouchEnd(null);
    setSwipeDistance(0);
  };
  // Handle back button press
  useEffect(() => {
    const handleBackButton = (e) => {
      // Check if we're in story view
      if (document.body.contains(containerRef.current)) {
        e.preventDefault();
        // Update parent state with locally tracked changes before closing
        if (localStoriesRef.current && typeof onStoriesUpdate === "function") {
          onStoriesUpdate(localStoriesRef.current);
        }
        onClose(viewedStoryIds);
        
        // Push a new history state to replace the one we just intercepted
        window.history.pushState(null, document.title, window.location.href);
      }
    };

    // Push an entry to the history stack so we can intercept the back button
    window.history.pushState(null, document.title, window.location.href);
    
    // Listen for popstate (back button)
    window.addEventListener('popstate', handleBackButton);
    
    return () => {
      window.removeEventListener('popstate', handleBackButton);
    };
  }, [containerRef.current, viewedStoryIds]);

  useEffect(() => {
    localStoriesRef.current = JSON.parse(JSON.stringify(stories));
  }, []);

  const handleStoryLike = async (e) => {
    e.stopPropagation(); // Prevent event from bubbling up to story navigation
    
    if (!activeStory) return;
    
    try {
      // Call the storylike API endpoint
      const response = await axios.post(
        `${api}/post/storylike`,
        { storyId: activeStory.storyId },
        { withCredentials: true }
      );
      
      // Update the local state to reflect the new like status
      if (response.data) {
        const updatedStories = stories.map((userStory) => {
          if (userStory.userId === currentUser.userId) {
            return {
              ...userStory,
              stories: userStory.stories.map((story) => {
                if (story.storyId === activeStory.storyId) {
                  return { 
                    ...story, 
                    isLiked: response.data.liked // Set isLiked based on API response
                  };
                }
                return story;
              }),
            };
          }
          return userStory;
        });
        
        // Update stories via the provided callback
        if (typeof onStoriesUpdate === "function") {
          onStoriesUpdate(updatedStories);
        }
      }
    } catch (error) {
      console.error("Error liking/unliking story:", error);
    }
  };
  
  
  // New state for tracking adjacent users
  const [adjacentUsers, setAdjacentUsers] = useState({
    left: null,
    right: null
  });
  

  
  useEffect(() => {
    pausedRef.current = showMoreOptions || showViewersModal;
  }, [showMoreOptions, showViewersModal]);

  // Updated function to prefetch adjacent users' stories
  const prefetchAdjacentUserStories = async (userId) => {
    // Don't prefetch if we've already done it
    if (prefetchedUserIds.has(userId)) return;
    
    // Don't attempt prefetching while offline
    if (checkIsOffline()) return;
    
    try {
      const response = await axios.get(`${api}/post/user-stories/${userId}`, {
        withCredentials: true,
        headers: { accessToken: localStorage.getItem("accessToken") },
        timeout: 5000 // Short timeout for prefetch
      });
      
      if (!response.data || !response.data.stories) return;
      
      // Update stories array with the fetched details
      const updatedStories = [...stories];
      const indexToUpdate = updatedStories.findIndex(s => String(s.userId) === String(userId));
      
      if (indexToUpdate !== -1) {
        updatedStories[indexToUpdate] = {
          ...updatedStories[indexToUpdate],
          stories: response.data.stories
        };
        
        // Update Redux and callback
        dispatch(setStories(updatedStories));
        if (typeof onStoriesUpdate === "function") {
          onStoriesUpdate(updatedStories);
        }
        
        // Mark this user's stories as prefetched in Redux
        dispatch(addPrefetchedUserId(userId));
      }
    } catch (error) {
      // Just log the error silently - this is just prefetch
      console.log("Error prefetching stories:", error.message);
    }
  };

  // Function to process the adjacentUsers data from the API
  const processAdjacentUsers = (adjacentUsersData) => {
    if (!adjacentUsersData || !Array.isArray(adjacentUsersData) || adjacentUsersData.length === 0) return;
    
    // Find users that should be to the left and right based on the stories array
    const currentUserIdIndex = stories.findIndex(
      (story) => String(story.userId) === String(selectedUserId)
    );
    
    if (currentUserIdIndex === -1) return;
    
    // Check for each adjacent user if they exist in the stories array
    adjacentUsersData.forEach(adjacentUser => {
      // Find this user in our stories array
      const userIndex = stories.findIndex(
        story => String(story.userId) === String(adjacentUser.userId)
      );
      
      if (userIndex !== -1) return; // Already in our stories array
      
      // Create a user story object from the adjacent user data
      const newUserStory = {
        userId: adjacentUser.userId,
        username: adjacentUser.username,
        profilePicture: adjacentUser.profilePicture,
        verified: adjacentUser.verified,
        viewedAll: true, // Default until we fetch detailed data
        hasStories: adjacentUser.hasStories,
        storyCount: adjacentUser.storyCount,
        stories: [] // Will be populated when needed
      };
      
      // Calculate the correct position relative to current user
      const updatedStories = [...stories];
      if (userIndex === -1) {
        if (updatedStories.length <= currentUserIdIndex + 1) {
          // Add to the end if we don't have enough elements
          updatedStories.push(newUserStory);
        } else {
          // Insert after the current user
          updatedStories.splice(currentUserIdIndex + 1, 0, newUserStory);
        }
        
        // Update stories via callback
        if (typeof onStoriesUpdate === "function") {
          onStoriesUpdate(updatedStories);
        }
      }
    });
  };

  const handleAssetLoaded = () => {
    // Debounce to prevent rapid multiple calls
    if (window.assetLoadTimeout) {
      clearTimeout(window.assetLoadTimeout);
    }
    
    window.assetLoadTimeout = setTimeout(() => {
      setAssetsToLoad((prev) => {
        const newCount = Math.max(0, prev - 1);
        if (newCount <= 0) {
          setStoryLoaded(true);
        }
        return newCount;
      });
    }, 50);
  };

  const handleShowViewers = async (e) => {
    e.stopPropagation();
    setShowMoreOptions(false); // close more options if open
    if (!activeStory?.storyId) return;
    try {
      const response = await axios.get(
        `${api}/post/storyviewedBy/${activeStory.storyId}`,
        { withCredentials: true }
      );
      if (response.data && response.data.viewers) {
        setViewers(response.data.viewers);
      }
      setShowViewersModal(true);
    } catch (error) {
      console.error(error);
    }
  };
  const handleDeleteStory = async (storyId, e) => {
    e.stopPropagation();
    try {
      await axios.delete(`${api}/post/story-delete`, {
        data: { storyId },
        withCredentials: true,
      });
      // Local update: Remove the deleted story from the "stories" array.
      const updatedStories = stories.map((userStory) => {
        // Compare trimmed user IDs (assuming loggedInUser is the current user's id)
        if (userStory.userId.trim() === loggedInUser.trim()) {
          return {
            ...userStory,
            stories: userStory.stories.filter(
              (story) => story.storyId !== storyId
            ),
          };
        }
        return userStory;
      });
      // Call the callback to update stories locally, if provided
      if (typeof onStoriesUpdate === "function") {
        onStoriesUpdate(updatedStories);
      }
    } catch (error) {
      console.error(error);
    }
  };
  const handlePrevStoryStage = () => {
    if (processingNavigation) return;
    
    setProcessingNavigation(true);
    
    try {
      if (currentStoryIndex > 0) {
        setCurrentStoryIndex(currentStoryIndex - 1);
      } else {
        // Jump to previous user: set story index to the last story of the previous user
        const prevUserIndex = (currentUserIndex - 1 + stories.length) % stories.length;
        setCurrentUserIndex(prevUserIndex);
        const prevUser = stories[prevUserIndex];
        setCurrentStoryIndex(prevUser.stories.length - 1);
      }
    } finally {
      // Add delay to prevent rapid navigation
      setTimeout(() => setProcessingNavigation(false), 300);
    }
  };
  
  useEffect(() => {
    if (!processingNavigation) {
      // Get unique users from stories array
      const unique = stories.filter(
        (story, idx, self) => idx === self.findIndex(s => s.userId === story.userId)
      );
      
      // Preserve viewed status from previous storiesForUI
      setStoriesForUI(prev => {
        // Merge new stories with existing viewed status
        return unique.map(newUserStory => {
          // Find matching user in previous stories
          const existingUserStory = prev.find(p => p.userId === newUserStory.userId);
          
          // If no existing data or no stories to merge, use the new data
          if (!existingUserStory || !existingUserStory.stories || !existingUserStory.stories.length) {
            return newUserStory;
          }
          
          // Preserve viewed status for stories we already have
          return {
            ...newUserStory,
            stories: newUserStory.stories.map(newStory => {
              const existingStory = existingUserStory.stories.find(
                s => s.storyId === newStory.storyId
              );
              // If story exists in previous data and was viewed, keep that status
              if (existingStory && existingStory.viewed) {
                return { ...newStory, viewed: true };
              }
              return newStory;
            })
          };
        });
      });
    }
  }, [stories, processingNavigation]);
  

  const handleStageClick = (e) => {
    if (processingNavigation || showMoreOptions || showViewersModal || isLoading) return;
    
    const rect = containerRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    
    if (clickX > rect.width / 2) {
      handleNextStory();
    } else {
      handlePrevStory();
    }
  };

  useEffect(() => {
    const handleResize = () => setScreenWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    // Only initialize indices if not already done
    if (!initializedRef.current && stories && stories.length > 0 && selectedUserId) {
      const selectedIndex = stories.findIndex(
        (userStory) => userStory.userId === selectedUserId
      );
      if (selectedIndex >= 0) {
        setCurrentUserIndex(selectedIndex);
        setCurrentStoryIndex(0);
        initializedRef.current = true; // Mark as initialized
      }
    }
  }, [stories, selectedUserId]);

  useEffect(() => {
    return () => {
      initializedRef.current = false; // Reset when component unmounts
    };
  }, []);

  // New effect to handle prefetching adjacent users' stories
  useEffect(() => {
    if (!stories.length) return;
    
    // Determine adjacent user indices
    const leftUserIndex = (currentUserIndex - 1 + stories.length) % stories.length;
    const rightUserIndex = (currentUserIndex + 1) % stories.length;
    
    // Get user data
    const leftUser = stories[leftUserIndex];
    const rightUser = stories[rightUserIndex];
    
    // Update adjacentUsers state
    setAdjacentUsers({
      left: leftUser || null,
      right: rightUser || null
    });
    
    // Prefetch stories for adjacent users if needed
    if (leftUser?.userId && !prefetchedUserIds.has(leftUser.userId)) {
      prefetchAdjacentUserStories(leftUser.userId);
    }
    
    if (rightUser?.userId && !prefetchedUserIds.has(rightUser.userId)) {
      prefetchAdjacentUserStories(rightUser.userId);
    }
  }, [currentUserIndex, stories]);

  const currentUser = stories[currentUserIndex];
  const activeStory = currentUser?.stories[currentStoryIndex];

  // Modified effect to fetch the initial story data and process adjacent users
  useEffect(() => {
    const fetchStoryData = async () => {
      if (!selectedUserId) return;
      
      // ** KEY CHANGE: Check if we have already prefetched this user's stories **
      if (prefetchedUserIds.has(selectedUserId)) {
        console.log("Using prefetched stories for user", selectedUserId);
        return;
      }
      
      // Don't try to fetch if offline
      if (checkIsOffline()) {
        console.log("Offline: Using available stories only");
        return;
      }
      
      try {
        setIsLoading(true);
        const response = await axios.get(`${api}/post/user-stories/${selectedUserId}`, {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") },
          timeout: 8000
        });
        
        if (response.data?.stories) {
          // Update the story data for the selected user
          const updatedStories = [...stories];
          const selectedIndex = updatedStories.findIndex(
            s => String(s.userId) === String(selectedUserId)
          );
          
          if (selectedIndex !== -1) {
            updatedStories[selectedIndex] = {
              ...updatedStories[selectedIndex],
              stories: response.data.stories
            };
            
            // Process adjacent users data if available
            if (response.data.adjacentUsers) {
              processAdjacentUsers(response.data.adjacentUsers);
            }
            
            // Update stories array
            if (typeof onStoriesUpdate === "function") {
              onStoriesUpdate(updatedStories);
            }
            
            // Mark as prefetched
            dispatch(addPrefetchedUserId(selectedUserId));
          }
        }
      } catch (error) {
        console.error("Error fetching story details:", error);
        
        if (checkIsOffline()) {
          console.log("Offline: Using available stories only");
        } else {
          toast.error("Could not load story details");
        }
      } finally {
        setIsLoading(false);
      }
    };
    
    // Only fetch if we haven't already and we're online
    if (selectedUserId && !prefetchedUserIds.has(selectedUserId) && isOnline) {
      fetchStoryData();
    }
  }, [selectedUserId, isOnline]); // Add isOnline dependency

  useEffect(() => {
    if (activeStory && activeStory.storyId && !viewedStoryIds.includes(activeStory.storyId)) {
      setViewedStoryIds((prev) => [...prev, activeStory.storyId]);
    }
  }, [activeStory]);

  // Autoplay video when available
  useEffect(() => {
    if (videoRef) {
      const playVideo = async () => {
        try {
          videoRef.muted = false;
          await videoRef.play();
        } catch (error) {
        }
      };
      const handleInteraction = () => {
        playVideo();
        document.removeEventListener("click", handleInteraction);
      };
      document.addEventListener("click", handleInteraction);
      return () => document.removeEventListener("click", handleInteraction);
    }
  }, [videoRef]);

  // Measure stage size for proper scaling
  useLayoutEffect(() => {
    const updateStageSize = () => {
      if (containerRef.current) {
        const { width, height } = containerRef.current.getBoundingClientRect();
        setStageSize({
          width: width > 0 ? width : 380,
          height: height > 0 ? height : 700,
        });
      }
    };
    const timeout = setTimeout(updateStageSize, 100);
    window.addEventListener("resize", updateStageSize);
    return () => {
      clearTimeout(timeout);
      window.removeEventListener("resize", updateStageSize);
    };
  }, []);

  // Background color based on active story (fallback for small screens)
  useEffect(() => {
    const updateBackground = () => {
      const isSmall = window.innerWidth < 500;
      setBg(isSmall ? activeStory?.bgcolor || "#0a0a0a" : "#0a0a0a");
    };
    updateBackground();
    window.addEventListener("resize", updateBackground);
    return () => window.removeEventListener("resize", updateBackground);
  }, [activeStory]);

const handleNextStory = async () => {
  if (!currentUser) return;
  
  // Already at the last story of current user?
  if (currentStoryIndex >= currentStories.length - 1) {
    // Calculate the next user index
    const nextUserIndex = currentUserIndex + 1;
    
    // If we reached the last user, close the story viewer instead of looping back
    if (nextUserIndex >= stories.length) {
      // Clean up and close the story display
      if (localStoriesRef.current && typeof onStoriesUpdate === "function") {
        onStoriesUpdate(localStoriesRef.current);
      }
      onClose(viewedStoryIds);
      return true;
    }
    
    // Otherwise navigate to first story of next user
    return navigateToStory(nextUserIndex, 0, { reason: "last-story-of-user" });
  } else {
    // Simply move to next story in current user
    setCurrentStoryIndex(currentStoryIndex + 1);
    return true;
  }
};

const handlePrevStory = () => {
  if (!currentUser) return;
  
  // Already at the first story of current user? Go to previous user
  if (currentStoryIndex <= 0) {
    // Calculate the previous user index
    const prevUserIndex = (currentUserIndex - 1 + stories.length) % stories.length;
    const prevUser = stories[prevUserIndex];
    
    // Navigate to the last story of previous user
    const targetStoryIndex = (prevUser.stories && prevUser.stories.length > 0) 
                           ? prevUser.stories.length - 1 
                           : 0;
    
    return navigateToStory(prevUserIndex, targetStoryIndex, { reason: "first-story-of-user" });
  } else {
    // Simply move to previous story in current user
    setCurrentStoryIndex(currentStoryIndex - 1);
    return true;
  }
};

const handleNextUser = async () => {
  // Prevent duplicate navigation requests
  if (processingNavigation || isTransitioning) {
    console.log('Navigation blocked: already in progress');
    return false;
  }

  // Calculate the next user index
  const nextUserIndex = (currentUserIndex + 1) % stories.length;
  console.log(`Attempting to navigate to next user: ${nextUserIndex}`);
  
  // Wait for navigation to complete
  const success = await navigateToStory(nextUserIndex, 0, { reason: "next-user-button" });
  
  // Log success/failure for debugging
  console.log(`Navigation to user ${nextUserIndex} ${success ? 'succeeded' : 'failed'}`);
  
  return success;
};

const handlePrevUser = async () => {
  const prevUserIndex = (currentUserIndex - 1 + stories.length) % stories.length;
  console.log(`Attempting to navigate to previous user: ${prevUserIndex}`);
  return await navigateToStory(prevUserIndex, 0, { reason: "prev-user-button" });
};

  useEffect(() => {
    if (activeStory) {
      // Count images and video (if any) in the active story.
      const imageCount = activeStory.elements.filter(el => el.type === "image").length;
      const videoCount = activeStory.elements.some(el => el.type === "video") ? 1 : 0;
      const totalAssets = imageCount + videoCount;
      setAssetsToLoad(totalAssets);
      // Set to false until assets load
      setStoryLoaded(totalAssets === 0);
    }
  }, [activeStory]);


  useEffect(() => {
    if (!activeStory || !activeStory.storyId || !currentUser) return;
    
    // Always locally mark the story as viewed immediately
    if (!viewedStoryIds.includes(activeStory.storyId)) {
      setViewedStoryIds((prev) => [...prev, activeStory.storyId]);
      
      // Update story viewed status in Redux
      dispatch(updateStoryViewed({
        userId: currentUser.userId,
        storyId: activeStory.storyId
      }));
      
      // Only make the API call if this story hasn't been marked as viewed yet
      // and we're online
      if (!activeStory.viewed && isOnline) {
        // Create a local copy of stories for UI updates
        const updatedLocalStories = JSON.parse(JSON.stringify(stories));
        
        // Update our local reference
        for (const userStory of updatedLocalStories) {
          if (userStory.userId === currentUser.userId) {
            for (const story of userStory.stories) {
              if (story.storyId === activeStory.storyId) {
                story.viewed = true;
                break;
              }
            }
            
            // Check if all stories are now viewed and update viewedAll flag
            const allViewed = userStory.stories.every(story => story.viewed);
            userStory.viewedAll = allViewed;
            break;
          }
        }
        
        // Update our local reference without triggering re-render
        localStoriesRef.current = updatedLocalStories;
        
        // Also update storiesForUI to reflect viewed status in side panels
        setStoriesForUI(prev => {
          return prev.map(userStory => {
            if (userStory.userId === currentUser.userId) {
              const updatedStories = userStory.stories.map(story => {
                if (story.storyId === activeStory.storyId) {
                  return { ...story, viewed: true };
                }
                return story;
              });
              
              // Check if all stories are now viewed
              const allViewed = updatedStories.every(story => story.viewed);
              
              return {
                ...userStory,
                stories: updatedStories,
                viewedAll: allViewed
              };
            }
            return userStory;
          });
        });
        
        // Make the API call only if we're online
        if (isOnline) {
          axios.post(
            `${api}/post/storyviewed`,
            { storyId: activeStory.storyId },
            { withCredentials: true }
          ).catch((error) => {
            console.error("Error marking story as viewed:", error);
          });
        }
      }
    }
  }, [activeStory, currentUser?.userId, dispatch, isOnline]);

  const currentStories = useMemo(() => {
    return currentUser?.stories || [];
  }, [currentUser]);


  const renderVideo = () => {
    if (!activeStory) return null;
    const videoElement = activeStory.elements.find((el) => el.type === "video");
    if (!videoElement) return null;
  
    const originalWidth = videoElement.dimensions?.width || 0;
    const originalHeight = videoElement.dimensions?.height || 0;
    const scale = videoElement.transform?.scale || 1;
    const scaledWidth = originalWidth * scale;
    const scaledHeight = originalHeight * scale;
  
    const styleObj = {
      zIndex: videoElement.z_index || 1,
      position: "absolute",
      top: videoElement.position?.y || 0,
      left: videoElement.position?.x || 0,
      width: scaledWidth,
      height: scaledHeight,
      objectFit: "cover",
      transform: `rotate(${videoElement.transform?.rotation || 0}deg)`,
      transformOrigin: "top left",
    };
  
    // Create a unique key so React mounts a new element for a different story/video.
    const videoKey = `video_${currentUserIndex}_${currentStoryIndex}_${videoElement.content}`;
  
    return (
      <video
        key={videoKey}
        ref={(el) => {
          if (el && el !== videoRef) {
            setVideoRef(el);
            // Mark the story as loaded once the video is ready
            handleAssetLoaded();
          }
        }}
        autoPlay
        playsInline
        style={styleObj}
        crossOrigin="anonymous"
        onLoadedMetadata={(e) => {
          const duration = e.target.duration;
          if (duration && duration > 0) {
            setStoryDuration(duration);
          }
        }}
        // Prevent duplicate calls with a reference check
        onEnded={() => {
          if (!processingNavigation) {
            // For the last story of the last user, we need special handling
            if (currentUserIndex === stories.length - 1 && 
                currentStoryIndex === currentStories.length - 1) {
              // We're at the very last story - close the story viewer
              if (localStoriesRef.current && typeof onStoriesUpdate === "function") {
                onStoriesUpdate(localStoriesRef.current);
              }
              onClose(viewedStoryIds);
            } else {
              // Otherwise, proceed to the next story as usual
              handleNextStory();
            }
          }
        }}
      >
        <source
          src={`${cloud}/cloudofscubiee/storyMedia/${videoElement.content}`}
          type="video/mp4"
        />
        Your browser does not support the video tag.
      </video>
    );
  };
  useEffect(() => {
    if (activeStory) {
      // Reset progress and flush any pending timers
      progressRef.current = 0;
      setProgress(0);

      // Pause and reset any existing video ref so it doesn't carry over audio/playing state.
      if (videoRef) {
        videoRef.pause();
        videoRef.currentTime = 0;
        setVideoRef(null);
      }
      // For non-video stories, set a default duration.
      const hasVideo = activeStory.elements?.some((el) => el.type === "video");
      if (!hasVideo) {
        setStoryDuration(5);
        
        // For non-video stories, mark as loaded after a brief delay
        // This gives images time to load
        setTimeout(() => {
          if (!storyLoaded) {
            setStoryLoaded(true);
          }
        }, 300);
      }
      // Video stories will update their duration in onLoadedMetadata.
      
      // Reset story loaded state
      setStoryLoaded(false);
    }
  }, [activeStory]);

  // Replace the existing progress effect with this improved version
  useEffect(() => {
    // Reset progress at the start
    progressRef.current = 0;
    setProgress(0);
    
    // Don't start the timer if the story isn't loaded yet or if navigation is in progress
    if (!storyLoaded || processingNavigation || !activeStory) return;
    
    // Create a unique timer ID for this specific story instance
    const timerId = `timer_${currentUserIndex}_${currentStoryIndex}_${Date.now()}`;
    
    // Configure the timer
    const tickInterval = 250; // slightly faster updates for smoother progress
    const increment = (tickInterval / (storyDuration * 1000)) * 100;
    
    // Store the timer ID for cleanup
    const timer = setInterval(() => {
      // Skip if paused or if navigation is in progress
      if (pausedRef.current || processingNavigation) return;
      
      // Update progress
      progressRef.current += increment;
      
      // Check if we've reached 100%
      if (progressRef.current >= 100) {
        clearInterval(timer);
        if (!processingNavigation) {
          // For the last story of the last user, we need special handling
          if (currentUserIndex === stories.length - 1 && 
              currentStoryIndex === currentStories.length - 1) {
            // We're at the very last story - close the story viewer
            if (localStoriesRef.current && typeof onStoriesUpdate === "function") {
              onStoriesUpdate(localStoriesRef.current);
            }
            onClose(viewedStoryIds);
          } else {
            // Otherwise, proceed to the next story as usual
            handleNextStory();
          }
        }
      } else {
        setProgress(progressRef.current);
      }
    }, tickInterval);
    
    // Clean up timer when component unmounts or when story changes
    return () => clearInterval(timer);
  }, [currentUserIndex, currentStoryIndex, storyDuration, storyLoaded, processingNavigation, stories.length, currentStories.length]);




  // Update the PostOverlay component in DisplayStory.jsx
const PostOverlay = React.useMemo(() => {
  const Component = ({ postId, style }) => {
    const [postData, setPostData] = React.useState(null);
    const [mediaItems, setMediaItems] = React.useState([]);
    
    React.useEffect(() => {
      const fetchPostData = async () => {
        try {
          const response = await fetch(`${api}/post/summary/${postId}`);
          const data = await response.json();
          setPostData(data);
          
          // Process media items when data is available
          if (data) {
            processMediaItems(data);
          }
        } catch (error) {
          console.error("Error fetching post summary:", error);
        }
      };
      
      if (postId) {
        fetchPostData();
      }
    }, [postId]);

    const processMediaItems = (post) => {
      if (!post.media || post.media.length === 0) return;
      
      // Map each media item to its appropriate URL
      const items = post.media.map(item => {
        const isVideo = item.type === 'video';
        let url;
        
        if (post.isShort) {
          // Path for shorts
          url = isVideo 
            ? `${cloud}/cloudofscubiee/shortVideos/${item.url}`
            : `${cloud}/cloudofscubiee/shortImages/${item.url}`;
        } else {
          // Path for regular posts
          url = isVideo
            ? `${cloud}/cloudofscubiee/postVideos/${item.url}`
            : `${cloud}/cloudofscubiee/postImages/${item.url}`;
        }
        
        return {
          url,
          type: isVideo ? 'video' : 'image'
        };
      });
      
      setMediaItems(items);
    };

    if (!postData) return null;

    return (
      <div
        style={{
          ...style,
          position: "relative",
          width: "375px",
          height: `${375 * (9 / 10)}px`, // equals 337.5px
          background: "#0a0a0a",
          borderRadius: "8px",
          overflow: "hidden",
        }}
      >
        {/* Profile image */}
        <img
          src={
            postData.author.profilePicture ?
            `${cloud}/cloudofscubiee/profilePic/${postData.author.profilePicture}` : "/logos/DefaultPicture.png"}
          alt={postData.author.username}
          className="bg-gray-300"
          style={{
            position: "absolute",
            left: "8px",
            top: "6px",
            width: "30px",
            height: "30px",
            borderRadius: "50%",
            objectFit: "cover",
            zIndex: 2,
          }}
        />
        {/* Username text */}
        <div
          style={{
            position: "absolute",
            left: "46px",
            top: "9px",
            fontSize: "14.5px",
            color: "#ccc",
            fontFamily: "sans-serif",
            zIndex: 2,
          }}
        >
          {postData.author.username}
        </div>
        
        {/* Media grid container */}
        <div
          style={{
            position: "absolute",
            left: "0px",
            top: "40px",
            width: "375px",
            height: "238px",
            display: "grid",
            gridTemplateColumns: 
              mediaItems.length === 1 ? "1fr" : 
              mediaItems.length === 2 ? "1fr 1fr" :
              mediaItems.length === 4 ? "1fr 1fr" : "1fr 1fr 1fr",
            gridTemplateRows: 
              mediaItems.length <= 3 ? "1fr" : "1fr 1fr",
            gap: "2px",
          }}
        >
          {mediaItems.map((item, idx) => (
            item.type === 'video' ? (
              <video
                key={`media_${idx}`}
                src={item.url}
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                }}
                autoPlay
                loop
                muted
              />
            ) : (
              <img
                key={`media_${idx}`}
                src={item.url}
                alt="Post media"
                style={{
                  width: "100%",
                  height: "100%",
                  objectFit: "cover",
                }}
              />
            )
          ))}
        </div>
        
        {/* Post title/content text */}
        <div
          style={{
            position: "absolute",
            left: "8px",
            top: "288px",
            fontSize: "15.5px",
            color: "#ccc",
            fontFamily: "sans-serif",
            width: "354px",
            lineHeight: 1.2,
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 2,
            overflow: "hidden",
          }}
        >
          {postData.title || postData.content}
        </div>
      </div>
    );
  };

  // Comparator to prevent re-renders
  return React.memo(Component, (prev, next) => {
    return (
      prev.postId === next.postId &&
      shallowEqual(prev.style, next.style)
    );
  });
}, []);


  const shallowEqual = (obj1, obj2) => {
    const keys1 = Object.keys(obj1 || {});
    const keys2 = Object.keys(obj2 || {});
    if (keys1.length !== keys2.length) return false;
    for (let key of keys1) {
      if (obj1[key] !== obj2[key]) return false;
    }
    return true;
  };
  const message =
  currentUser.userId &&
  loggedInUser?.id &&
  currentUser.userId.trim() === loggedInUser.id.trim()
    ? "This is the user's story"
    : "This is not the user's story";
    const buildImageTransformStyles = (elem) => {
      const offsetX = elem.offset_x || 0;
      const offsetY = elem.offset_y || 0;
      const rotation = elem.transform?.rotation || 0;
      // Do not include scale here.
      return {
        transform: `translate(${offsetX}px, ${offsetY}px) rotate(${rotation}deg)`,
        transformOrigin: "top left",
      };
    };
    
    const buildTransformStyles = (elem) => {
      const offsetX = elem.offset_x || 0;
      const offsetY = elem.offset_y || 0;
      const rotation = elem.transform?.rotation || 0;
      // Use the scale from the transform object.
      const scale = elem.transform?.scale || 1;
      return {
        transform: `translate(${offsetX}px, ${offsetY}px) rotate(${rotation}deg) scale(${scale})`,
        transformOrigin: "top left",
      };
    };
    
    const renderImages = () => {
      if (!activeStory) return null;
      const imageElements = activeStory.elements.filter((el) => el.type === "image");
      return imageElements.map((imgElem, idx) => {
        // Obtain the scale factor from a single source.
        const scaleFactor = imgElem.transform?.scale || imgElem.scaleX || 1;
        // Compute dimensions once using the stored scale factor.
        const displayWidth = imgElem.originalWidth * scaleFactor;
        const displayHeight = imgElem.originalHeight * scaleFactor;
    
        // Choose transform styles based on scale condition.
        const transformStyles =
          scaleFactor < 1 ? buildImageTransformStyles(imgElem)
                          : buildTransformStyles(imgElem);
    
        const styleObj = {
          zIndex: imgElem.z_index || 1,
          position: "absolute",
          top: imgElem.position?.y || 0,
          left: imgElem.position?.x || 0,
          width: displayWidth,
          height: displayHeight,
          objectFit: "cover",
          ...transformStyles,
        };
    
        return (
          <img
            key={`img_${idx}`}
            src={`${cloud}/cloudofscubiee/storyMedia/${imgElem.content}`}
            alt="storyImages"
            style={styleObj}
            onLoad={handleAssetLoaded}
          />
        );
      });
    };
  // Helper to get text gradient colors
  const getTextGradient = () => ({
    colors: [
      "#FF3E6B",
      "#9C27B0",
      "#3F51B5",
      "#2196F3",
      "#00BCD4",
      "#4CAF50",
      "#FFC107",
    ],
  });

  const renderOverlay = (element, index) => {
    const x = element.position?.x || 0;
    const y = element.position?.y || 0;
    const rotation = element.transform?.rotation || 0;
    const scale = element.transform?.scale || 1;
  
    // Check if this is a post element
    if (element.type === "post") {
      // For post elements, render the PostOverlay component
      return (
        <div
          key={index}
          style={{
            position: "absolute",
            transform: `translate(${x}px, ${y}px) rotate(${rotation}deg) scale(${scale})`,
            transformOrigin: "top left",
            zIndex: element.z_index || 1,
          }}
        >
          <PostOverlay postId={element.content} />
        </div>
      );
    }
  
    // Determine if the element is interactive.
    const isInteractive =
      element.type === "link" ||
      element.type === "mention" ||
      element.type === "hashtag";
  
    // Rest of your existing code for text elements
    const isSpecialText = isInteractive;
  
    const textContent =
      element.type === "mention"
        ? `@ ${element.content}`
        : element.type === "link"
        ? `🔗 ${element.content}`
        : element.type === "hashtag"
        ? `# ${element.content}`
        : element.content;
    const gradientColors = getTextGradient().colors;
    const backgroundColor = isInteractive ? "#ffffff" : element.backgroundColor || "transparent";
  
    const handleClick = (e) => {
      // Prevent the click from bubbling up to the stage.
      e.stopPropagation();
      if (element.type === "link") {
        window.open(element.content, "_blank");
      } else if (element.type === "mention") {
        window.location.href = `/${element.content}`;
      } else if (element.type === "hashtag") {
        // Navigate directly to the search page with the tag parameter
        window.location.href = `/search?tag=${encodeURIComponent(element.content)}`;
      }
    };
  
    return (
      <div
        key={index}
        style={{
          position: "absolute",
          transform: `translate(${x}px, ${y}px) rotate(${rotation}deg) scale(${scale})`,
          transformOrigin: "top left",
          zIndex: element.z_index || 1,
          cursor: isInteractive ? "pointer" : "default",
        }}
        onClick={isInteractive ? handleClick : undefined}
      >
        <div
          style={{
            padding: "5px",
            borderRadius: "6px",
            backgroundColor,
            paddingTop: "2px",
            paddingBottom: "2px",
            display: "inline-block",
          }}
        >
          <div
            style={{
              fontSize: "20px",
              fontWeight: isSpecialText ? "bold" : "normal",
              ...(isSpecialText
                ? {
                    background: `linear-gradient(90deg, ${gradientColors[0]} 0%, ${gradientColors[1]} 25%, ${gradientColors[2]} 50%, ${gradientColors[3]} 75%, ${gradientColors[4]} 100%)`,
                    WebkitBackgroundClip: "text",
                    WebkitTextFillColor: "transparent",
                    backgroundClip: "text",
                  }
                : { color: element.textColor || "#fff" }),
              whiteSpace: "nowrap",
              pointerEvents: "auto",
              userSelect: "none",
              lineHeight: "normal",
            }}
          >
            {textContent}
          </div>
        </div>
      </div>
    );
  };

  if (!stories.length || !activeStory)
    return <div>No stories found or loading story...</div>;

// Use storiesForUI for UI rendering in the side panels
const leftStories = screenWidth > 768 ? storiesForUI.slice(Math.max(0, currentUserIndex - 2), currentUserIndex) : [];
const rightStories = screenWidth > 768 ? storiesForUI.slice(currentUserIndex + 1, currentUserIndex + 3) : [];


    return (
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          width: "100%",
          height: "100vh",
          // Keep the main background constant as the current story's background
          background: bg,
          zIndex: 1000,
          display: "flex",
          justifyContent: "center",
          overflow: "hidden"
        }}
        className="md:items-center"
        onTouchStart={window.innerWidth < 500 ? handleTouchStart : undefined}
        onTouchMove={window.innerWidth < 500 ? handleTouchMove : undefined}
        onTouchEnd={window.innerWidth < 500 ? handleTouchEnd : undefined}
      >
        {/* Add offline indicator */}
        {!isOnline && (
          <div 
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              backgroundColor: "#CA8A04",
              color: "white",
              padding: "4px 0",
              textAlign: "center",
              fontSize: "12px",
              zIndex: 2000,
              fontWeight: 500
            }}
          >
            You're offline. Using cached stories.
          </div>
        )}
        {/* Background split effect for swiping - only on mobile */}
        {window.innerWidth < 500 && swipeDistance !== 0 && (
  <div
    style={{
      position: "absolute",
      top: 0,
      right: swipeDistance > 0 ? 0 : "auto",
      left: swipeDistance > 0 ? "auto" : 0,
      width: `${Math.min(Math.abs(swipeDistance), window.innerWidth)}px`,
      height: "100vh",
      background: swipeDistance > 0
        ? (adjacentUsers.right?.stories?.[0]?.bgcolor || "#0a0a0a")
        : (adjacentUsers.left?.stories?.[0]?.bgcolor || "#0a0a0a"),
      zIndex: -1,
    }}
  />
)}

    
        {/* Full background during complete transitions */}
        {isTransitioning && window.innerWidth < 500 && (
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              width: "100vw",
              height: "100vh",
              background: transitionDirection === 'left'
                ? (adjacentUsers.right?.stories?.[0]?.bgcolor || "#0a0a0a")
                : (adjacentUsers.left?.stories?.[0]?.bgcolor || "#0a0a0a"),
              zIndex: -1,
              opacity: 1,
              transition: "opacity 0.12s ease-out",
            }}
          />
        )}
        
        {/* Wrapper to position stage, side previews and buttons */}
        <div style={{ position: "relative" }}>
          
          {/* CURRENT STORY CONTAINER */}
          <div style={{ position: "relative" }}>
  {/* Current story - central content */}
  <div
  ref={containerRef}
  className="[aspect-ratio:9/16] mt-2 max-h-[700px] max-w-[380px] max-md:mx-2"
  style={{
    position: "relative",
    opacity: isTransitioning ? '0.8' : '1',
    zIndex: 1,
    transform: isTransitioning 
      ? `translateX(${transitionDirection === 'left' ? '-' : ''}100%)`
      : window.innerWidth < 500 && swipeDistance !== 0
        ? `translateX(${-swipeDistance}px)`
        : 'none',
    // Make the transition faster - reduce from 0.3s to 0.15s
    transition: isTransitioning ? "transform 0.15s ease-out" : "none",
  }}
>
              {/* Progress bars */}
              <div className="absolute top-0 left-0 right-0 flex gap-1 z-[100]">
                {currentUser.stories.map((story, idx) => {
                  let barWidth = "0%";
                  if (idx < currentStoryIndex) {
                    barWidth = "100%";
                  } else if (idx === currentStoryIndex) {
                    barWidth = `${progress}%`;
                  }
                  return (
                    <div key={idx} className="flex-1 bg-gray-300 h-[3px] rounded">
                      <div
                        style={{
                          width: barWidth,
                          transitionDuration:
                            idx < currentStoryIndex
                              ? "0ms"
                              : barWidth === "0%"
                              ? "0ms"
                              : "300ms",
                        }}
                        className="h-full bg-gradient-to-r from-cyan-600 to-blue-400 ease-linear rounded"
                      />
                    </div>
                  );
                })}
              </div>
    
              {/* User info bar */}
              <div className="absolute top-2 left-1 w-full flex items-center justify-between p-2 z-[1000] bg-transparent">
                <div className="flex items-center">
                  <img
                    src={
                      currentUser.profilePicture ?
                      `${cloud}/cloudofscubiee/profilePic/${currentUser.profilePicture}` : "/logos/DefaultPicture.png"}
                    alt={currentUser.username}
                    className="w-9 h-9 rounded-full bg-gray-300 object-cover"
                  />
                  <span className="ml-4 text-white font-semibold">
                    {currentUser.username}
                  </span>
                </div>
                {/* More options button */}
                {loggedInUser && currentUser.userId === userData.id && (
                  <div className="relative p-1 mr-2 rounded-full bg-black/20">
                    <IoMdMore
                      className="text-white text-xl cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowViewersModal(false);
                        setShowMoreOptions((prev) => !prev);
                      }}
                    />
                    {showMoreOptions && (
                      <div ref={moreOptionsRef} className="absolute animate-fadeIn rounded-md top-full right-2 border-[1px] border-gray-800 px-2 mt-1 bg-[#0f0f0f] text-white py-2 rounded-full">
                        <button
                          className="text-sm font-ubuntu mb-1 font-medium hover:bg-black/30 px-8 py-1"
                          onClick={(e) => handleDeleteStory(activeStory.storyId, e)}
                        >
                          Delete
                        </button>
                        <div className="w-full bg-slate-600 h-[1px]"></div>
                        <button
                          className="text-sm font-ubuntu font-medium px-8 mt-1 hover:bg-black/30 px-2 py-1"
                          onClick={() => setShowMoreOptions((prev) => !prev)}
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
    
              {/* Story content */}
              <div
                className=""
                style={{
                  position: "relative",
                  width: stageSize.width,
                  height: stageSize.height,
                  background: activeStory.bgcolor || "#000",
                  overflow: "hidden",
                }}
                onClick={handleStageClick}
              >
                {isLoading ? (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-cyan-500"></div>
                  </div>
                ) : (
                  <>
                    {renderVideo()}
                    {renderImages()}
                    {activeStory.elements &&
                      activeStory.elements
                        .filter((el) => !["image", "video"].includes(el.type))
                        .map(renderOverlay)}
                  </>
                )}
              </div>
            </div>
            
            {/* ADJACENT STORY PREVIEW - only shown on mobile during swipe */}
            {swipeDistance !== 0 && (
    <div 
      style={{
        position: "absolute",
        top: 0,
        [swipeDistance > 0 ? 'right' : 'left']: `-${stageSize.width}px`, // Position off-screen
        width: stageSize.width,
        height: stageSize.height,
        transform: `translateX(${swipeDistance > 0 
          ? Math.min(Math.abs(swipeDistance), window.innerWidth) 
          : -Math.min(Math.abs(swipeDistance), window.innerWidth)}px)`,
        background: swipeDistance > 0 
          ? (adjacentUsers.right?.stories?.[0]?.bgcolor || "#0a0a0a") 
          : (adjacentUsers.left?.stories?.[0]?.bgcolor || "#0a0a0a"),
      }}
      className="[aspect-ratio:9/16] max-h-[700px] max-w-[380px] max-md:mx-2"
    >
      {/* Progress bars preview */}
      <div className="absolute top-0 left-0 right-0 flex gap-1 z-10">
        {(swipeDistance > 0 ? adjacentUsers.right?.stories : adjacentUsers.left?.stories)?.map((_, idx) => (
          <div key={idx} className="flex-1 bg-gray-300 h-[3px] rounded">
            <div className="h-full bg-gray-500 rounded" style={{width: '0%'}} />
          </div>
        )) || <div className="flex-1 bg-gray-300 h-[3px] rounded"></div>}
      </div>
      
      {/* User info bar */}
      <div className="absolute top-2 left-1 w-full flex items-center p-2 z-10">
        <img
          src={
            (swipeDistance > 0 ? adjacentUsers.right?.profilePicture : adjacentUsers.left?.profilePicture)
              ? `${cloud}/cloudofscubiee/profilePic/${swipeDistance > 0 ? adjacentUsers.right?.profilePicture : adjacentUsers.left?.profilePicture}`
              : "/logos/DefaultPicture.png"
          }
          alt="Preview"
          className="w-9 h-9 rounded-full bg-gray-300 object-cover"
        />
        <span className="ml-4 text-white font-semibold">
          {swipeDistance > 0 ? adjacentUsers.right?.username : adjacentUsers.left?.username}
        </span>
      </div>
    </div>
  )}
</div>
    
          {/* Navigation buttons - positioned outside animation container */}
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: "-60px",
              transform: "translateY(-50%)",
              cursor: "pointer",
              fontSize: "24px",
              color: "#fff",
              background: "rgba(0,0,0,0.3)",
              borderRadius: "50%",
              padding: "10px",
              zIndex: 1100,
            }}
            onClick={async () => {
              const success = await handlePrevUser();
              console.log(`Previous user navigation ${success ? 'succeeded' : 'failed'}`);
            }}
            className="max-md:hidden hover:bg-black/50"
          >
            <FaChevronLeft />
          </div>
          <div
            style={{
              position: "absolute",
              top: "50%",
              right: "-60px",
              transform: "translateY(-50%)",
              cursor: "pointer",
              fontSize: "24px",
              color: "#fff",
              background: "rgba(0,0,0,0.3)",
              borderRadius: "50%",
              padding: "10px",
              zIndex: 1100,
            }}
            onClick={async () => {
              const success = await handleNextUser();
              console.log(`Next user navigation ${success ? 'succeeded' : 'failed'}`);
            }}
            className="max-md:hidden hover:bg-black/50"
          >
            <FaChevronRight />
          </div>
    
          {/* Side story previews for large screens */}
          {screenWidth > 768 && (
            <>
              <div
                className="absolute top-1/2 -translate-y-1/2 flex flex-row gap-[50px] opacity-85 z-[900]"
                style={{ left: leftStories.length === 1 ? "-180px" : "-380px" }}
              >
                {leftStories.map((userStory, index) => (
                  <div
                    key={`left_${index}`}
                    className="flex flex-col items-center cursor-pointer"
                    onClick={async () => {
                      const userIndex = stories.findIndex((s) => s.userId === userStory.userId);
                      
                      // Check if we need to fetch story details
                      if (userStory.stories.length === 0) {
                        try {
                          setIsLoading(true);
                          const response = await axios.get(`${api}/post/user-stories/${userStory.userId}`, {
                            withCredentials: true,
                            headers: { accessToken: localStorage.getItem("accessToken") }
                          });
                          
                          if (response.data && response.data.stories) {
                            const updatedStories = [...stories];
                            updatedStories[userIndex] = {
                              ...updatedStories[userIndex],
                              stories: response.data.stories
                            };
                            
                            if (typeof onStoriesUpdate === "function") {
                              onStoriesUpdate(updatedStories);
                            }
                          }
                        } catch (error) {
                          console.error("Error fetching story details:", error);
                          return;
                        } finally {
                          setIsLoading(false);
                        }
                      }
                      
                      setCurrentUserIndex(userIndex);
                      setCurrentStoryIndex(0);
                    }}
                  >
                    <img
                      src={
                        userStory.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${userStory.profilePicture}`
                          : "/logos/DefaultPicture.png"
                      }
                      alt={userStory.username}
                      className={`w-[80px] bg-gray-300 h-[80px] rounded-full border-4 ${
                        userStory.stories.every(story => story.viewed) ? "border-gray-500" : "border-cyan-600"
                      } object-cover`}
                    />
                    <span className="text-white mt-2 text-sm">{userStory.username}</span>
                  </div>
                ))}
              </div>
    
              <div
                className="absolute top-1/2 -translate-y-1/2 flex flex-row gap-[50px] opacity-85 z-[900]"
                style={{ right: rightStories.length === 1 ? "-180px" : "-360px" }}
              >
                {rightStories.map((userStory, index) => (
                  <div
                    key={`right_${index}`}
                    className="flex flex-col items-center cursor-pointer"
                    onClick={async () => {
                      const userIndex = stories.findIndex((s) => s.userId === userStory.userId);
                      
                      if (userStory.stories.length === 0) {
                        try {
                          setIsLoading(true);
                          const response = await axios.get(`${api}/post/user-stories/${userStory.userId}`, {
                            withCredentials: true,
                            headers: { accessToken: localStorage.getItem("accessToken") }
                          });
                          
                          if (response.data && response.data.stories) {
                            const updatedStories = [...stories];
                            updatedStories[userIndex] = {
                              ...updatedStories[userIndex],
                              stories: response.data.stories
                            };
                            
                            if (typeof onStoriesUpdate === "function") {
                              onStoriesUpdate(updatedStories);
                            }
                          }
                        } catch (error) {
                          console.error("Error fetching story details:", error);
                          return;
                        } finally {
                          setIsLoading(false);
                        }
                      }
                      
                      setCurrentUserIndex(userIndex);
                      setCurrentStoryIndex(0);
                    }}
                  >
                    <img
                      src={
                        userStory.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${userStory.profilePicture}`
                          : "/logos/DefaultPicture.png"
                      }
                      alt={userStory.username}
                      className={`w-[80px] bg-gray-300 h-[80px] rounded-full border-4 ${
                        userStory.stories.every(story => story.viewed) ? "border-gray-500" : "border-cyan-600"
                      } object-cover`}
                    />
                    <span className="text-white mt-2 text-sm">{userStory.username}</span>
                  </div>
                ))}
              </div>
            </>
          )}
    
          {/* Views/likes display */}
          {activeStory && (
            <div
              onClick={loggedInUser && currentUser.userId.trim() === loggedInUser.trim() ? handleShowViewers : null}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "4px",
                position: "absolute",
                bottom: "5px",
                left: "13px",
                color: "#fff",
                fontSize: "14px",
                fontFamily: "roboto",
                fontWeight: 600,
                zIndex: 1100,
                cursor: loggedInUser && currentUser.userId.trim() === loggedInUser.trim() ? "pointer" : "default",
              }}
            >
              {loggedInUser && currentUser.userId.trim() === loggedInUser.trim() ? (
                <div className="bg-black/20 p-1 rounded-lg flex items-center">
                  <span className="text-md">{activeStory.viewsCount}</span>
                  <IoEyeSharp className="ml-1 h-[20px] w-[20px]" />
                </div>
              ) : (
                <div 
                  className={`bg-black/10 p-1 rounded-full relative cursor-pointer transition-transform duration-300 ${heartClicked ? 'scale-125' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setHeartClicked(true);
                    setTimeout(() => setHeartClicked(false), 300);
                    handleStoryLike(e);
                  }}
                >
                  <Heart 
                    className={`max-380:ml-4 ${!activeStory.isLiked ? 'stroke-[1.6px] stroke-white drop-shadow-2xl shadow-black' : 'stroke-none'}`} 
                    fill={activeStory.isLiked ? "red" : "none"} 
                    color="red" 
                    size={26} 
                  />
                </div>
              )}
            </div>
          )}
    
          {/* Close button */}
          <button
            className="fixed max-500:hidden top-4 right-4 z-[1200] rounded-full bg-black/40 p-1 hover:bg-black/60 transition-colors"
            onClick={() => {
              if (localStoriesRef.current && typeof onStoriesUpdate === "function") {
                onStoriesUpdate(localStoriesRef.current);
              }
              onClose(viewedStoryIds);
            }}
          >
            <IoMdClose className="text-white text-[35px]" />
          </button>
    
          {/* Viewers modal */}
          {showViewersModal && (
            <div
              ref={viewersModalRef}
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                width: "360px",
                height: "400px",
                zIndex: 1200,
                boxShadow: "0 4px 8px rgba(0,0,0,0.2)",
                overflowY: "auto",
                borderRadius: "16px",
                padding: "16px",
              }}
              className="bg-[#0f0f0f] border-[1px] border-gray-700 font-sans"
            >
              {/* Modal content */}
              <div className="flex justify-between items-center mb-3">
                <div className="font-bold text-base text-white">Viewed By</div>
                <IoMdClose
                  className="text-white text-xl cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowViewersModal(false);
                  }}
                />
              </div>
              
              {viewers.length ? (
                viewers.map((viewer, idx) => (
                  <div
                    key={idx}
                    className="flex items-center mb-2"
                  >
                    <img
                      src={
                        viewer.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${viewer.profilePicture}`
                          : "/logos/DefaultPicture.png"
                      }
                      alt={viewer.username}
                      className="w-10 h-10 rounded-full object-cover mr-2 bg-gray-300"
                    />
                    <span className="text-white">{viewer.username}</span>
                  </div>
                ))
              ) : (
                <div className="text-white">No views yet</div>
              )}
            </div>
          )}
        </div>
      </div>
    );
};

export default DisplayStory;