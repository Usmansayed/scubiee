import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import axios from 'axios'; // Add this missing import
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import { MdOutlineContentCopy, MdOutlineReport, MdOutlineDeleteOutline, MdPersonAddDisabled, MdVolumeOff, MdVolumeUp } from "react-icons/md";
import { RiVerifiedBadgeFill, RiUserUnfollowLine, RiDeleteBin6Line } from 'react-icons/ri';
import { IoCloseSharp, IoNewspaperOutline } from "react-icons/io5";
import { FiBell ,FiSearch } from 'react-icons/fi';
import { HiOutlineUserGroup } from "react-icons/hi";
import { toast } from 'react-toastify';
import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
import CommentWidget from "../components/CommentWidget";
import ShareDialog from "../components/shareWidget";
import ReportWidget from "../components/ReportWidget";
import SuggestedUsers from "../components/SuggestedUsers";
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import ShortMediaCarousel from '../components/ShortMediaCarousel';
import { createPortal } from 'react-dom';

import {
  fetchFeedPosts,
  loadMorePosts,
  toggleLikePost,
  toggleSavePost,
  deletePost,
  toggleExpandText,
  setShortMediaIndex,
  setVideoPlaying,
  setOnlineStatus,
  removeUnfollowedUserPosts
} from '../Slices/HomeSlice';
import useScrollPreservation from '../hooks/useScrollPreservation';
const ScubieeLogo = "/logos/scubiee.svg"; // Path to Google SVG
const cloud = import.meta.env.VITE_CLOUD_URL;

const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted ? createPortal(children, document.body) : null;
};
const api = import.meta.env.VITE_API_URL;

// Custom hook to measure text height and determine if it needs truncation
const useSmartTruncate = () => {
  const textRef = useRef(null);
  const [needsTruncate, setNeedsTruncate] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isCalculated, setIsCalculated] = useState(false);

  // Function to calculate if text needs truncation
  const calculateTruncation = useCallback(() => {
    if (!textRef.current) return;

    // Reset styles to measure full height
    textRef.current.style.webkitLineClamp = 'unset';
    textRef.current.style.maxHeight = 'unset';
    
    // Get element's line height
    const lineHeight = parseInt(window.getComputedStyle(textRef.current).lineHeight) || 20;
    
    // Calculate number of lines
    const height = textRef.current.scrollHeight;
    const lines = Math.round(height / lineHeight);
    
    // Determine if truncation is needed (more than 6 lines)
    const shouldTruncate = lines > 6;
    
    // If it needs truncation, apply it
    if (shouldTruncate && !isExpanded) {
      textRef.current.style.webkitLineClamp = '4';
      textRef.current.style.display = '-webkit-box';
      textRef.current.style.webkitBoxOrient = 'vertical';
      textRef.current.style.overflow = 'hidden';
    }
    
    setNeedsTruncate(shouldTruncate);
    setIsCalculated(true);
  }, [isExpanded]);

  // Toggle expanded state
  const toggleExpand = () => {
    setIsExpanded(!isExpanded);
  };

  return {
    textRef,
    needsTruncate,
    isExpanded,
    calculateTruncation,
    toggleExpand,
    isCalculated
  };
};

// Smart Truncate Text component
const SmartTruncateText = ({ text, className = '' }) => {
  const { 
    textRef, 
    needsTruncate, 
    isExpanded, 
    calculateTruncation, 
    toggleExpand,
    isCalculated
  } = useSmartTruncate();

  // Calculate truncation on mount and window resize
  useEffect(() => {
    calculateTruncation();
    
    // Recalculate on window resize
    const handleResize = () => {
      calculateTruncation();
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [calculateTruncation]);

  return (
    <>
      <p
        ref={textRef}
        className={`${className} ${isExpanded ? 'whitespace-pre-line' : ''} ${isExpanded ? '' : needsTruncate ? 'truncated-text' : ''}`}
        style={{
          transition: 'max-height 0.3s ease-out'
        }}
      >
        {text}
      </p>
      
      {needsTruncate && isCalculated && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            toggleExpand();
          }}
          className="text-[15px] text-blue-500 hover:text-blue-400 mt-1 font-medium transition-opacity"
        >
          {isExpanded ? 'Show Less' : 'Show More'}
        </button>
      )}
    </>
  );
};

// Custom hook to detect the most visible video in viewport
const useVideoAutoplay = (dependencies = []) => {
  const [mostVisibleVideo, setMostVisibleVideo] = useState(null);
  const videoRefs = useRef({});
  const observers = useRef({});
  const visibilityRatios = useRef({});
  const userInteracted = useRef({});
  const manuallyPaused = useRef({}); // Track videos that were manually paused
  const firstClickHandled = useRef({}); // Track videos that have had their first click

  // Register a video element to be tracked
  const registerVideo = useCallback((id, element) => {
    if (!element) return;
    
    videoRefs.current[id] = element;
    
    // Set up observer for this video
    if (observers.current[id]) {
      observers.current[id].disconnect();
    }
    
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          // Store the current visibility ratio
          visibilityRatios.current[id] = entry.intersectionRatio;
          
          // If video is no longer visible enough, pause it immediately
          if (entry.intersectionRatio < 0.5 && mostVisibleVideo === id) {
            setMostVisibleVideo(null); // This will trigger the effect to pause it
          }
          
          // Only proceed to find most visible if this video is visible enough
          if (entry.intersectionRatio >= 0.5) {
            // Find the most visible video (highest intersection ratio)
            let maxRatio = 0;
            let maxId = null;
            
            Object.keys(visibilityRatios.current).forEach(videoId => {
              if (visibilityRatios.current[videoId] > maxRatio) {
                maxRatio = visibilityRatios.current[videoId];
                maxId = videoId;
              }
            });
            
            // Update the most visible video if it's visible enough
            if (maxId && maxRatio > 0.5) {
              setMostVisibleVideo(maxId);
            }
          }
        });
      },
      {
        threshold: [0, 0.25, 0.5, 0.75, 1.0], // Multiple thresholds for better precision
        root: null, // Use viewport as root
      }
    );
    
    observer.observe(element);
    observers.current[id] = observer;
  }, [mostVisibleVideo]);
  
  // Handle user interaction (mute/unmute) for a video
  const handleUserInteraction = useCallback((id) => {
    userInteracted.current[id] = true;
  }, []);
  
  // Add function to mark a video as manually paused
  const setManuallyPaused = useCallback((id, isPaused) => {
    manuallyPaused.current[id] = isPaused;
  }, []);
  
  // Check if a video was manually paused by the user
  const isManuallyPaused = useCallback((id) => {
    return manuallyPaused.current[id] || false;
  }, []);
  
  // Check if a user has interacted with a video
  const hasUserInteracted = useCallback((id) => {
    return userInteracted.current[id] || false;
  }, []);
  
  // Add function to check/set if first click has been handled
  const isFirstClickHandled = useCallback((id) => {
    return firstClickHandled.current[id] || false;
  }, []);
  
  const setFirstClickHandled = useCallback((id, handled) => {
    firstClickHandled.current[id] = handled;
  }, []);
  
  // Clean up observers when component unmounts
  useEffect(() => {
    return () => {
      Object.values(observers.current).forEach(observer => {
        if (observer) observer.disconnect();
      });
    };
  }, dependencies);
  
  return { 
    mostVisibleVideo, 
    registerVideo, 
    handleUserInteraction, 
    hasUserInteracted,
    videoRefs,
    setManuallyPaused,
    isManuallyPaused,
    isFirstClickHandled,
    setFirstClickHandled
  };
}

// Custom hook to track horizontal scroll index
function useHorizontalScrollIndex(imageCount) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const containerRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const children = Array.from(container.children);
      let minDiff = Infinity;
      let idx = 0;
      children.forEach((child, i) => {
        const diff = Math.abs(child.getBoundingClientRect().left - container.getBoundingClientRect().left);
        if (diff < minDiff) {
          minDiff = diff;
          idx = i;
        }
      });
      setCurrentIndex(idx);
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [imageCount]);

  // Reset index if imageCount changes
  useEffect(() => {
    setCurrentIndex(0);
  }, [imageCount]);

  return [containerRef, currentIndex];
}

// Updated component for horizontal scrolling of all media (images and videos)
const HorizontalImageScroll = ({ imageFiles, post, handleImageClick, cloud, registerVideo, handleVideoClick, videoOverlays }) => {
  const [scrollRef, scrollIndex] = useHorizontalScrollIndex(imageFiles.length);
  const isLargeScreen = window.innerWidth >= 768;

  // Handle video click specifically for grid items to prevent event bubbling issues
  const handleVideoClickInGrid = (e, postId, videoUrl) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Call the main video click handler with the right parameters
    handleVideoClick(e, postId, videoUrl);
  };

  return (
    <div className="relative mb-4">
      <div
        ref={scrollRef}
        className="flex overflow-x-auto snap-x snap-mandatory scrollbar-hide w-[100%] mx-auto py-2 space-x-0"
      >
        {imageFiles.map((media, i) => (
          <div 
            key={`media-${i}`} 
            className="flex-shrink-0 snap-start snap-always w-[100%] first:pl-0"
          >            <div className="[aspect-ratio:1/1] w-full">              {media.type === 'video' ? (
                <div 
                  className="max-md:w-[93%] max-md:mx-auto max-md:rounded-lg w-full h-full video-container bg-black md:rounded-lg cursor-pointer overflow-hidden relative" 
                  data-video-id={`${post.id}-${media.url}`}
                  onClick={(e) => handleVideoClickInGrid(e, post.id, media.url)}
                >
                  <video 
                    ref={(el) => el && registerVideo(`${post.id}-${media.url}`, el)}
                    src={`${cloud}/cloudofscubiee/${media.type === 'video' ? 'postVideos' : 'postImages'}/${media.url}`}
                    className="w-full h-full object-contain max-h-[550px]" 
                    muted
                    loop
                    playsInline
                    preload="metadata"
                  />
                  
                  {/* Play/Pause Icon Overlay - Show play icon when paused, pause icon when playing */}
                  {videoOverlays[`${post.id}-${media.url}`] === 'play' && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/20 animate-fadeOut">
                      <div className="rounded-full bg-black/50 p-3">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 scale-110 text-white" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M8 5v14l11-7z"/>
                        </svg>
                      </div>
                    </div>
                  )}
                  
                  {videoOverlays[`${post.id}-${media.url}`] === 'pause' && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                      <div className="rounded-full bg-black/50 p-3">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 scale-110 text-white" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
                        </svg>
                      </div>
                    </div>
                  )}
                </div>              ) : (
                <img 
                  src={`${cloud}/cloudofscubiee/postImages/${media.url}`}
                  alt={`Media ${i}`} 
                  loading="lazy"
                  className="max-md:w-[93%] max-md:mx-auto max-md:rounded-lg w-[94%] mx-auto rounded-lg h-full object-cover cursor-pointer"
                  onClick={(e) => handleImageClick(e, media, post, post.media.indexOf(media))}
                />
              )}
            </div>
          </div>
        ))}
      </div>
      
      {/* Media count indicator */}
      <div className="absolute bottom-4 right-4 bg-black/60 px-2 py-1 rounded-full text-xs text-white">
        {imageFiles.length > 1 && (
          <span>{`${scrollIndex + 1}/${imageFiles.length}`}</span>
        )}
      </div>
      
      {/* Navigation arrows for larger screens */}
      {isLargeScreen && imageFiles.length > 1 && (
        <>
          <button 
            className="absolute left-2 top-1/2 transform -translate-y-1/2 bg-black/60 p-2 rounded-full z-10 hover:bg-black/80 transition-all"
            onClick={(e) => {
              e.stopPropagation();
              const container = scrollRef.current;
              if (container) {
                const currentScroll = container.scrollLeft;
                const itemWidth = container.clientWidth;
                container.scrollTo({
                  left: currentScroll - itemWidth,
                  behavior: 'smooth'
                });
              }
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button 
            className="absolute right-2 top-1/2 transform -translate-y-1/2 bg-black/60 p-2 rounded-full z-10 hover:bg-black/80 transition-all"
            onClick={(e) => {
              e.stopPropagation();
              const container = scrollRef.current;
              if (container) {
                const currentScroll = container.scrollLeft;
                const itemWidth = container.clientWidth;
                container.scrollTo({
                  left: currentScroll + itemWidth,
                  behavior: 'smooth'
                });
              }
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </>
      )}
    </div>
  );
};

const Home = () => {
  // Navbar scroll state
  const [isNavbarVisible, setIsNavbarVisible] = useState(true);
  const [lastScrollY, setLastScrollY] = useState(0);
  const scrollThreshold = 10; // Minimum scroll distance to trigger navbar hide/show

  const navigate = useNavigate();
  const dispatch = useDispatch();
  const userData = useSelector((state) => state.user.userData);
  const isLoggedIn = !!userData;
  
  // Add state for content readiness
  const [contentReady, setContentReady] = useState(false);
  
  // Add a ref to track if we're currently loading more posts
  const loadingMoreRef = useRef(false);
  
  // Safety check - redirect if not authenticated
  useEffect(() => {
    if (!isLoggedIn) {
      console.log("User not authenticated, redirecting to sign-in");
      navigate('/sign-in', { replace: true });
      return;
    }
    
    // Mark content as ready immediately after initial render
    // No artificial delay needed since scroll restoration now happens immediately
    setContentReady(true);
  }, [isLoggedIn, navigate]);

  useEffect(() => {
    setGlobalMuted(false);
  }, []);
  
  // Use the scroll preservation hook
  // Redux state
  const {
    posts,
    likedPosts,
    savedPosts,
    expandedTexts,
    shortMediaIndexes,
    playingVideos,
    loading,
    loadingMore,
    error,
    pagination,
    isOnline
  } = useSelector(state => state.home);
    const { 
    cleanup: cleanupScroll, 
    manualRestoreScroll, 
    savedPosition,
    scrollRestorationCompleted 
  } = useScrollPreservation({
    posts,
    loading,
    loadingMore,
    isContentReady: contentReady
  });
    // Cleanup scroll preservation when component unmounts
  useEffect(() => {
    return () => {
      cleanupScroll();
    };
  }, [cleanupScroll]);

  // Fallback scroll restoration effect - triggers manual restoration if automatic didn't work
  useEffect(() => {
    if (contentReady && !loading && posts.length > 0 && savedPosition > 50 && !scrollRestorationCompleted) {
      console.log('Fallback: Manually triggering scroll restoration after 2 seconds');
      const fallbackTimer = setTimeout(() => {
        if (!scrollRestorationCompleted && savedPosition > 50) {
          console.log('Executing fallback scroll restoration');
          manualRestoreScroll();
        }
      }, 2000); // Wait 2 seconds before fallback

      return () => clearTimeout(fallbackTimer);
    }
  }, [contentReady, loading, posts.length, savedPosition, scrollRestorationCompleted, manualRestoreScroll]);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [showCopyNotification, setShowCopyNotification] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  
  // Replace local unreadNotifications state with Redux state
  const { unreadCount: unreadNotifications } = useSelector(state => state.notification);
  // Remove notificationsLoaded state since we'll rely on Redux loading state
  const notificationsLoaded = useSelector(state => !state.notification.loading || state.notification.lastFetched !== null);
  useEffect(() => {
    const handleOnline = () => {
      dispatch(setOnlineStatus(true));
      toast.success("You're back online!");
    };
    
    const handleOffline = () => {
      dispatch(setOnlineStatus(false));
    };
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  const toggleOptions = () => {
    setShowOptions(!showOptions);
  };
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);

  // Local state for UI controls
  const [showOptions, setShowOptions] = useState(false);
  const [commentPostId, setCommentPostId] = useState(null);
  const [sharePostId, setSharePostId] = useState(null);
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportType, setReportType] = useState(null);
  const [reportTargetId, setReportTargetId] = useState(null);
  const [activeMenu, setActiveMenu] = useState(null);
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);
  const [deleteConfirmation, setDeleteConfirmation] = useState({
    isOpen: false,
    postId: null,
    postTitle: ''
  });
    // Refs
  const observerRef = useRef(null);
  const menuRef = useRef(null);
  const pageRef = useRef(null);
  const reportWidgetRef = useRef(null);
  
  // Debounce refs
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map()); // Add ref for save operations
  const intersectionDebounceRef = useRef(null); // Add debounce for intersection observer
  const visualState = useRef({
    likedPosts: {},  // Track visual state separate from Redux
    savedPosts: {}   // Track visual state separate from Redux
  });
  const visualLikeState = useRef({}); // Track visual like state per post
  
  // Fetch initial posts - modified to check if we already have posts
  useEffect(() => {
    if (posts.length === 0) {
      console.log("No posts in Redux store, fetching initial posts...");
      dispatch(fetchFeedPosts(1));
    } else {
      console.log("Using existing posts from Redux store");
    }
  }, [dispatch, posts.length]);
    // Clean up pending operations on unmount
  useEffect(() => {
    return () => {
      // Clear all pending like operations
      pendingLikeOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingLikeOperations.current.clear();
      
      // Clear all pending save operations
      pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingSaveOperations.current.clear();
      
      // Clear intersection observer debounce
      intersectionDebounceRef.current = false;
      
      // Clear scroll preservation pause flag
      if (window.scrollPreservationPaused !== undefined) {
        window.scrollPreservationPaused = false;
      }
    };
  }, []);  // Optimized observer for infinite scrolling that prevents scroll jumps
  const lastPostRef = useCallback(node => {
    if (loading || loadingMore) return;
    
    if (observerRef.current) {
      observerRef.current.disconnect();
    }
    
    observerRef.current = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && pagination.hasMore) {
        // Prevent infinite scroll when offline
        if (!isOnline) {
          console.log("User is offline, preventing infinite scroll load");
          toast.warning("You're offline. New posts will load when you're back online.");
          return;
        }
        
        // Prevent multiple rapid fire requests with debouncing
        if (loadingMoreRef.current) {
          console.log("Already loading more posts, ignoring intersection");
          return;
        }
        
        // Add debounce to prevent rapid triggering during fast scrolling
        if (intersectionDebounceRef.current) {
          console.log("Intersection observer debounced, ignoring rapid trigger");
          return;
        }
        
        console.log("Reached bottom of posts, loading more...");
        
        // Set debounce flag
        intersectionDebounceRef.current = true;
        setTimeout(() => {
          intersectionDebounceRef.current = false;
        }, 1000); // 1 second debounce
          // Store scroll anchor element before loading new content
        const viewportCenter = window.innerWidth / 2;
        const viewportMiddle = window.innerHeight / 2;
        let scrollAnchor = document.elementFromPoint(viewportCenter, viewportMiddle);
        
        // If we can't find an element at the center, try finding a post element
        if (!scrollAnchor || !scrollAnchor.closest('article')) {
          const articles = document.querySelectorAll('article');
          const viewportTop = window.scrollY;
          const viewportBottom = viewportTop + window.innerHeight;
          
          // Find the article that's most centered in the viewport
          for (let article of articles) {
            const rect = article.getBoundingClientRect();
            const articleTop = rect.top + viewportTop;
            const articleBottom = articleTop + rect.height;
            
            if (articleTop < viewportBottom && articleBottom > viewportTop) {
              scrollAnchor = article;
              break;
            }
          }
        }
        
        const scrollAnchorRect = scrollAnchor ? scrollAnchor.getBoundingClientRect() : null;
        const scrollAnchorDistanceFromTop = scrollAnchorRect ? scrollAnchorRect.top : 0;
        
        // Set the loading more flag BEFORE dispatching the action
        loadingMoreRef.current = true;
        
        // Temporarily disable scroll position saving during load more
        if (window.scrollPreservationPaused !== undefined) {
          window.scrollPreservationPaused = true;
        }
        
        // Dispatch loadMorePosts action with improved position preservation
        dispatch(loadMorePosts())
          .then(() => {
            // Use multiple animation frames to ensure DOM updates are complete
            requestAnimationFrame(() => {
              requestAnimationFrame(() => {
                requestAnimationFrame(() => {                  // Restore scroll position relative to the anchor element
                  if (scrollAnchor && scrollAnchor.isConnected) {
                    try {
                      const newScrollAnchorRect = scrollAnchor.getBoundingClientRect();
                      const newScrollAnchorDistanceFromTop = newScrollAnchorRect.top;
                      const scrollDifference = newScrollAnchorDistanceFromTop - scrollAnchorDistanceFromTop;
                      
                      // Be more conservative with scroll adjustments - only adjust for significant, reasonable changes
                      if (Math.abs(scrollDifference) > 10 && Math.abs(scrollDifference) < window.innerHeight * 0.5) {
                        window.scrollBy({
                          top: scrollDifference,
                          behavior: 'instant'
                        });
                        console.log('Scroll adjusted by:', scrollDifference);
                      } else if (Math.abs(scrollDifference) > 10) {
                        console.log('Scroll difference too large, skipping adjustment:', scrollDifference);
                      }
                    } catch (error) {
                      console.warn('Failed to adjust scroll position:', error);
                    }
                  } else {
                    console.log('Scroll anchor not found or disconnected, skipping adjustment');
                  }
                });
              });
            });
          })          .finally(() => {
            // Reset the loading flag and re-enable scroll saving after content is settled
            setTimeout(() => {
              loadingMoreRef.current = false;
              // Don't re-enable scroll preservation here - let the hook handle it
              // if (window.scrollPreservationPaused !== undefined) {
              //   window.scrollPreservationPaused = false;
              // }
            }, 500); // Longer delay to ensure all animations complete
          });
      }
    }, {
      root: null,
      rootMargin: '200px', // Increased margin for better UX
      threshold: 0.1
    });
    
    if (node) {
      observerRef.current.observe(node);
    }
  }, [loading, loadingMore, pagination.hasMore, dispatch, isOnline]);
  // Handle like toggle with debouncing
  const handleLikeToggle = (postId, e) => {
    if (e) e.stopPropagation();
  
    // Early return if offline
    if (!isOnline) {
      toast.warning("You're offline. Please try again when connected.");
      return;
    }
  
    // Visual feedback animation
    if (e && e.currentTarget) {
      try {
        requestAnimationFrame(() => {
          if (e.currentTarget) {
            e.currentTarget.classList.add('scale-90');
            setTimeout(() => {
              if (e.currentTarget) {
                e.currentTarget.classList.remove('scale-90');
              }
            }, 150);
          }
        });
      } catch (err) {
        console.log("Animation feedback error:", err);
        // Continue with the like operation even if the animation fails
      }
    }
  
    const postIdStr = postId.toString();
    
    // 1. Remember the ORIGINAL backend state (from Redux)
    const originalBackendState = likedPosts[postId] || false;
    const post = posts.find(p => p.id === postId);
    const originalCount = post?.likes || 0;
    
    // 2. TOGGLE the local visual state
    const hasVisualState = postIdStr in visualState.current.likedPosts;
    const currentVisualState = hasVisualState 
      ? visualState.current.likedPosts[postIdStr] 
      : originalBackendState;
    
    const newVisualState = !currentVisualState;
    visualState.current.likedPosts[postIdStr] = newVisualState;
      // If this is a like action (not unlike), show a simple upvote animation
    if (newVisualState) {
      try {
        // Add upvote success animation to the button itself
        if (e && e.currentTarget) {
          const button = e.currentTarget;
          button.classList.add('upvote-success');
          
          // Remove the animation class after it completes
          setTimeout(() => {
            button.classList.remove('upvote-success');
          }, 600);
        }
      } catch (error) {
        // Fail silently - animation is non-critical
        console.log("Animation error:", error);
      }
    }
    
    // 3. Calculate VISUAL delta from ORIGINAL backend state
    const visualDelta = newVisualState !== originalBackendState 
      ? (newVisualState ? 1 : -1) 
      : 0;
    
    // 4. Update UI based on final INTENDED state
    const likeButtons = document.querySelectorAll(`[data-like-button="${postId}"]`);
    likeButtons.forEach(button => {
      // Update icon
      const emptyHeart = button.querySelector('.empty-heart');
      const filledHeart = button.querySelector('.filled-heart');
      
      if (emptyHeart && filledHeart) {
        emptyHeart.style.display = newVisualState ? 'none' : 'block';
        filledHeart.style.display = newVisualState ? 'block' : 'none';
      }
      
      // Update count based on ORIGINAL count + visual delta
      const countSpan = button.querySelector('span');
      if (countSpan) {
        countSpan.textContent = Math.max(0, originalCount + visualDelta).toString();
      }
    });
    
    // 5. Debounce the actual API call
    if (pendingLikeOperations.current.has(postIdStr)) {
      clearTimeout(pendingLikeOperations.current.get(postIdStr));
    }
    
    const timerId = setTimeout(() => {
      // Only make the API call if the final visual state differs from original backend state
      if (visualState.current.likedPosts[postIdStr] !== originalBackendState) {
        dispatch(toggleLikePost({
          postId,
          finalState: visualState.current.likedPosts[postIdStr],
          action: visualState.current.likedPosts[postIdStr] ? 'like' : 'unlike'
        }))
          .unwrap()
          .catch(error => {
            console.error('Error updating like status:', error);
            // Revert visual state on error
            visualState.current.likedPosts[postIdStr] = originalBackendState;
            
            // Also revert the visual UI on error
            likeButtons.forEach(button => {
              const emptyHeart = button.querySelector('.empty-heart');
              const filledHeart = button.querySelector('.filled-heart');
              
              if (emptyHeart && filledHeart) {
                emptyHeart.style.display = originalBackendState ? 'none' : 'block';
                filledHeart.style.display = originalBackendState ? 'block' : 'none';
              }
              
              // Also revert the count
              const countSpan = button.querySelector('span');
              if (countSpan) {
                countSpan.textContent = originalCount.toString();
              }
            });
          })
          .finally(() => {
            pendingLikeOperations.current.delete(postIdStr);
          });
      } else {
        pendingLikeOperations.current.delete(postIdStr);
      }
    }, 500);
    
    pendingLikeOperations.current.set(postIdStr, timerId);
  };

  // Handle comment click
  const handleCommentClick = (postId, e) => {
    if (e) e.stopPropagation();
    dispatch(setIsCommentOpen(true));
    setCommentPostId(postId);
  };

  // Add a handler for comment close that updates the comment count
  const handleCommentClose = (newCommentCount = 0) => {
    // If we have new comments and a commentPostId to update
    if (newCommentCount > 0 && commentPostId) {
      // Update the post in the posts array
      const updatedPosts = posts.map(post => 
        post.id === commentPostId 
          ? { ...post, comments: (post.comments || 0) + newCommentCount } 
          : post
      );
      
      // Update posts in Redux
      dispatch({
        type: 'home/updatePosts',
        payload: updatedPosts
      });
    }
    
    dispatch(setIsCommentOpen(false));
  };

  // Handle share post
  const handleSharePost = (postId, e) => {
    if (e) e.stopPropagation();
    setSharePostId(postId);
    setShowShareWidget(true);
  };

  // Fix the handleCopyLink function which is referenced but not implemented
  const handleCopyLink = (postId, e) => {
    e.stopPropagation();
    const postUrl = `${window.location.origin}/viewpost/${postId}`;
    
    navigator.clipboard.writeText(postUrl)
      .then(() => {
        // Show notification instead of or in addition to toast
        setShowCopyNotification(true);
        setTimeout(() => setShowCopyNotification(false), 2000);
        
        toast.success("Link copied to clipboard");
        setActiveMenu(null); // Close the menu after copying
      })
      .catch((err) => {
        console.error('Failed to copy text: ', err);
        toast.error("Failed to copy link");
      });
  };

  // Handle menu toggle
  const handleToggleMenu = (postId, e) => {
    e.stopPropagation();
    
    if (activeMenu === postId) {
      setActiveMenu(null);
      return;
    }
    
    // Get the position of the clicked button
    const buttonRect = e.currentTarget.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;
    
    // Calculate positions that ensure the menu stays within the viewport
    let topPosition, leftPosition;
    
    if (window.innerWidth < 768) {
      // Mobile: position to the left of the button
      topPosition = Math.min(buttonRect.top, viewportHeight - 250); // Keep menu in viewport
      leftPosition = Math.max(viewportWidth - 192, 0); // 192px is width of menu (w-48)
    } else {
      // Desktop: position near the button without adding scroll
      topPosition = Math.min(buttonRect.top, viewportHeight - 250); // Keep menu in viewport
      
      // Position to the left of the button, but ensure it stays within viewport
      leftPosition = Math.min(
        Math.max(buttonRect.right - 192, 0), // Don't go beyond left edge
        viewportWidth - 192 // Don't go beyond right edge
      );
    }
    
    // Set final position
    setMenuPosition({
      top: topPosition,
      left: leftPosition
    });
    
    setActiveMenu(postId);
  };
 // Handle save toggle with debouncing
 const handleSaveToggle = (postId, e) => {
  if (e) e.stopPropagation();
  
  // Early return if offline
  if (!isOnline) {
    toast.warning("You're offline. This action will be available when you're back online.");
    return;
  }
  
  // Visual feedback animation
  if (e && e.currentTarget) {
    requestAnimationFrame(() => {
      e.currentTarget.classList.add('scale-90');
      setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
    });
  }
  
  const postIdStr = postId.toString();
  
  // Remember the ORIGINAL backend state (from Redux)
  const originalBackendState = savedPosts[postId] || false;
  
  // TOGGLE the local visual state
  const hasVisualState = postIdStr in visualState.current.savedPosts;
  const currentVisualState = hasVisualState 
    ? visualState.current.savedPosts[postIdStr] 
    : originalBackendState;
  
  const newVisualState = !currentVisualState;
  visualState.current.savedPosts[postIdStr] = newVisualState;
  
  // Update UI immediately for better UX
  const saveButtons = document.querySelectorAll(`[data-save-button="${postId}"]`);
  saveButtons.forEach(button => {
    // Update icon
    const emptyBookmark = button.querySelector('.empty-bookmark');
    const filledBookmark = button.querySelector('.filled-bookmark');
    
    if (emptyBookmark && filledBookmark) {
      emptyBookmark.style.display = newVisualState ? 'none' : 'block';
      filledBookmark.style.display = newVisualState ? 'block' : 'none';
    }
  });
  
  // Debounce the API call
  if (pendingSaveOperations.current.has(postIdStr)) {
    clearTimeout(pendingSaveOperations.current.get(postIdStr));
  }
  
  const timerId = setTimeout(() => {
    // Only make the API call if the final visual state differs from backend state
    if (visualState.current.savedPosts[postIdStr] !== originalBackendState) {
      // Include explicit action parameter based on target state
      dispatch(toggleSavePost({
        postId, 
        finalState: visualState.current.savedPosts[postIdStr],
        action: visualState.current.savedPosts[postIdStr] ? 'save' : 'unsave'
      }));
    }
    pendingSaveOperations.current.delete(postIdStr);
  }, 500);
  
  pendingSaveOperations.current.set(postIdStr, timerId);
};
  // Replace your handleDeletePost function with this:
const handleDeletePost = (postId, e) => {
  e.stopPropagation();
  console.log("Delete post clicked", postId);
  
  if (!isOnline) {
    toast.warning("You're offline. Please try again when connected.");
    return;
  }
  
  // If it's user's own post, allow deletion
  const post = posts.find(p => p.id === postId);
  console.log("Post found:", post);
  console.log("Current user:", userData);
  
  if (!post) {
    console.log("Post not found");
    return;
  }
  
  // Check if user is the author - use Redux state instead of localStorage
  if (userData && userData.id === post.author.id) {
    console.log("User is author, opening confirmation");
    // Open the confirmation modal
    setDeleteConfirmation({
      isOpen: true,
      postId: postId,
      postTitle: post.title || post.content?.substring(0, 30) || 'this post'
    });
  } else {
    console.log("User is not author:", userData?.id, "vs", post.author.id);
    toast.error("You don't have permission to delete this post");
  }
  
  setActiveMenu(null);
};
  // Add functions to handle modal actions
  const confirmDelete = () => {
    console.log("Confirming delete for post:", deleteConfirmation.postId);
    // Show deleting UI
    setIsDeleting(true);
    
    // Call the delete API through Redux
    if (deleteConfirmation.postId) {
      dispatch(deletePost(deleteConfirmation.postId))
        .finally(() => {
          // Hide deleting UI after operation completes (success or error)
          setIsDeleting(false);
        });
    }
    // Close the modal
    setDeleteConfirmation({
      isOpen: false,
      postId: null,
      postTitle: ''
    });
  };
  
  const cancelDelete = () => {
    console.log("Canceling delete");
    // Just close the modal
    setDeleteConfirmation({
      isOpen: false,
      postId: null,
      postTitle: ''
    });
  };

  // Handle reporting a post
  const handleReportPost = (postId, e) => {
    e.stopPropagation();
    setReportType('post');
    setReportTargetId(postId);
    setShowReportWidget(true);
    setActiveMenu(null);
  };

  // Handle reporting a user
  const handleReportUser = (userId, e) => {
    e.stopPropagation();
    setReportType('user');
    setReportTargetId(userId);
    setShowReportWidget(true);
    setActiveMenu(null);
  };

  // Handle follow/unfollow
  const handleFollowToggle = async (post, e) => {
    e.stopPropagation();
    
    // Early return if offline
    if (!isOnline) {
      toast.warning("You're offline. Please try again when connected.");
      return;
    }
    
    const authorId = post.author.id;
    const authorUsername = post.author.username;
    
    try {
      // Check if we're following the user
      const isFollowing = post.author.followedByMe;
      
      if (isFollowing) {
        // Unfollow the user
        await axios.delete(`${api}/user/follow/${authorId}`, {
          withCredentials: true
        });
        
        // Remove all posts from the unfollowed user immediately
        dispatch(removeUnfollowedUserPosts(authorId));
        
        toast.success(`Unfollowed @${authorUsername}`);
      } else {
        // Follow the user
        await axios.post(`${api}/user/follow/${authorId}`, {}, {
          withCredentials: true
        });
        
        // For follows, refresh the feed to show their posts
        toast.success(`Following @${authorUsername}`);
        dispatch(fetchFeedPosts(1));
      }
      
    } catch (error) {
      console.error('Error toggling follow:', error);
      toast.error("Failed to update follow status");
    }
    
    setActiveMenu(null);
  };

  // Handle menu cancel
  const handleCancelMenu = (e) => {
    e.stopPropagation();
    setActiveMenu(null);
  };

  // Navigate to user profile
  const navigateToProfile = (username, e) => {
    e.stopPropagation();
    navigate(`/${username}`);
  };

  // Handle image click for viewing
  const handleImageClick = (e, media, post, index) => {
    e.stopPropagation();
    if (media && media.type !== 'video') {
      setViewingImage({
        ...media,
        postMedia: post.media
      });
      setImageIndex(index);
    }
  };

  // Close image viewer
  const closeImageViewer = () => {
    setViewingImage(null);
    setImageIndex(0);
  };

  // Add this new useEffect for handling scroll and history for image viewer
  useEffect(() => {
    if (viewingImage) {
      // Push a new history state when opening image viewer
      window.history.pushState({ action: 'viewImage' }, '');
      
      // Handle scroll events to close the viewer
      const handleScroll = () => {
        closeImageViewer();
      };
      
      // Handle back button clicks
      const handlePopState = () => {
        closeImageViewer();
      };
      
      // Add event listeners
      window.addEventListener('scroll', handleScroll);
      window.addEventListener('popstate', handlePopState);
      
      // Clean up
      return () => {
        window.removeEventListener('scroll', handleScroll);
        window.removeEventListener('popstate', handlePopState);
      };
    }
  }, [viewingImage]);

  // Navigate between images in viewer
  const navigateImages = (e, direction, mediaArray) => {
    e.stopPropagation();
    
    // Find all images in the media array (exclude videos)
    const imageMediaOnly = mediaArray.filter(media => media.type !== 'video');
    
    // If there are no images to navigate through, return
    if (imageMediaOnly.length <= 1) return;
    
    // Find the current index in the filtered images array
    const currentImageIndex = imageMediaOnly.findIndex(media => media.url === viewingImage.url);
    
    // Calculate the new index in the filtered array
    let newImageIndex = currentImageIndex + direction;
    
    // Handle looping
    if (newImageIndex < 0) newImageIndex = imageMediaOnly.length - 1;
    if (newImageIndex >= imageMediaOnly.length) newImageIndex = 0;
    
    // Set the new image - make sure we preserve the postMedia property
    const newImage = imageMediaOnly[newImageIndex];
    setImageIndex(mediaArray.indexOf(newImage));
    setViewingImage({
      ...newImage,
      postMedia: mediaArray // Keep the postMedia reference
    });
  };

  // Handle video play
  const { 
    mostVisibleVideo, 
    registerVideo, 
    handleUserInteraction, 
    hasUserInteracted, 
    videoRefs,
    setManuallyPaused,
    isManuallyPaused,
    isFirstClickHandled,
    setFirstClickHandled
  } = useVideoAutoplay([posts]);
  
  const videoStates = useRef({}); // Track video mute state
  
  // Add state to track if device is touch screen or small screen
  const [isTouchDevice, setIsTouchDevice] = useState(false);
  
  // Detect touch device or small screen on mount
  useEffect(() => {
    const checkTouchDevice = () => {
      setIsTouchDevice('ontouchstart' in window || 
                      navigator.maxTouchPoints > 0 ||
                      window.innerWidth < 1280);
    };
    
    checkTouchDevice();
    window.addEventListener('resize', checkTouchDevice);
    
    return () => window.removeEventListener('resize', checkTouchDevice);
  }, []);

  const globalUnmuteState = useRef(false);
  
  // Add a new state for global mute control
  const [globalMuted, setGlobalMuted] = useState(true);

  // Add state to track video overlay icons
  const [videoOverlays, setVideoOverlays] = useState({});
  
  // Updated video click handler for better functionality
  const handleVideoClick = (e, postId, videoUrl) => {
    e.preventDefault(); // Prevent default to avoid any conflicts
    e.stopPropagation();
    
    // Get the video key
    const videoKey = `${postId}-${videoUrl}`;
    
    // Record user interaction with this video
    handleUserInteraction(videoKey);

    // Improved video element selection with better debugging
    let videoElement = null;
    let container = null;
    
    // First try to find the container
    if (e.target.classList.contains('video-container')) {
      container = e.target;
    } else {
      container = e.target.closest('.video-container');
    }
    
    if (container) {
      videoElement = container.querySelector('video');
    } else if (e.target.tagName === 'VIDEO') {
      videoElement = e.target;
    }
    
    if (!videoElement) {
      console.error('Could not find video element:', e.target);
      return;
    }

    // Strictly allow only one video to play at a time
    const allVideos = document.querySelectorAll('video');
    allVideos.forEach(v => {
      if (v !== videoElement && !v.paused) {
        v.pause();
        const container = v.closest('.video-container');
        if (container && container.dataset.videoId) {
          const [pId, vUrl] = container.dataset.videoId.split('-');
          dispatch(setVideoPlaying({ postId: pId, videoUrl: vUrl, isPlaying: false }));
        }
      }
    });

    // Toggle play/pause with visual feedback
    if (videoElement.paused) {
      // Play the video
      const playPromise = videoElement.play();
      
      if (playPromise !== undefined) {
        playPromise.then(() => {
          // Successfully played - update states
          setManuallyPaused(videoKey, false);
          dispatch(setVideoPlaying({ postId, videoUrl, isPlaying: true }));
          
          // Show play icon briefly (indicating video is now playing)
          setVideoOverlays(prev => ({ 
            ...prev, 
            [videoKey]: 'play' 
          }));
          
          // Hide play icon after a short delay
          setTimeout(() => {
            setVideoOverlays(prev => ({
              ...prev,
              [videoKey]: null
            }));
          }, 800);
        }).catch(err => {
          console.error('Error playing video:', err);
          // If playback fails, try with muted
          if (!videoElement.muted) {
            videoElement.muted = true;
            videoElement.play().catch(e => console.error('Failed to play even with mute:', e));
          }
        });
      }
    } else {
      // Pause the video
      videoElement.pause();
      
      // Update states
      setManuallyPaused(videoKey, true);
      dispatch(setVideoPlaying({ postId, videoUrl, isPlaying: false }));
      
      // Show pause icon briefly (indicating video is now paused)
      setVideoOverlays(prev => ({ 
        ...prev, 
        [videoKey]: 'pause' 
      }));
      // Hide pause icon after a short delay
      setTimeout(() => {
        setVideoOverlays(prev => ({
          ...prev,
          [videoKey]: null
        }));
      }, 800);
    }
    
    // Don't show controls
    videoElement.controls = false;
    
    // Store current mute state
    videoStates.current[videoKey] = { muted: videoElement.muted };
  };
  
  // Effect to handle automatic video playback - modified to always respect global mute setting
  useEffect(() => {
    // Get all video elements
    const videoElements = document.querySelectorAll('video');
    
    // Pause all videos first - except the most visible one
    videoElements.forEach(video => {
      const videoContainer = video.closest('.video-container');
      if (!videoContainer) return;
      const videoId = videoContainer.dataset.videoId;
      // Skip the most visible video
      if (videoId === mostVisibleVideo) return;
      // Always pause videos not in view, even if manually resumed
      if (!video.paused) {
        video.pause();
        // Update Redux state for paused videos
        const [postId, videoUrl] = videoId?.split('-') || [];
        if (postId && videoUrl) {
          dispatch(setVideoPlaying({ postId, videoUrl, isPlaying: false }));
        }
      }
    });
    
    // Only play the most visible video if one is identified
    if (mostVisibleVideo && videoRefs && videoRefs.current) {
      const targetVideo = videoRefs.current[mostVisibleVideo];
      if (targetVideo) {
        // Only auto-play if the user didn't manually pause this video
        const wasManuallyPaused = isManuallyPaused(mostVisibleVideo);
        
        // Don't auto-play if user manually paused this video
        if (!wasManuallyPaused) {
          // Set appropriate properties
          const userInteracted = hasUserInteracted(mostVisibleVideo);
          
          // Always respect global mute setting but never show controls
          targetVideo.controls = false;
          
          if (isTouchDevice) {
            targetVideo.muted = globalMuted;
            
            // Update the global unmute state
            globalUnmuteState.current = !globalMuted;
            
            // Try to play the video
            targetVideo.play().catch(err => {
              console.error('Failed to autoplay video:', err);
              if (!globalMuted) {
                // If unmuted autoplay fails, try muted
                targetVideo.muted = true;
                targetVideo.play().catch(e => console.error('Failed to autoplay even with mute:', e));
              }
            });
          } else {
            // On larger screens
            targetVideo.muted = userInteracted ? 
              (videoStates.current[mostVisibleVideo]?.muted ?? globalMuted) : 
              globalMuted;
            
            // Try to play the video
            const playPromise = targetVideo.play();
            if (playPromise !== undefined) {
              playPromise.catch(() => {
                // If playback fails, try with mute
                targetVideo.muted = true;
                targetVideo.play().catch(err => {
                  console.error('Failed to autoplay video even with mute:', err);
                });
              });
            }
          }
          
          // Update Redux state
          const [postId, videoUrl] = mostVisibleVideo.split('-');
          dispatch(setVideoPlaying({ postId, videoUrl, isPlaying: true }));
        }
      }
    }
  }, [mostVisibleVideo, dispatch, hasUserInteracted, videoRefs, isManuallyPaused, isTouchDevice, globalMuted]);

  // Update all video elements when global mute state changes
  useEffect(() => {
    // Apply the global mute setting to all currently playing videos
    const videoElements = document.querySelectorAll('video');
    videoElements.forEach(video => {
      if (!video.paused) {
        video.muted = globalMuted;
      }
    });
  }, [globalMuted]);

  // Close menu when clicking outside or scrolling
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Close active menu when clicking outside
      if (activeMenu && !event.target.closest('[data-more-button="true"]')) {
        const isOutsideMenu = document.querySelectorAll('.menu-container').length > 0 && 
                             !event.target.closest('.menu-container');
        
        if (isOutsideMenu || !event.target.closest('.menu-container')) {
          setActiveMenu(null);
        }
      }
    };
    
    const handleScroll = () => {
      if (activeMenu !== null) {
        setActiveMenu(null);
      }
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("scroll", handleScroll);
    
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      window.addEventListener('scroll', handleScroll);
    };
  }, [activeMenu]);

  // Handle carousel index change
  const handleCarouselIndexChange = (postId, newIndex) => {
    dispatch(setShortMediaIndex({ postId, index: newIndex }));
  };

  // Adjust menu positioning
  useEffect(() => {
    if (activeMenu !== null) {
      const menuElement = document.querySelector('.menu-container');
      if (!menuElement) return;
      
      const rect = menuElement.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;
      
      // Check if menu is too close to the bottom
      if (rect.bottom > viewportHeight) {
        menuElement.style.bottom = '0';
        menuElement.style.top = 'auto';
      }
      
      // Check if menu is too close to the right edge (mainly for mobile)
      if (rect.right > viewportWidth) {
        menuElement.style.right = '0';
        menuElement.style.left = 'auto';
      }
      
      // Make sure it's visible on small screens 
      if (viewportWidth < 768) {
        // For mobile, position based on click location
        const moreBtnRect = menuElement.parentElement.querySelector('[data-more-button="true"]').getBoundingClientRect();
        
        // Set the menu position based on where the more button is
        menuElement.style.position = 'fixed';
        menuElement.style.top = `${moreBtnRect.top - rect.height}px`;
        menuElement.style.right = `${viewportWidth - moreBtnRect.right}px`;
      }
    }
  }, [activeMenu]);

  // Skeleton component for posts
  const PostSkeleton = () => (
    <div className="overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818] bg-[#0a0a0a] md:bg-[#0c0c0c] backdrop-blur-sm py-2 max-md:py-2 max-md:px-[4px]">
      <div className="flex items-center px-3 max-md:px-2 mb-3">
        <Skeleton circle width={40} height={40} className="mr-3" />
        <div>
          <Skeleton width={120} height={16} className="mb-1" />
          <Skeleton width={80} height={12} />
        </div>
      </div>
      <div className="px-4 max-md:px-2">
        <Skeleton count={3} className="mb-4" />
        <Skeleton height={200} className="rounded-lg mb-4" />
        <div className="flex">
          <Skeleton width={70} height={24} className="mr-4" />
          <Skeleton width={70} height={24} className="mr-4" />
          <Skeleton width={24} height={24} className="ml-auto mr-4" />
          <Skeleton width={24} height={24} />
        </div>
      </div>
    </div>
  );



  useEffect(() => {
    function handleClickOutside(e) {
      if (
        activeMenu !== null && 
        !e.target.closest('[data-more-button="true"]') && 
        !e.target.closest('.menu-container')
      ) {
        setActiveMenu(null);
      }
    }
    
    document.addEventListener('click', handleClickOutside);
    
    return () => {
      document.removeEventListener('click', handleClickOutside);
    };  }, [activeMenu]);

  // Create a handler for video volume changes that will affect all videos
  const handleVideoVolumeChange = (e, videoKey) => {
    // Get the muted state from the event
    const newMutedState = e.target.muted;
    
    // Update the video state for this specific video
    videoStates.current[videoKey] = { muted: newMutedState };
    
    // Mark this video as interacted with
    handleUserInteraction(videoKey);
    
    // For small screens, update global mute state
    if (isTouchDevice) {
      // Update global mute state
      setGlobalMuted(newMutedState);
      
      // Apply this mute state to all other videos
      const allVideos = document.querySelectorAll('video');
      allVideos.forEach(video => {
        if (video !== e.target) {
          video.muted = newMutedState;
        }
      });
    }
  };

  // Handle navbar scroll behavior
  useEffect(() => {
    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      
      // Only apply scroll behavior on mobile (navbar is only visible on mobile)
      if (window.innerWidth >= 768) return;
      
      // Don't hide navbar when at the very top
      if (currentScrollY < 10) {
        setIsNavbarVisible(true);
        setLastScrollY(currentScrollY);
        return;
      }
      
      // Calculate scroll direction and distance
      const scrollDirection = currentScrollY > lastScrollY ? 'down' : 'up';
      const scrollDistance = Math.abs(currentScrollY - lastScrollY);
      
      // Only trigger navbar visibility change if scroll distance exceeds threshold
      if (scrollDistance >= scrollThreshold) {
        if (scrollDirection === 'down') {
          setIsNavbarVisible(false);
        } else {
          setIsNavbarVisible(true);
        }
        setLastScrollY(currentScrollY);
      }
    };

    // Add scroll listener with throttling for better performance
    let scrollTimeout;
    const throttledHandleScroll = () => {
      if (scrollTimeout) {
        clearTimeout(scrollTimeout);
      }
      scrollTimeout = setTimeout(handleScroll, 10);
    };

    window.addEventListener('scroll', throttledHandleScroll, { passive: true });
    
    return () => {
      window.removeEventListener('scroll', throttledHandleScroll);
      if (scrollTimeout) {
        clearTimeout(scrollTimeout);
      }
    };
  }, [lastScrollY, scrollThreshold]);

  return (
    <div className="min-h-screen lg:max-w-[950px] max-w-[640px] mx-auto text-white relative" ref={pageRef}>
   
      {/* Add Deleting Overlay */}
      {isDeleting && (
        <div className="fixed inset-0 z-[60] bg-black bg-opacity-60 flex items-center justify-center">
          <div className="bg-black bg-opacity-80 rounded-lg px-4 py-2 flex items-center">
            <span className="text-white mr-2">Deleting</span>
            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
          </div>
        </div>
      )}
   
          {/* Header Section - Dynamic navbar with scroll animation */}
        <div className={`fixed top-0 left-0 right-0 z-40 max-md:py-2 px-[6px] max-md:border-b-4 border-[#111] backdrop-blur-sm w-full bg-[#0a0a0a]/90 md:bg-transparent md:relative transition-transform duration-300 ease-in-out ${
          isNavbarVisible ? 'translate-y-0' : 'md:translate-y-0 max-md:-translate-y-full'
        }`}>
          <div className='pr-3 mt-[1px] pl-[14px] pb-2'>
            <img src={ScubieeLogo} alt="" className='md:hidden w-[100px] pt-2'/>
              {/* Updated notification icon with badge */}
            <div 
              className="fixed right-4 top-4 md:hidden cursor-pointer"
              onClick={() => navigate('/notifications')}
            >
              <div className="relative">
                <FiBell className='w-8 h-[24px]'/>
                {notificationsLoaded && unreadNotifications > 0 && (
                  <div className="absolute top-[-5px] right-[-5px] bg-red-500 border-2 border-[#0a0a0a] text-white font-semibold text-xs rounded-full h-[18px] w-[18px] flex items-center justify-center">
                    {unreadNotifications > 9 ? '9+' : unreadNotifications}
                  </div>
                )}
              </div>
            </div>

            {/* Search icon - replaces the old search functionality */}
            <div 
              className="fixed right-16 top-4 md:hidden cursor-pointer"
              onClick={() => navigate('/search')}
            >
              <FiSearch className='w-8 h-[24px]'/>
            </div>
            
            {/* Paper icon */}
            <div 
              className="fixed right-28 top-4 md:hidden cursor-pointer"
              onClick={() => navigate('/my-papers')}
            >
              <IoNewspaperOutline className='w-8 h-[23px]'/>
            </div>
          </div>
        </div>    
        
          {/* Main content - two column layout */}
      <div className="flex justify-between md:pt-0 max-md:pt-20">
        {/* Main feed column */}
        <div className="w-full lg:w-[640px]">
          <div className="space-y-3 md:my-4 mb-16">
            {/* Loading state */}
            {loading && !posts.length && (
              <SkeletonTheme baseColor="#202020" highlightColor="#444">
                <div className="space-y-3">
                  {Array(3).fill().map((_, i) => (
                    <PostSkeleton key={i} />
                  ))}
                </div>
              </SkeletonTheme>
            )}

          
            {error && !loading && !posts.length && (
              <div className="text-center py-8">
                <p className="text-red-500 mb-3">{error}</p>
                <button 
                  onClick={() => dispatch(fetchFeedPosts(1))}
                  className="px-3 py-[6px] bg-gray-300 text-black rounded-full"
                >
                  Try Again
                </button>
              </div>
            )}

            {/* Posts with inline suggested users for mobile */}
            {posts.map((post, index) => {
              // Inject the SuggestedUsers component after the 4th post on small screens
              const displayInlineSuggestions = index === 3 && window.innerWidth < 1024;
              
              return (
                <React.Fragment key={post.id}>
                  <article
                    ref={index === posts.length - 1 ? lastPostRef : null}
                    className="overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818]  bg-[#0a0a0a] md:bg-[#0c0c0c] py-2 max-md:py-2  text-gray-300"
                    >
                    {/* Post Header */}
                    <div className="flex items-center justify-between mb-3 px-3 max-md:px-2">
                      <div 
                        className="flex items-center gap-3 max-md:ml-[6px] pt-1 md:pt-2 cursor-pointer"
                        onClick={(e) => navigateToProfile(post.author.username, e)}
                      >
                        <div className="relative h-10 w-10 max-md:h-[36px] max-md:w-[36px] rounded-full overflow-hidden group">
                          <img
                            src={post.author.profilePicture
                              ? `${cloud}/cloudofscubiee/profilePic/${post.author.profilePicture}`
                              : "/logos/DefaultPicture.png"}
                            alt={post.author.username}
                            className="w-full h-full bg-gray-300 object-cover transition-transform duration-200 group-hover:scale-110"
                          />
                          <div className="absolute inset-0 bg-black/10 group-hover:bg-black/0 "></div>
                        </div>
                        <div>
                        <div className="flex items-center gap-1">
          <h3 className="mt-[-4px] text-[15px] max-md:text-[14px] font-semibold font-sans">
            {post.author.username}
          </h3>
          {!!post.author.verified && (
            <RiVerifiedBadgeFill className="text-blue-500 h-[14px] w-[14px]" />
          )}
        </div>
                          <h3 className="text-xs max-md:text-[11px] text-gray-400">
                            {new Date(post.createdAt).toLocaleDateString('en-US', {
                              day: 'numeric',
                              month: 'short',
                              year: 'numeric'
                            })}
                          </h3>
                        </div>
                      </div>
                      
                      {/* Post menu button */}
                      <div className="relative mt-2" ref={menuRef}>
                        <button 
                          className="text-gray-400 hover:text-white p-1 rounded-full hover:bg-gray-800/30 " 
                          onClick={(e) => handleToggleMenu(post.id, e)}
                          data-more-button="true"
                        >
                          <FiMoreVertical className="h-[19px] w-[19px]" />
                        </button>
                        
                        {activeMenu === post.id && (
          <Portal>
            <div 
              className="fixed w-48 font-medium bg-[#0f0f0f] border border-gray-700 rounded-md shadow-lg z-[1000] menu-container"
              style={{
                top: `${menuPosition.top}px`,
                left: `${menuPosition.left}px`,
                maxHeight: '90vh',
                position: 'fixed' // Explicitly set fixed positioning
              }}
            >
                            <ul className="py-1 text-gray-200">
                             
                              {post.author.id !== userData?.id ? (
                  <>
                    <li 
                      className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-500"
                      onClick={(e) => handleReportPost(post.id, e)}
                    >
                      <div className="flex items-center">
                        <MdOutlineReport className="mr-2" size={16}/>
                        Report Post
                      </div>
                    </li>
                    <li 
                      className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-500"
                      onClick={(e) => handleReportUser(post.author.id, e)}
                    >
                      <div className="flex items-center">
                        <MdOutlineReport className="mr-2" size={16} />
                        Report User
                      </div>
                    </li>
                  </>
                ) : (
                  <li 
                    className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-500"
                    onClick={(e) => handleDeletePost(post.id, e)}
                  >
                    <div className="flex items-center">
                      <MdOutlineDeleteOutline className="mr-2" size={16}/>
                      Delete Post
                    </div>
                  </li>
                )}
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                                onClick={(e) => handleCopyLink(post.id, e)}
                              >
                                <div className="flex items-center">
                                  <MdOutlineContentCopy className="mr-2" />
                                  Copy Link
                                </div>
                              </li>
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                                onClick={(e) => handleCancelMenu(e)}
                              >
                                <div className="flex items-center">
                                  <IoCloseSharp className="mr-2" />
                                  Cancel
                                </div>
                              </li>
                            </ul>
                           
        </div>
         </Portal>
                        )}
                      </div>
                    </div>

                    {/* Post Content */}
                    <div className="pr-4 pl-4 max-md:px-0 cursor-pointer">                      {/* Text Content */}
                      {(post.title || post.content || post.description) && (
                       <div className="mb-[10px] max-md:ml-2 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2">
                          <SmartTruncateText
                            text={post.title || post.content || post.description}
                            className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-medium"
                          />
                        </div>
                      )}

                      {/* Media Content */}
                      {post.media && post.media.length > 0 && (
                        <div className="relative mb-4 max-md:mb-0 xl:w-[84%] md:w-[90%] mx-auto w-full">                          {/* Single media item - full width for both mobile and desktop */}
                          {post.media.length === 1 ? (                            <div className="relative mb-4">
                              <div className="max-md:w-[100%] max-md:mx-auto w-[98%] mx-auto" style={{ maxHeight: '550px' }}>
                                {post.media[0].type === 'video' ? (
                                  <div 
                                    className="max-md:rounded-lg w-full h-full video-container bg-black md:rounded-lg cursor-pointer overflow-hidden relative" 
                                    data-video-id={`${post.id}-${post.media[0].url}`}
                                    onClick={(e) => handleVideoClick(e, post.id, post.media[0].url)}
                                  >
                                    <video 
                                      ref={(el) => el && registerVideo(`${post.id}-${post.media[0].url}`, el)}
                                      src={`${cloud}/cloudofscubiee/postVideos/${post.media[0].url}`}
                                      className="w-full h-full object-contain max-h-[550px]" 
                                      
                                      muted
                                      loop
                                      playsInline
                                      preload="metadata"
                                    />
                                    {/* Play/Pause Icon Overlay */}
                                    {videoOverlays[`${post.id}-${post.media[0].url}`] === 'play' && (
                                      <div className="absolute inset-0 flex items-center justify-center bg-black/20 animate-fadeOut">
                                        <div className="rounded-full bg-black/50 p-3">
                                          <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 scale-110 text-white" viewBox="0 0 24 24" fill="currentColor">
                                            <path d="M8 5v14l11-7z"/>
                                          </svg>
                                        </div>
                                      </div>
                                    )}
                                    
                                    {videoOverlays[`${post.id}-${post.media[0].url}`] === 'pause' && (
                                      <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                                        <div className="rounded-full bg-black/50 p-3">
                                          <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 scale-110 text-white" viewBox="0 0 24 24" fill="currentColor">
                                            <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
                                          </svg>
                                        </div>
                                      </div>
                                    )}
                                  </div>                                ) : (
                                  <img 
                                    src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                                    alt="Post media" 
                                    loading="lazy"
                                    className="max-md:w-[93%] max-md:mx-auto max-md:rounded-lg w-full h-auto object-cover md:rounded-lg cursor-pointer max-h-[550px]"
                                    onClick={(e) => handleImageClick(e, post.media[0], post, 0)}
                                  />
                                )}
                              </div>
                            </div>
                          ) : (
                            /* Multiple media - carousel for both mobile and desktop */
                            <HorizontalImageScroll 
                              imageFiles={post.media}
                              post={post}
                              handleImageClick={handleImageClick}
                              cloud={cloud}
                              registerVideo={registerVideo}
                              handleVideoClick={handleVideoClick}
                              videoOverlays={videoOverlays} // Add this prop
                            />
                          )}
                        </div>
                      )}
                    </div>

                    {/* Post Actions */}
                    <div className="flex items-center md:w-[84%] xl:w-[78%] md:pl-[1px] md:mx-auto max-md:mr-[8px] max-md:ml-2 max-md:px-2 mb-3 max-md:mb-1 mt-1">                      {/* Upvote Button - Reddit/Daily.dev style */}
                      <button 
                        className={`flex items-center gap-1 px-3 py-[4px]  rounded-full border transition-all duration-200 transform hover:scale-105 ${
                          (() => {
                            const postId = post.id?.toString();
                            const isLiked = postId && postId in visualState.current.likedPosts 
                              ? visualState.current.likedPosts[postId] 
                              : likedPosts[post.id];
                            
                            return isLiked 
                              ? ' border-gray-500 bg-white/05 text-gray-200' 
                              : 'border-gray-500 bg-white/05 text-gray-300 ';
                          })()
                        }`}
                        onClick={(e) => handleLikeToggle(post.id, e)}
                        data-like-button={post.id}
                      >
                        <BiUpvote 
                          className="h-4 w-4 empty-heart" 
                          style={{
                            display: (() => {
                              const postId = post.id?.toString();
                              
                              // If we've interacted with this post, visualState is the source of truth
                              if (postId && postId in visualState.current.likedPosts) {
                                return visualState.current.likedPosts[postId] ? 'none' : 'block';
                              }
                              
                              // Otherwise fall back to Redux state
                              return likedPosts[post.id] ? 'none' : 'block';
                            })()
                          }} 
                        />
                        <BiSolidUpvote 
                          className="h-4 w-4 filled-heart" 
                          style={{
                            display: (() => {
                              const postId = post.id?.toString();
                              
                              // If we've interacted with this post, visualState is the source of truth
                              if (postId && postId in visualState.current.likedPosts) {
                                return visualState.current.likedPosts[postId] ? 'block' : 'none';
                              }
                              
                              // Otherwise fall back to Redux state
                              return likedPosts[post.id] ? 'block' : 'none';
                            })()
                          }}
                        />
                        <span className='text-sm font-medium'>
                          {(() => {
                            const postId = post.id?.toString();
                            const originalCount = post?.likes || 0;
                              
                            // If we've interacted with this post, calculate adjusted count
                            if (postId && postId in visualState.current.likedPosts) {
                              const originalLiked = likedPosts[post.id] || false;
                              
                              const visualDelta = visualState.current.likedPosts[postId] !== originalLiked
                                ? (visualState.current.likedPosts[postId] ? 1 : -1)
                                : 0;
                              
                              return Math.max(0, originalCount + visualDelta).toString();
                            }
                            
                            // Otherwise show original count
                            return originalCount.toString();
                          })()}
                        </span>
                      </button>

                      {/* Comment Button */}
                      <button 
                        className="flex items-center gap-2 text-gray-300 ml-6 group"
                        onClick={(e) => handleCommentClick(post.id, e)}
                      >
                        <div className="p-1.2 rounded-full  ">
                          <TfiCommentAlt className="mt-[1px] h-[18px] w-[18px]  " />
                        </div>
                        <span className='text-[14px] mt-[-1px]  '>
                          {(post.comments > 0) ? post.comments : '0'}
                        </span>
                      </button>

                      {/* Share Button */}
                      <button 
                        className="flex items-center text-gray-300 ml-auto group"
                        onClick={(e) => handleSharePost(post.id, e)}
                      >
                        <div className="p-1.5 rounded-full  ">
                          <BsSend className="h-[18px] w-[18px]  " />
                        </div>
                      </button>

                      {/* Save Button */}
                      <button 
                        className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
                        onClick={(e) => handleSaveToggle(post.id, e)}
                        data-save-button={post.id}
                      >
                        <div className="p-1.5 rounded-full">
                          <BsBookmark 
                            className="h-[18px] w-[18px] empty-bookmark" 
                            style={{
                              display: (() => {
                                const postId = post.id?.toString();
                                
                                // If we've interacted with this post, visualState is the source of truth
                                if (postId && postId in visualState.current.savedPosts) {
                                  return visualState.current.savedPosts[postId] ? 'none' : 'block';
                                }
                                
                                // Otherwise fall back to Redux state
                                return savedPosts[post.id] ? 'none' : 'block';
                              })()
                            }} 
                          />
                          <BsBookmarkFill 
                            className="h-[18px] w-[18px] text-white group-hover:text-gray-200 filled-bookmark" 
                            style={{
                              display: (() => {
                                const postId = post.id?.toString();
                                
                                // If we've interacted with this post, visualState is the source of truth
                                if (postId && postId in visualState.current.savedPosts) {
                                  return visualState.current.savedPosts[postId] ? 'block' : 'none';
                                }
                                
                                // Otherwise fall back to Redux state
                                return savedPosts[post.id] ? 'block' : 'none';
                              })()
                            }} 
                          />
                        </div>
                      </button>
                    </div>
                  </article>

                  {/* Show suggested users inline after the 4th post on small screens */}
                  {(index === 3 && posts.length > 4) && (
                    <div className="lg:hidden my-4">
                      <SuggestedUsers />
                    </div>
                  )}
                </React.Fragment>
              );
            })}

            {/* Load more indicator */}
            {loadingMore && (
              <div className="py-8 w-full text-center">
                <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]">
                  <span className="!absolute !-m-px !h-px !w-px !overflow-hidden !whitespace-nowrap !border-0 !p-0 ![clip:rect(0,0,0,0)]">
                    Loading more...
                  </span>
                </div>
              </div>
            )}

            {/* No posts message */}
            {!loading && !loadingMore && posts.length === 0 && (
              <div className="text-center py-10">
                <p className="text-gray-400 mb-4">No posts to show.</p>
                <p className="text-gray-500">Follow some users to see their posts in your feed!</p>
              </div>
            )}
          </div>
        </div>

        {/* Right sidebar - only visible on large screens */}
        <div className="hidden xl:ml-24 lg:block w-[290px] mt-4 sticky top-4 self-start">
          <SuggestedUsers />
        </div>
      </div>

      {/* Comment Widget */}
      {isCommentOpen && (
        <div 
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
          onClick={(e) => {
            /* Existing code */
          }}
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            className="z-[110]"
          >
            <CommentWidget
              postId={commentPostId}
              isOpen={isCommentOpen}
              onClose={handleCommentClose}
              userId={userData?.id}
            />
          </div>
        </div>
      )}

      {/* Share Widget */}
      {showShareWidget && (
        <ShareDialog 
          postId={sharePostId}
          onClose={() => setShowShareWidget(false)}
        />
      )}

      {/* Report Widget */}
      {showReportWidget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div 
            ref={reportWidgetRef}
            className="bg-[#1a1a1a] p-4 rounded-md w-[90%] sm:w-[400px] text-white relative"
            onClick={(e) => e.stopPropagation()}
          >
            <ReportWidget
              onClose={() => setShowReportWidget(false)}
              type={reportType}
              targetId={reportTargetId}
            />
            <button
              onClick={() => setShowReportWidget(false)}
              className="absolute top-2 right-2 text-gray-400 hover:text-gray-200"
            >
              <IoCloseSharp size={24} />
            </button>
          </div>
        </div>
      )}

      {/* Image Viewer */}
      {viewingImage && (
        <div 
          className="fixed inset-0 bg-black/90 z-50 flex items-center justify-center"
          onClick={closeImageViewer}
        >
          <div className="relative max-h-[85vh] min-w-[98vw]">
            <img 
              src={`${cloud}/cloudofscubiee/postImages/${viewingImage.url}`}
              alt="Enlarged view"
              className="max-h-[85vh] min-w-[98vw] object-cover"
            />
            
            {/* Navigation arrows if there are multiple images */}
            {viewingImage.postMedia && viewingImage.postMedia.filter(media => media.type !== 'video').length > 1 && (
              <>
                <button 
                  className="absolute max-md:hidden md:left-[-50px] left-2 top-1/2 transform -translate-y-1/2 bg-white/10 md:p-2 p-1 rounded-full z-10"
                  onClick={(e) => navigateImages(e, -1, viewingImage.postMedia)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="md:h-6 md:w-6 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <button 
                  className="absolute md:right-[-50px] max-md:hidden right-2 top-1/2 transform -translate-y-1/2 bg-white/10 md:p-2 p-1 rounded-full z-10"
                  onClick={(e) => navigateImages(e, 1, viewingImage.postMedia)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="md:h-6 md:w-6 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
       {deleteConfirmation.isOpen && (
             <Portal>
               <div className="fixed font-sans inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm">
                 <div 
                   className="bg-gradient-to-b from-[#222] to-[#111] p-6 rounded-xl w-[90%] max-w-[400px] shadow-2xl border border-gray-700"
                   onClick={(e) => e.stopPropagation()}
                 >
                   <div className="mb-2 flex items-center">
                     <div className="bg-red-500/20 p-2 rounded-full mr-3">
                       <MdOutlineDeleteOutline size={24} className="text-red-500" />
                     </div>
                     <h3 className="text-xl font-semibold text-white">Delete Post</h3>
                   </div>
                   
                   <div className="h-px w-full bg-gradient-to-r from-transparent via-gray-700 to-transparent my-3"></div>
                   
                   <p className="text-gray-300 mb-6 pl-1">
                     Are you sure you want to delete {deleteConfirmation.postTitle ? (
                       <span className="font-medium text-white">"{deleteConfirmation.postTitle.length > 25 ? 
                         deleteConfirmation.postTitle.substring(0, 25) + '...' : 
                         deleteConfirmation.postTitle}"</span>
                     ) : 'this post'}? This action cannot be undone.
                   </p>
                   
                   <div className="flex justify-end space-x-4">
                     <button
                       onClick={(e) => {
                         e.preventDefault();
                         e.stopPropagation();
                         cancelDelete();
                       }}
                       className="px-5 py-2.5 bg-transparent border border-gray-600 hover:bg-gray-800 text-gray-200 rounded-full transition duration-200 font-medium"
                     >
                       Cancel
                     </button>
                     <button
                       onClick={(e) => {
                         e.preventDefault();
                         e.stopPropagation();
                         confirmDelete();
                       }}
                       className="px-5 py-2.5 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 rounded-full text-white transition duration-200 font-medium flex items-center"
                     >
                       <MdOutlineDeleteOutline size={18} className="mr-1.5" />
                       Delete
                     </button>
                   </div>
                 </div>
               </div>
             </Portal>
           )}

      {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
        </div>
      )}
      
    </div>
  );
};

export default Home;