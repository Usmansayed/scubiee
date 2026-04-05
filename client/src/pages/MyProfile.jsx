import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios"; // Add this missing import
import { Twitter, Instagram, Facebook, Github, Youtube } from "lucide-react";
import { RiVerifiedBadgeFill, RiDeleteBin6Line } from 'react-icons/ri'; 
import Share from './Shorts';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { IoMdHeartEmpty, IoMdHeart } from "react-icons/io";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical, FiMessageCircle } from "react-icons/fi";
import { toast } from 'react-toastify';
import CommentWidget from "../components/CommentWidget";
import { useDispatch, useSelector } from 'react-redux';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import ShareDialog from "../components/shareWidget";
import { MdOutlineContentCopy, MdOutlineDeleteOutline, MdMenu, MdLogout, MdClose, MdOutlineBookmark, MdOutlineHelpOutline, MdOutlinePrivacyTip, MdOutlineGavel } from "react-icons/md";
import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
import { MdPerson, MdSettings } from "react-icons/md";
import { GrCircleInformation } from "react-icons/gr";

import { 
  fetchProfileInfo, 
  fetchUserPosts, 
  fetchUserShorts, 
  fetchMoreContent,
  toggleLikePost, 
  toggleSavePost,
  deletePost,
  toggleExpandText as toggleExpandTextAction,
  setShortMediaIndex as setShortMediaIndexAction,
  setVideoPlaying as setVideoPlayingAction
} from '../Slices/profileSlice';
import ShortMediaCarousel from '../components/ShortMediaCarousel';
import useInteractionManager from '../hooks/useInteractionManager';
import FollowsWidget from "../components/FollowsWidget";
import { createPortal } from 'react-dom';

import './Profile.css';

const api = import.meta.env.VITE_API_URL;
const cloud = import.meta.env.VITE_CLOUD_URL;

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

// Add Portal component
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted ? createPortal(children, document.body) : null;
};

// Add this custom hook near the other hooks at the top
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

// Update HorizontalImageScroll component to match Home.jsx's version
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
                  
                  {/* Play/Pause Icon Overlay */}
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
                </div>              ) : (                <img 
                  src={`${cloud}/cloudofscubiee/postImages/${media.url}`}
                  alt={`Media ${i}`} 
                  loading="lazy"
                  className="max-md:w-[93%] max-md:mx-auto max-md:rounded-lg w-full h-full object-cover md:rounded-lg cursor-pointer"
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

// --- COPY FROM Home.jsx: useVideoAutoplay HOOK ---
const useVideoAutoplay = (dependencies = []) => {
  const [mostVisibleVideo, setMostVisibleVideo] = useState(null);
  const videoRefs = useRef({});
  const observers = useRef({});
  const visibilityRatios = useRef({});
  const userInteracted = useRef({});
  const manuallyPaused = useRef({});
  const firstClickHandled = useRef({});

  const registerVideo = useCallback((id, element) => {
    if (!element) return;
    videoRefs.current[id] = element;
    if (observers.current[id]) observers.current[id].disconnect();
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          visibilityRatios.current[id] = entry.intersectionRatio;
          if (entry.intersectionRatio < 0.5 && mostVisibleVideo === id) {
            setMostVisibleVideo(null);
          }
          if (entry.intersectionRatio >= 0.5) {
            let maxRatio = 0, maxId = null;
            Object.keys(visibilityRatios.current).forEach(videoId => {
              if (visibilityRatios.current[videoId] > maxRatio) {
                maxRatio = visibilityRatios.current[videoId];
                maxId = videoId;
              }
            });
            if (maxId && maxRatio > 0.5) setMostVisibleVideo(maxId);
          }
        });
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1.0], root: null }
    );
    observer.observe(element);
    observers.current[id] = observer;
  }, [mostVisibleVideo]);

  const handleUserInteraction = useCallback((id) => { userInteracted.current[id] = true; }, []);
  const setManuallyPaused = useCallback((id, isPaused) => { manuallyPaused.current[id] = isPaused; }, []);
  const isManuallyPaused = useCallback((id) => manuallyPaused.current[id] || false, []);
  const hasUserInteracted = useCallback((id) => userInteracted.current[id] || false, []);
  const isFirstClickHandled = useCallback((id) => firstClickHandled.current[id] || false, []);
  const setFirstClickHandled = useCallback((id, handled) => { firstClickHandled.current[id] = handled; }, []);
  useEffect(() => {
    return () => { Object.values(observers.current).forEach(observer => observer && observer.disconnect()); };
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
};
// --- END COPY ---

const MyProfile = () => {
  // Add state to track rehydration status
  const [showMenu, setShowMenu] = useState(false);

  const [storeReady, setStoreReady] = useState(!!window.reduxRehydrated);
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map());
  const visualState = useRef({
    likedPosts: {},  // Track visual state separate from Redux
    savedPosts: {}   // Track visual state separate from Redux
  });
  useEffect(() => {
    return () => {
      pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingSaveOperations.current.clear();
    };
  }, []);
  // Add a flag to track if we've deliberately decided to fetch data
  const hasMadeFetchDecision = useRef(false);
  
  // Add loading debug state
  const [debugInfo, setDebugInfo] = useState({
    cachedDataDetected: false,
    fetchReason: null,
    renderCount: 0
  });

  // When component mounts, immediately check and log cached data status
  useEffect(() => {
    const state = window.store?.getState() || {};
    const profileData = state.profile?.profileInfo;
    const postsData = state.profile?.userPosts;
    
    setDebugInfo(prev => ({
      ...prev,
      cachedDataDetected: !!profileData?.id && Array.isArray(postsData) && postsData.length > 0,
      renderCount: prev.renderCount + 1
    }));
    
   
  }, []);
   

  // Add state for offline status
  const [isOffline, setIsOffline] = useState(!navigator.onLine);
  const [showCacheMessage, setShowCacheMessage] = useState(false);
  
  // Monitor online/offline status
  useEffect(() => {
    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Add bottomSheetRef at the top with other refs
  const bottomSheetRef = useRef(null);
  
  const [activeTab, setActiveTab] = useState(false);
  // Get profile data from Redux instead of local state
  const DefaultPicture = "/logos/DefaultPicture.png";
  const DefaultCover = "/logos/DefualtCover.png";

  // Redux state selectors - improved with proper null checking
  const dispatch = useDispatch();
  
  // Debugging the whole Redux state
  const wholeReduxState = useSelector(state => state);
  
  // Extreme defensive programming - fallback to empty objects when state is undefined
  const profile = useSelector(state => state?.profile) || {};
  
  // Additional defensive checks for profile data
  const userProfile = profile?.profileInfo || {};
  const userPosts = profile?.userPosts || [];
  const userShorts = profile?.userShorts || null;
  const loading = profile?.loading || false;
  const postsLoading = profile?.postsLoading || false;
  const shortsLoading = profile?.shortsLoading || false;
  const loadingMore = profile?.loadingMore || false;
  const hasMorePosts = profile?.hasMorePosts ?? true;
  const hasMoreShorts = profile?.hasMoreShorts ?? true;
  const error = profile?.error || null;
  const likedPosts = profile?.likedPosts || {};
  const savedPosts = profile?.savedPosts || {};  const expandedTexts = profile?.expandedTexts || {};
  const shortMediaIndexes = profile?.shortMediaIndexes || {};

  // Chat-related state and selectors (moved from Home.jsx)
  const [validatedUnreadCount, setValidatedUnreadCount] = useState(0);
  const [isInitialRender, setIsInitialRender] = useState(true);
  const [chatDataLoaded, setChatDataLoaded] = useState(false);
  
  const recentChats = useSelector(state => state.chat.recentChats);
  const unreadCount = useSelector(state => {
    const currentUserId = state.user.userData?.id;
    if (!currentUserId || !state.chat.recentChats || state.chat.recentChats.length === 0) {
      return 0;
    }
    
    return state.chat.recentChats.reduce((count, chat) => {
      if (
        chat.lastActivity?.type === 'message' &&
        chat.lastActivity.data.senderId !== currentUserId &&
        !chat.lastActivity.data.read
      ) {
        return count + 1;
      }
      return count;
    }, 0);
  });

   useEffect(() => {
      setGlobalMuted(false);
    }, []);
    
  // Local UI state (not migrated to Redux)
  const [selectedPost, setSelectedPost] = useState(null);
  const [showOptions, setShowOptions] = useState(false);
  const [selectedShort, setSelectedShort] = useState(null);
  const [CommentPostId, setCommentPostId] = useState(null);
  const navigate = useNavigate();
  const [playingVideos, setPlayingVideos] = useState({});
  const widgetRef = useRef(null);
  const observerRef = useRef(null);
  const [activeMenu, setActiveMenu] = useState(null);
  const menuRef = useRef(null);
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [sharePostId, setSharePostId] = useState(null);
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  // Add these new states for image viewing
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);
  
  // Add local loading state
  const [localLoading, setLocalLoading] = useState(true);

  // Add state for follows widget
  const [showFollowsWidget, setShowFollowsWidget] = useState(false);
  const [followsWidgetType, setFollowsWidgetType] = useState('followers');

  // Add state for copy notification
  const [showCopyNotification, setShowCopyNotification] = useState(false);

  // Add delete confirmation state
  const [deleteConfirmation, setDeleteConfirmation] = useState({
    isOpen: false,
    postId: null,
    postTitle: ''
  });

  // Add deletion loading state
  const [isDeleting, setIsDeleting] = useState(false);
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  // Chat-related useEffects (moved from Home.jsx)
  useEffect(() => {
    if (isInitialRender || !recentChats || recentChats.length === 0) {
      return;
    }
    
    const hasValidStructure = recentChats.some(chat => 
      chat && chat.lastActivity && chat.lastActivity.data && 
      typeof chat.lastActivity.data.read !== 'undefined'
    );

    if (!hasValidStructure) {
      return;
    }
    
    const timer = setTimeout(() => {
      setChatDataLoaded(true);
    }, 0);
    
    return () => clearTimeout(timer);
  }, [recentChats, isInitialRender]);

  useEffect(() => {
    if (!chatDataLoaded || isInitialRender) {
      return;
    }
    
    setValidatedUnreadCount(prev => {
      if (unreadCount === 0) return 0;
      if (unreadCount > prev) return unreadCount;
      return prev;
    });
  }, [unreadCount, chatDataLoaded, isInitialRender]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsInitialRender(false);
    }, 1000);
    
    return () => clearTimeout(timer);
  }, []);

  const handleLogout = async () => {
    try {
      setIsLoggingOut(true);
  
      // Make a request to the server to clear the HTTP-only cookie
      await axios.post(`${api}/user/logout`, {}, {
        withCredentials: true // Important for cookies
      });
  
      // Clear any local storage items if needed
      localStorage.removeItem("accessToken");
  
      // Force redirect to login page (hard reload)
      window.location.href = "/sign-in";
    } catch (error) {
      console.error("Logout error:", error);
      toast.error("Logout failed. Please try again.");
    } finally {
      setIsLoggingOut(false);
    }
  };

  // Add this component for shorts loading
  const ShortsLoadingSkeleton = () => (
    <div className="space-y-3 w-full my-4 mb-16">
      {Array(2).fill().map((_, index) => (
        <div key={index} className="relative flex justify-center bg-[#111111] 
          w-full max-w-sm mx-auto h-[84vh] max-h-[650px] border-[1px] border-gray-800 
          bg-card rounded-xl overflow-hidden">
          <Skeleton height="100%" width="100%" />
        </div>
      ))}
    </div>
  );

  // Add this component for content loading
  const ContentLoadingSkeleton = () => (
    <div className="space-y-3 w-full my-4 mb-16 max-w-[640px]">
      {Array(3).fill().map((_, index) => (
        <div key={index} className="w-full">
          <Skeleton height={300} className="rounded-xl" />
        </div>
      ))}
    </div>
  );

  useEffect(() => {
    if (selectedPost || selectedShort) {
      // When a widget opens, push a new history state
      window.history.pushState({ widget: true }, "");
  
      // Add event listener for popstate (back button press)
      const handlePopState = (event) => {
        // Close the widget when the back button is pressed
        if (selectedPost) setSelectedPost(null);
        if (selectedShort) setSelectedShort(null);
      };
  
      window.addEventListener("popstate", handlePopState);
      
      return () => {
        // Clean up event listener when component unmounts or widget closes
        window.removeEventListener("popstate", handlePopState);
      };
    }
  }, [selectedPost, selectedShort]);
  
  // Simplified data check - only check if the data exists, no time-based checks
  const hasProfileData = useCallback(() => {
    // We have valid data if we have profile info with an ID
    return !!userProfile?.id;
  }, [userProfile?.id]);

  const hasPostsData = useCallback(() => {
    // We have valid posts data if userPosts exists and has items
    return Array.isArray(userPosts) && userPosts.length > 0;
  }, [userPosts]);

  // Only load if we don't have profile data AND we're in a loading state
  const initialLoading = (loading || postsLoading || (activeTab && shortsLoading) || localLoading) && 
                        (!hasProfileData()); // <-- Only check profile data

  // First useEffect - check for Redux rehydration
  useEffect(() => {
   
    
    // If Redux is already rehydrated, we're good
    if (window.reduxRehydrated) {
      setStoreReady(true);
      return;
    }
    
    // Listen for the rehydration event
    const handleRehydration = () => {
      setStoreReady(true);
    };
    
    window.addEventListener('redux-persist-rehydrated', handleRehydration);
    
    // Also check periodically in case we missed the event
    const interval = setInterval(() => {
      if (window.reduxRehydrated) {
        setStoreReady(true);
        clearInterval(interval);
      }
    }, 100);
    
    return () => {
      window.removeEventListener('redux-persist-rehydrated', handleRehydration);
      clearInterval(interval);
    };
  }, []);

  // MODIFIED: Always fetch profile data when component mounts - don't rely on cached data
  useEffect(() => {
    // Skip all fetching logic until the store is ready
    if (!storeReady) {
      return;
    }
    
    // Only make the fetch decision once
    if (hasMadeFetchDecision.current) {
      return;
    }
    
    
    // Mark that we've made the decision, so we don't repeatedly evaluate
    hasMadeFetchDecision.current = true;
    
    // Always fetch fresh data from the server
    setLocalLoading(true);
    dispatch(fetchProfileInfo())
      .unwrap()
      .then(profileData => {
        setLocalLoading(false);
        if (profileData?.id) {
          // If we have profile data, fetch posts
          dispatch(fetchUserPosts(profileData.id));
        }
      })
      .catch(() => {
        setLocalLoading(false);
        // Show error message when fetch fails
        toast.error("Failed to load profile data. Please try again.");
      });
  }, [dispatch, storeReady]);

  // Add this function to handle image clicks
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
  
  // Function to close the image viewer
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

  // Add state for offline status
  const [shortsContentLoading, setShortsContentLoading] = useState(false);

  // Update the fetchUserShorts effect to handle loading states better - with additional checks
  useEffect(() => {
    // Only fetch shorts if tab is active, no shorts are loaded yet, and we have a user ID
    if (activeTab && userShorts === null && userProfile?.id) {
      // Set local loading state first
      setShortsContentLoading(true);
      
      dispatch(fetchUserShorts(userProfile.id))
        .unwrap()
        .then(() => {
          // Clear loading state when done
          setShortsContentLoading(false);
        })
        .catch(() => {
          // Also clear loading on error
          setShortsContentLoading(false);
        });
    }
  }, [activeTab, userShorts, userProfile?.id, dispatch]);

  // Observer for infinite scrolling
  const lastElementRef = useCallback((node) => {
    // Don't observe if we're loading anything or if there's no more content to load
    if (initialLoading || loadingMore) return;
    
    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    observerRef.current = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting) {
        const activeContent = activeTab ? userShorts : userPosts;
        const hasMore = activeTab ? hasMoreShorts : hasMorePosts;
        
        // Only fetch more if the current array length is a multiple of 9 (indicating full pages)
        // and if hasMore is true
        if (activeContent && activeContent.length > 0 && activeContent.length % 9 === 0 && hasMore) {
          const lastItemId = activeContent[activeContent.length - 1].id;
          dispatch(fetchMoreContent({ isShort: activeTab, lastItemId }));
        }
      }
    });

    if (node) {
      observerRef.current.observe(node);
    }
  }, [loadingMore, initialLoading, activeTab, hasMorePosts, hasMoreShorts, userPosts?.length, userShorts?.length, dispatch]);

  // Update the handle tab change function to handle empty array states properly
  const handleTabChange = (isShortTab) => {
    // Only change state if the tab is actually different
    if (activeTab !== isShortTab) {
      setActiveTab(isShortTab);
      
      // Only set loading state when shorts haven't been loaded at all (null)
      // Not when shorts are empty array (already loaded but empty)
      if (isShortTab && userShorts === null && userProfile?.id) {
        setShortsContentLoading(true);
      }
    }
  };

  // Show post details
  const fetchPostDetails = async (postId) => {
    try {
      const { data } = await axios.get(`${api}/post/details/${postId}`, {
        withCredentials: true,
        headers: { accessToken: localStorage.getItem("accessToken") },
      });

      if (data) {
        setSelectedPost(data);
      }
    } catch (error) {
      console.error("Error fetching post details:", error);
    }
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      // Check if we're clicking on a menu container or menu item
      const isInsideMenu = event.target.closest('.menu-container');
      const isMoreButton = event.target.closest('[data-more-button="true"]');
      
      // Only close the menu if clicking outside both the menu and the more button
      if (activeMenu && !isInsideMenu && !isMoreButton) {
        setActiveMenu(null);
      }
      
      // We'll keep the widgetRef logic for other widgets but not for post display
      if (widgetRef.current && !widgetRef.current.contains(event.target)) {
        setShowOptions(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [widgetRef, activeMenu]);

  const toggleOptions = () => {
    setShowOptions(!showOptions);
  };
  useEffect(() => {
    setGlobalMuted(false);
  }, []);

  const { createLikeHandler, createCommentLikeHandler } = useInteractionManager();
  
  // Add this useEffect to clean up any pending timers when component unmounts
  useEffect(() => {
    return () => {
      // Clear all pending like operations
      pendingLikeOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingLikeOperations.current.clear();
      
      // Clear all pending save operations
      pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingSaveOperations.current.clear();
    };
  }, []);
  const handleLikeToggle = (postId, e) => {
    if (e) e.stopPropagation();
  
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
    
    // Find the post in either userPosts or userShorts
    const post = userPosts.find(p => p.id === postId) || 
                 (Array.isArray(userShorts) ? userShorts.find(s => s.id === postId) : null);
    const originalCount = post?.likes || 0;
      // 2. TOGGLE the local visual state
    const hasVisualState = postIdStr in visualState.current.likedPosts;
    const currentVisualState = hasVisualState 
      ? visualState.current.likedPosts[postIdStr] 
      : originalBackendState;
    
    const newVisualState = !currentVisualState;
    visualState.current.likedPosts[postIdStr] = newVisualState;
    
    // If this is a like action (not unlike), show the upvote animation
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
  // Fixed handleCommentClick function - exactly like PostWidget
  const handleCommentClick = (postId, e) => {
    if (e) e.stopPropagation();
    dispatch(setIsCommentOpen(true));
    setCommentPostId(postId);
  };

  const handleSharePost = (postId, e) => {
    if (e) e.stopPropagation();
    setSharePostId(postId);
    setShowShareWidget(true);
  };

  // Add state for menu position
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

  const handleToggleMenu = (postId, e) => {
    e.stopPropagation();
    
    if (activeMenu === postId) {
      setActiveMenu(null);
      return;
    }
    
    // Get the position of the clicked button
    const buttonRect = e.currentTarget.getBoundingClientRect();
    
    // Calculate menu position - fixed for both dimensions
    if (window.innerWidth < 768) {
      // Mobile: position at button level but right-aligned
      setMenuPosition({
        top: buttonRect.top, // Keep at the same vertical level (good positioning)
        left: window.innerWidth - 192, // Right align the menu (192px = menu width)
      });
    } else {
      // Desktop: position at button level, with right edge aligned to button right edge
      setMenuPosition({
        top: buttonRect.top, // Keep at the same vertical level (good positioning)
        left: buttonRect.right - 192, // Align right edges (good horizontal positioning)
      });
    }
    
    setActiveMenu(postId);
  };

  const handleDeletePost = (postId, e) => {
    e.stopPropagation();
    
    if (!navigator.onLine) {
      toast.warning("You're offline. Please try again when connected.");
      return;
    }
    
    // Find the post
    const post = [...userPosts, ...(userShorts || [])].find(p => p.id === postId);
    
    if (!post) {
      return;
    }
    
    // Add proper null checks for author property
    if (!post.author) {
      // Still allow deletion if post exists but author data is missing
      setDeleteConfirmation({
        isOpen: true,
        postId: postId,
        postTitle: post.title || post.content?.substring(0, 30) || 'this post'
      });
      setActiveMenu(null);
      return;
    }
    
    // Since we're in the user's profile, we assume they own the posts
    // but let's still validate to be safe
    if (userProfile && userProfile.id === post.author.id) {
      // Open the confirmation modal
      setDeleteConfirmation({
        isOpen: true,
        postId: postId,
        postTitle: post.title || post.content?.substring(0, 30) || 'this post'
      });
    } else {
      toast.error("You don't have permission to delete this post");
    }
    
    setActiveMenu(null);
  };

  const confirmDelete = () => {
    
    // Show deleting UI
    setIsDeleting(true);
    
    // Close the modal immediately
    setDeleteConfirmation({
      isOpen: false,
      postId: null,
      postTitle: ''
    });
    
    // Call the delete API through Redux
    if (deleteConfirmation.postId) {
      dispatch(deletePost(deleteConfirmation.postId))
        .then((result) => {
          if (result.meta.requestStatus === 'fulfilled') {
            // Dispatch to other reducers to ensure consistency across the app
            dispatch({ type: 'home/removePost', payload: deleteConfirmation.postId });
            dispatch({ type: 'shorts/removeShort', payload: deleteConfirmation.postId });
            
            toast.success("Post deleted successfully");
          } else {
            toast.error('Failed to delete post. Please try again.');
          }
        })
        .finally(() => {
          // Hide deleting UI after operation completes (success or error)
          setIsDeleting(false);
        });
    }
  };

  const cancelDelete = () => {
    // Just close the modal
    setDeleteConfirmation({
      isOpen: false,
      postId: null,
      postTitle: ''
    });
  };

  const handleCancelMenu = (e) => {
    e.stopPropagation();
    setActiveMenu(null);
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
      .then(() => {
        // Show notification
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
  
  const handleCopyLink = (postId) => {
    copyToClipboard(`${window.location.origin}/viewpost/${postId}`);
  };

  // Add this ref for detecting scrolls
  const pageRef = useRef(null);

  // Add this useEffect for scroll detection to close menus
  useEffect(() => {
    const handleScroll = () => {
      if (activeMenu !== null) {
        setActiveMenu(null);
      }
    };

    // Add scroll event listener to the page container
    const pageElement = pageRef.current;
    if (pageElement) {
      pageElement.addEventListener('scroll', handleScroll);
    }

    // Also add to window for mobile scrolling
    window.addEventListener('scroll', handleScroll);

    return () => {
      if (pageElement) {
        pageElement.removeEventListener('scroll', handleScroll);
      }
      window.addEventListener('scroll', handleScroll);
    };
  }, [activeMenu]);

  useEffect(() => {
    // Preload images for shortcuts to make navigation feel instant
    Object.entries(shortMediaIndexes).forEach(([postId, currentIndex]) => {
      // Find the post that matches this postId
      const post = [...(userPosts || []), ...(userShorts || [])].find(p => p.id === postId);
      
      if (post?.media && post.media.length > 1) {
        // Only preload if there are multiple media items
        const prevIndex = currentIndex === 0 ? post.media.length - 1 : currentIndex - 1;
        const nextIndex = currentIndex === post.media.length - 1 ? 0 : currentIndex + 1;
        
        // Preload previous and next images (skip videos)
        if (post.media[prevIndex]?.type === 'image') {
          const prevImg = new Image();
          prevImg.src = `${cloud}/cloudofscubiee/shortImages/${post.media[prevIndex].url}`;
        }
        
        if (post.media[nextIndex]?.type === 'image') {
          const nextImg = new Image();
          nextImg.src = `${cloud}/cloudofscubiee/shortImages/${post.media[nextIndex].url}`;
        }
      }
    });
  }, [shortMediaIndexes, userPosts, userShorts]);

  const goToPrevShortMedia = (postId, e) => {
    if (e) e.stopPropagation();
    
    // Get current index
    const currentIndex = shortMediaIndexes[postId] || 0;
    if (currentIndex === 0) return;
    
    // Dispatch Redux action FIRST
    const newIndex = currentIndex - 1;
    dispatch(setShortMediaIndexAction({ postId, index: newIndex }));
    
    // Then handle visual feedback with requestAnimationFrame
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 100);
      });
    }
  };

  const goToNextShortMedia = useCallback((postId, mediaLength, e) => {
    if (e) e.stopPropagation();
    
    // Get current index
    const currentIndex = shortMediaIndexes[postId] || 0;
    if (currentIndex >= mediaLength - 1) return;
    
    // Dispatch Redux action to update the index
    const newIndex = currentIndex + 1;
    dispatch(setShortMediaIndexAction({ postId, index: newIndex }));
    
    // Visual feedback if needed
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 100);
      });
    }
  }, [dispatch, shortMediaIndexes]);

  const handleCarouselIndexChange = useCallback((postId, newIndex) => {
    if (postId && typeof newIndex === 'number') {
      dispatch(setShortMediaIndexAction({ postId, index: newIndex }));
    }
  }, [dispatch]);

  // Add a function to handle touch navigation for shorts
  const handleShortTouchStart = useRef({ x: 0, postId: null });
  const handleShortTouchEnd = useRef({ x: 0, postId: null });

  const handleShortTouchMove = (e, postId, mediaLength) => {
    if (handleShortTouchStart.current.postId !== postId) {
      handleShortTouchStart.current = { 
        x: e.touches[0].clientX, 
        postId 
      };
      return;
    }
    
    handleShortTouchEnd.current = { 
      x: e.touches[0].clientX, 
      postId 
    };
    
    // Calculate swipe distance
    const diff = handleShortTouchStart.current.x - handleShortTouchEnd.current.x;
    
    // If the swipe is significant enough
    if (Math.abs(diff) > 50) {
      if (diff > 0) {
        // Swiped left - go to next media
        goToNextShortMedia(postId, mediaLength);
      } else {
        // Swiped right - go to previous media
        goToPrevShortMedia(postId);
      }
      
      // Reset after handling the swipe
      handleShortTouchStart.current = { x: e.touches[0].clientX, postId };
    }
  };

  // --- VIDEO AUTOPLAY LOGIC (copy from Home.jsx) ---
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
  } = useVideoAutoplay([userPosts, userShorts]);

  const videoStates = useRef({});
  const globalUnmuteState = useRef(false);
  const [globalMuted, setGlobalMuted] = useState(false);

  // Detect touch device or small screen on mount
  const [isTouchDevice, setIsTouchDevice] = useState(false);
  useEffect(() => {
    const checkTouchDevice = () => {
      setIsTouchDevice('ontouchstart' in window || navigator.maxTouchPoints > 0 || window.innerWidth < 1280);
    };
    checkTouchDevice();
    window.addEventListener('resize', checkTouchDevice);
    return () => window.removeEventListener('resize', checkTouchDevice);
  }, []);

  // Add state for video overlays
  const [videoOverlays, setVideoOverlays] = useState({});

  // Updated video click handler for Twitter-like functionality
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
          setPlayingVideos(prev => ({ ...prev, [container.dataset.videoId]: false }));
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
          setPlayingVideos(prev => ({ ...prev, [videoKey]: true }));
          
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
      setPlayingVideos(prev => ({ ...prev, [videoKey]: false }));
      
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

  // Update the useEffect for autoplay behavior to match Home.jsx - but always keep controls false
  useEffect(() => {
    const videoElements = document.querySelectorAll('video');
    videoElements.forEach(video => {
      const videoContainer = video.closest('.video-container');
      if (!videoContainer) return;
      const videoId = videoContainer.dataset.videoId;
      if (videoId === mostVisibleVideo) return;
      const userHasInteracted = hasUserInteracted(videoId);
      if (!userHasInteracted || !mostVisibleVideo) {
        if (!video.paused) {
          video.pause();
          setPlayingVideos(prev => ({ ...prev, [videoId]: false }));
        }
      }
    });
    
    if (mostVisibleVideo && videoRefs && videoRefs.current) {
      const targetVideo = videoRefs.current[mostVisibleVideo];
      if (targetVideo) {
        const wasManuallyPaused = isManuallyPaused(mostVisibleVideo);
        if (!wasManuallyPaused) {
          const userInteracted = hasUserInteracted(mostVisibleVideo);
          
          // Always keep controls false regardless of screen size or interaction
          targetVideo.controls = false;
          
          if (isTouchDevice) {
            targetVideo.muted = globalMuted;
            globalUnmuteState.current = !globalMuted;
            targetVideo.play().catch(() => {
              if (!globalMuted) {
                targetVideo.muted = true;
                targetVideo.play().catch(() => {});
              }
            });
          } else {
            targetVideo.muted = userInteracted ? (videoStates.current[mostVisibleVideo]?.muted ?? globalMuted) : globalMuted;
            const playPromise = targetVideo.play();
            if (playPromise !== undefined) {
              playPromise.catch(() => {
                targetVideo.muted = true;
                targetVideo.play().catch(() => {});
              });
            }
          }
          setPlayingVideos(prev => ({ ...prev, [mostVisibleVideo]: true }));
        }
      }
    }
  }, [mostVisibleVideo, hasUserInteracted, videoRefs, isManuallyPaused, isTouchDevice, globalMuted]);

  // Create a handler for video volume changes that will affect all videos
  const handleVideoVolumeChange = (e, videoKey) => {
    const newMutedState = e.target.muted;
    videoStates.current[videoKey] = { muted: newMutedState };
    handleUserInteraction(videoKey);
    if (isTouchDevice) {
      setGlobalMuted(newMutedState);
      const allVideos = document.querySelectorAll('video');
      allVideos.forEach(video => {
        if (video !== e.target) {
          video.muted = newMutedState;
        }
      });
    }
  };

  // Update all video elements when global mute state changes
  useEffect(() => {
    const videoElements = document.querySelectorAll('video');
    videoElements.forEach(video => {
      if (!video.paused) {
        video.muted = globalMuted;
      }
    });
  }, [globalMuted]);
  
  // Remove the useEffect that sets globalMuted to false, as we want to start unmuted like Home.jsx

  const handleSaveToggle = (postId, e) => {
    if (e) e.stopPropagation();
    
    const postIdStr = postId.toString();
    
    // Remember the ORIGINAL backend state
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
      // Update icon displays
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
      if (visualState.current.savedPosts[postIdStr] !== originalBackendState) {
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
  const handleShowFollows = (type) => {
    setFollowsWidgetType(type);
    setShowFollowsWidget(true);
  };

  // Skeleton component for the profile
  const ProfileSkeleton = () => (
    <div className="min-h-screen max-w-[700px] mx-auto bg-[#0a0a0a] text-white font-sans overflow-x-hidden">
      <section>
        <div className="w-full mx-auto">
          {/* Cover Image Skeleton */}
          <div className="relative h-48 w-full">
            <Skeleton height={192} width="100%" borderRadius={0} className="rounded-b-lg" />
          </div>

          <div className="flex">
            {/* Left half */}
            <div className="w-[50%] max-xl:w-[60%] max-md:w-[100%]">
              <div className="relative px-4 sm:px-6 lg:px-8">
                {/* Profile Picture Skeleton */}
                <div className="absolute -top-20 max-md:-top-[60px] left-4 sm:left-6 lg:left-8">
                  <Skeleton circle height={160} width={160} className="max-md:h-32 max-md:w-32" />
                </div>

                {/* User Info Skeleton */}
                <div className="pt-24 max-md:mt-0 pb-6">
                  <div className="flex justify-between items-center">
                    <div className="max-md:hidden">
                      <Skeleton width={200} height={30} className="mb-2" />
                      <Skeleton width={120} height={16} />
                    </div>
                  </div>

                  {/* Tags Skeleton */}
                  <div className="mt-4 space-x-2">
                    <Skeleton width={100} height={24} borderRadius={20} inline />
                    <Skeleton width={60} height={24} borderRadius={20} inline />
                  </div>

                  {/* Bio Skeleton */}
                  <div className="mt-4">
                    <Skeleton count={3} width={300} />
                  </div>

                  {/* Social Links + Edit Profile Button Skeleton */}
                  <div className="flex space-x-4 mt-6">
                    <Skeleton circle width={24} height={24} />
                    <Skeleton circle width={24} height={24} />
                    <Skeleton circle width={24} height={24} />
                    <Skeleton width={100} height={34} borderRadius={20} />
                  </div>
                </div>
              </div>
            </div>

            {/* Right half - Stats */}
            <div className="space-y-4 w-[50%] h-full mt-10 pr-2">
              <div className="flex justify-end w-full max-md:hidden space-x-8 mb-1">
                <Skeleton width={60} height={60} />
                <Skeleton width={60} height={60} />
                <Skeleton width={60} height={60} />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Tabs Skeleton */}
      <div className="mt-4 w-full flex flex-col items-center">
        <Skeleton width="100%" height={40} className="max-w-[700px] rounded-xl" />
        
        {/* Content Skeleton */}
        <div className="space-y-3 w-full my-4 mb-16 max-w-[640px]">
          {Array(3).fill().map((_, index) => (
            <div key={index} className="w-full">
              <Skeleton height={300} className="rounded-xl" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  // Create a force refresh function that's more robust
  const forceRefreshProfile = () => {
    
    // Show toast if offline
    if (isOffline) {
      toast.warning("You're offline. Unable to refresh data.");
      return;
    }
    
    setLocalLoading(true);
    
    // Parallel fetching of profile and posts
    dispatch(fetchProfileInfo())
      .unwrap()
      .then(profileData => {
        if (profileData?.id) {
          // If we have profile data, fetch posts
          return dispatch(fetchUserPosts(profileData.id)).unwrap();
        }
      })
      .then(() => {
        setLocalLoading(false);
        toast.success("Profile refreshed successfully");
      })
      .catch(() => {
        setLocalLoading(false);
        toast.error("Failed to refresh profile. Please try again.");
      });
  };
  
  // Add a loading error component
  const LoadingErrorComponent = () => (
    <div className="flex flex-col items-center justify-center min-h-screen bg-[#0a0a0a] text-white">
      <div className="bg-red-900/20 border border-red-500 rounded-lg p-6 max-w-md mx-auto text-center">
        <h2 className="text-xl font-semibold mb-3">Profile Data Unavailable</h2>
        <p className="mb-4">There was an issue loading your profile data. This might happen if:</p>
        <ul className="list-disc text-left mb-4 pl-6">
          <li>The connection to the server timed out</li>
          <li>Your session has expired</li>
          <li>The Redux store wasn't properly initialized</li>
        </ul>
        <button 
          onClick={forceRefreshProfile}
          className="px-4 py-2 bg-blue-600 rounded-md hover:bg-blue-700 transition"
        >
          Retry Loading Profile
        </button>
        <div className="mt-3">
          <button 
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-gray-700 rounded-md hover:bg-gray-600 transition"
          >
            Reload Page
        </button>
        </div>
      </div>
    </div>
  );

  // Show error component if there's a critical issue
  if (!profile && wholeReduxState && Object.keys(wholeReduxState).length > 0) {
    return <LoadingErrorComponent />;
  }

  // Show skeleton during initial loading or explicit local loading state - display skeleton immediately
  if (initialLoading || localLoading) {
    // Return skeleton with debug button
    return (
      <SkeletonTheme baseColor="#202020" highlightColor="#444">
        <div>
          
          <ProfileSkeleton />
        </div>
      </SkeletonTheme>
    );
  }



  // Add a cached data toast that appears briefly
  const CachedDataMessage = () => {
    if (!showCacheMessage) return null;
    
    return (
      <div className="fixed bottom-6 left-1/2 transform -translate-x-1/2 bg-gray-800 text-white px-4 py-2 rounded-lg shadow-lg z-50 transition-opacity">
        Using cached profile data
      </div>
    );
  };

  // Add a debug panel to help diagnose what's happening
  const DebugPanel = () => {
    const isDebugMode = new URLSearchParams(window.location.search).get('debug') === 'true';
    
    if (!isDebugMode) return null;
    
    return (
      <div className="fixed bottom-0 left-0 right-0 bg-black/80 text-white text-xs p-2 z-50">
        <div className="flex justify-between items-center">
          <div>
            <div>Redux: {storeReady ? '✅' : '⏳'}</div>
            <div>Cache: {debugInfo.cachedDataDetected ? '✅' : '❌'}</div>
            <div>Fetch: {debugInfo.fetchReason || 'None'}</div>
            <div>Profile: {hasProfileData() ? '✅' : '❌'}</div>
            <div>Posts: {hasPostsData() ? `✅ (${userPosts.length})` : '❌'}</div>
          </div>
          <button 
            onClick={forceRefreshProfile}
            className="bg-blue-600 text-white px-2 py-1 rounded text-xs"
          >
            Force Refresh
          </button>
        </div>
      </div>
    );
  };

  // Add a handler for comment close that updates the comment count
  const handleCommentClose = (newCommentCount = 0) => {
    // If we have new comments and a post ID to update
    if (newCommentCount > 0 && CommentPostId) {
      // Update posts array
      setUserPosts(prevPosts => 
        prevPosts.map(post => 
          post.id === CommentPostId 
            ? { ...post, comments: (post.comments || 0) + newCommentCount } 
            : post
        )
      );
      
      // Also update shorts array if it exists
      if (userShorts) {
        setUserShorts(prevShorts => 
          prevShorts.map(short => 
            short.id === CommentPostId 
              ? { ...short, comments: (short.comments || 0) + newCommentCount } 
              : short
          )
        );
      }
    }
    
    dispatch(setIsCommentOpen(false));
  };


  return (
    <div className="min-h-screen max-w-[700px] mx-auto bg-[#0a0a0a] text-white font-sans" ref={pageRef}>
     
      {showCacheMessage && <CachedDataMessage />}
      <DebugPanel />
      
      <section id="theprofileinfo">
        <div className="w-full  mx-auto ">
          {/* Cover Image */}
          <div className="relative h-48 max-md:h-36 w-full">
            <img
              src={
                userProfile.coverImage 
                  ? `${cloud}/cloudofscubiee/coverImages/${userProfile.coverImage}`
                  : DefaultCover
              }
              className="object-cover h-48 max-md:h-36 w-full rounded-b-lg"
              loading="lazy"
            />
          </div>

          <div className="flex">
            {/* Left half */}
            <div id="lefthalf" className="w-[50%] max-xl:w-[60%] max-md:w-[100%]">
              {/* Profile picture and info */}
              <div className="relative px-4 sm:px-6 lg:px-8">
                {/* Profile Picture */}
                <div className="absolute rounded-full -top-20 max-md:-top-[60px] left-4 sm:left-6 lg:left-8">
                  <img
                    src={
                      userProfile.profilePicture
                        ? `${cloud}/cloudofscubiee/profilePic/${userProfile.profilePicture}`
                        : DefaultPicture
                    }
                    alt="Profile"
                    loading="lazy"

                    className="w-40 h-40 max-md:h-32 bg-[#d6d6d6] max-md:w-32 object-cover rounded-full border-4 border-white"
                  />
                  <div className="mt-[-60px] ml-36 w-full md:hidden">
                    <h1 className="text-3xl max-md:text-xl font-bold flex items-center gap-2">
                      {userProfile.fullName}{userProfile.verified && <RiVerifiedBadgeFill className="text-blue-500 h-5 w-5"/>}
                    </h1>
                    <p className="text-gray-300 text-sm">@{userProfile.username}</p>
                  </div>
                </div>

                {/* User Info and Actions */}
                <div className="pt-24 max-md:mt-0 pb-6">
                  <div className="flex justify-between items-center">
                    <div className="flex md:hidden max-lg:text-[22px] ml-1 mb-2 space-x-10 max-md:mt-[-10px] justify-center text-gray-300 font-semibold">
                      <div className="flex flex-col items-center">
                        <span>{userProfile.posts}</span>
                        <span className="text-[17px] max-md:text-[15px] max-sm:text-sm font-regular">Posts</span>
                      </div>
                      <div 
                        className="flex flex-col items-center cursor-pointer hover:opacity-80"
                        onClick={() => handleShowFollows('following')}
                      >
                        <span>{userProfile.following}</span>
                        <span className="text-[17px] max-md:text-[15px] max-sm:text-sm font-regular">Following</span>
                      </div>
                      <div 
                        className="flex flex-col items-center cursor-pointer hover:opacity-80"
                        onClick={() => handleShowFollows('followers')}
                      >
                        <span>{userProfile.followers}</span>
                        <span className="text-[17px] max-md:text-[15px] max-sm:text-sm font-regular">Followers</span>
                      </div>
                    </div>
                    <div className="max-md:hidden">
                      <h1 className="text-3xl max-md:text-xl font-bold flex items-center gap-2">
                        {userProfile.fullName}
                        {userProfile.verified && <RiVerifiedBadgeFill className="text-blue-500 h-[25px] w-[25px]"/>}                      </h1>
                      <p className="text-gray-300 text-[15px]">@{userProfile.username}</p>
                    </div>
                  </div>

                  {/* Tags/Badges */}
                  <div className="mt-3 mb-3 tags ">
                    {userProfile.badges && Array.isArray(userProfile.badges) ? (
                      userProfile.badges.map((badge, index) => (
                        <span key={index} className="rainbow-tag">
                          {badge}
                        </span>
                      ))
                    ) : userProfile.badges && typeof userProfile.badges === 'object' ? (
                      Object.keys(userProfile.badges).map((badge) => (
                        <span key={badge} className="rainbow-tag">
                          {badge}
                        </span>
                      ))
                    ) : null}
                  </div>

                  {/* Bio */}
                  {userProfile.bio && (
                    <p className="mt-4 max-md:mt-1 w-[200%] md:text-[16px] text-[15px] font-medium max-md:mr-4 max-md:w-[160%] max-500:w-[155%] max-md:pr-8 text-gray-300 font-sans">
                      {userProfile.bio}
                    </p>
                  )}
                  
                  <div className="flex space-x-4 mt-6 max-md:mt-3 max-md:w-full">
                    {userProfile.socialLinks?.instagram && (
                      <a
                        href={userProfile.socialLinks.instagram}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-gray-600 hover:text-gray-900 transition-colors"
                      >
                        <Instagram size={23} />
                      </a>
                    )}
                    {userProfile.socialLinks?.facebook && (
                      <a
                        href={userProfile.socialLinks.facebook}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-gray-600 hover:text-gray-900 transition-colors"
                      >
                        <Facebook size={24} />
                      </a>
                    )}
                    {userProfile.socialLinks?.twitter && (
                      <a
                        href={userProfile.socialLinks.twitter}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-gray-600 hover:text-gray-900 transition-colors"
                      >
                        <Twitter size={24} />
                      </a>
                    )}
                    {userProfile.socialLinks?.youtube && (
                      <a
                        href={userProfile.socialLinks.youtube}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-gray-600 hover:text-gray-900 transition-colors"
                      >
                        <Youtube size={29} className="mt-[-2px]" />
                      </a>
                    )}
                    <button
                      onClick={() => navigate("/edit-profile")}
                      className=" px-4 py-1 bg-white font-medium text-[15px] text-black rounded-full hover:bg-zinc-300"
                    >
                      Edit Profile
                    </button>
                  </div>
                </div>
              </div>
            </div>

            {/* Right half */}
            <div id="righthalf" className="space-y-4 w-[50%] h-full max-md:mt-4 mt-10 pr-2">
              {/* Stats */}
              <div className="flex justify-end lg:font-bold w-full max-md:hidden space-x-8 max-md:pr-10 max-md:mt-[-350px] mb-1 max-md:text-xl text-[30px] max-lg:text-[24px] text-gray-300 font-semibold">
                <div className="flex flex-col items-center">
                  <span>{userProfile.posts}</span>
                  <span className="text-[16px] max-md:text-[15px] max-sm:text-sm font-medium">Posts</span>
                </div>
                <div 
                  className="flex flex-col items-center cursor-pointer hover:opacity-80 transition"
                  onClick={() => handleShowFollows('following')}
                >
                  <span>{userProfile.following}</span>
                  <span className="text-[16px] max-md:text-[15px] max-sm:text-sm font-medium">Following</span>
                </div>
                <div 
                  className="flex flex-col items-center cursor-pointer hover:opacity-80 transition"
                  onClick={() => handleShowFollows('followers')}
                >
                  <span>{userProfile.followers}</span>
                  <span className="text-[16px] max-md:text-[15px] max-sm:text-sm font-medium">Followers</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Tabs Section */}
      <div className=" w-full flex flex-col items-center">
        <div className="w-full max-w-[700px]">
          <div className="flex text-center">
            <div 
              className={`w-1/2 cursor-pointer py-3 relative ${!activeTab ? "after:absolute after:bottom-0 after:left-0 after:right-0 after:mx-auto after:w-[40%] after:h-[3px] after:bg-white" : ""}`}
              onClick={() => handleTabChange(false)}
            >
              <span className={`font-medium text-[16px] ${!activeTab ? "text-white" : "text-gray-400"}`}>
                Posts
              </span>
            </div>
            <div 
              className={`w-1/2 cursor-pointer py-3 relative ${activeTab ? "after:absolute after:bottom-0 after:left-0 after:right-0 after:mx-auto after:w-[40%] after:h-[3px] after:bg-white" : ""}`}
              onClick={() => handleTabChange(true)}
            >
              <span className={`font-medium text-[16px] ${activeTab ? "text-white" : "text-gray-400"}`}>
                Shorts
              </span>
            </div>
          </div>
          <div className="w-full max-w-[660px] h-[1px] bg-gray-700/50 mt-[-1px] mx-auto"></div>        </div>

        {/* Content Area */}
        <div className="space-y-2 md:mt-8 md:space-y-3 w-full my-4 mb-16 max-w-[640px]">
          {/* Show loading skeletons only for the active tab's content and ONLY when that content is actually loading */}
          {activeTab ? (
            // SHORTS TAB
            shortsLoading || shortsContentLoading ? (
              <SkeletonTheme baseColor="#202020" highlightColor="#444">
                <ShortsLoadingSkeleton />
              </SkeletonTheme>
            ) : Array.isArray(userShorts) && userShorts.length > 0 ? (
              // Shorts tab content when we have shorts
              userShorts.map((post, index) => (
                <article 
                key={post.id}
                ref={index === userShorts.length - 1 ? lastElementRef : null}
                className="relative flex justify-center bg-[#111111] 
                w-full max-w-sm mx-auto h-[90vh] md:max-h-[650px] border-[1px] border-gray-800 
                bg-card rounded-xl overflow-hidden"
            >
                  {/* Content container */}
                  <div className="w-full h-full relative flex flex-col">
                    {/* Media Section - Top 40% */}
                    <div className="w-[100%]  rounded-2xl h-[50%] relative">
                      {post.media && post.media.length > 0 ? (
                        <ShortMediaCarousel
                          media={post.media}
                          postId={post.id}
                          currentIndex={shortMediaIndexes[post.id] || 0}
                          autoPlay={false}
                          isRedux={true}
                          onIndexChange={handleCarouselIndexChange}
                          api={api}
                          videoRef={(el) => {
                            if (el) {
                              const videoKey = `short-${post.id}`;
                              registerVideo(videoKey, el);
                            }
                          }}
                          onVideoPlay={(videoElement) => {
                            // Only play/pause on user click, never show controls
                            const videoKey = `short-${post.id}`;
                            handleUserInteraction(videoKey);
                            
                            // Pause all other videos when this one plays
                            const allVideos = document.querySelectorAll('video');
                            allVideos.forEach(video => {
                              if (video !== videoElement && !video.paused) {
                                video.pause();
                                const container = video.closest('.video-container');
                                if (container && container.dataset.videoId) {
                                  setPlayingVideos(prev => ({ ...prev, [container.dataset.videoId]: false }));
                                }
                              }
                            });
                            
                            setManuallyPaused(videoKey, false);
                            setPlayingVideos(prev => ({ ...prev, [videoKey]: true }));
                          }}
                          onVideoPause={(videoElement) => {
                            const videoKey = `short-${post.id}`;
                            if (videoKey === mostVisibleVideo) {
                              setManuallyPaused(videoKey, true);
                            }
                            setPlayingVideos(prev => ({ ...prev, [videoKey]: false }));
                          }}
                          isMuted={globalMuted}
                          onVolumeChange={(e) => handleVideoVolumeChange(e, `short-${post.id}`)}
                          videoProps={{
                            controls: false, // Always hide controls
                            playsInline: true, // Always plays inline
                            preload: 'metadata',
                            loop: true,
                            style: { background: '#000' }
                          }}
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center bg-gray-900 rounded-2xl">
                          <p className="text-gray-500">No media available</p>
                        </div>
                      )}
                    </div>

                    {/* Content area - Bottom 60% */}
                    <div className="absolute top-[52%] left-0 w-full h-[46%] flex flex-col">
                      {/* Text Content - Make sure it doesn't overlap bottom section */}
                      <div className="relative font-medium flex-1 px-3 pr-11 text-gray-300 pb-16 overflow-y-scroll hide-scrollbar">
                        <p className="max-md mt-1">
                          {post.content}
                        </p>
                      </div>

                      {/* User Info - Fixed position at bottom */}
                      <div className="flex bg-[#111111]  w-full absolute bottom-0 left-0 items-center justify-between px-4 pt-2 ">
                        <div className="flex items-center">
                          <img
                            src={userProfile.profilePicture
                              ? `${cloud}/cloudofscubiee/profilePic/${userProfile.profilePicture}`
                              : DefaultPicture}
                            alt={userProfile.username}
                            className="w-9 h-9 bg-gray-300 rounded-full mr-3 object-cover"
                          />
                          <div>
                            <div className="flex items-center gap-1">
                              <h3 className="text-[15px] before: font-semibold">
                                {userProfile.username}
                              </h3>
                              {userProfile.verified && (
                                <RiVerifiedBadgeFill className="text-blue-500 h-[14px] w-[14px]" />
                              )}
                            </div>
                            <span className="text-xs mt-[-6px] text-gray-400">
                              {new Date(post.createdAt).toLocaleDateString()}
                            </span>
                          </div>
                        </div>
                      </div>
                      {/* Action buttons - Right side */}
                      <div className="absolute h-fit right-3 bottom-3 flex flex-col items-center space-y-7 ">                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleLikeToggle(post.id, e);
                          }}
                          className="hover:text-gray-300 border border-gray-600 hover:border-gray-500 transition-colors py-2 px-[5px] rounded-full"
                          data-like-button={post.id}
                        >
                          <BiUpvote className='text-white empty-heart' size={20} 
                            style={{
                              display: (() => {
                                const postId = post.id?.toString();
                                
                                if (postId && postId in visualState.current.likedPosts) {
                                  return visualState.current.likedPosts[postId] ? 'none' : 'block';
                                }
                                
                                return likedPosts[post.id] ? 'none' : 'block';
                              })()
                            }} />
                          <BiSolidUpvote className='text-gray-200 filled-heart' size={20} 
                            style={{
                              display: (() => {
                                const postId = post.id?.toString();
                                
                                if (postId && postId in visualState.current.likedPosts) {
                                  return visualState.current.likedPosts[postId] ? 'block' : 'none';
                                }
                                
                                return likedPosts[post.id] ? 'block' : 'none';
                              })()
                            }} />
                          <span className="text-sm block mt-1 text-center">
                            {(() => {
                              const postId = post.id?.toString();
                              const originalCount = post?.likes || 0;
                                
                              if (postId && postId in visualState.current.likedPosts) {
                                const originalLiked = likedPosts[post.id] || false;
                                
                                const visualDelta = visualState.current.likedPosts[postId] !== originalLiked
                                  ? (visualState.current.likedPosts[postId] ? 1 : -1)
                                  : 0;
                                
                                return Math.max(0, originalCount + visualDelta).toString();
                              }
                              
                              return originalCount.toString();
                            })()}
                          </span>
                        </button>
                        
                        <button 
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCommentClick(post.id, e);
                          }} 
                          className="text-white hover:text-gray-300"
                        >
                          <TfiCommentAlt size={20} />
                          <span className="text-sm block mt-1 text-center">
                            {(post.comments > 0) ? post.comments : '0'}
                          </span>
                        </button>
                        
                        <button 
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSharePost(post.id, e);
                          }} 
                          className="text-white hover:text-gray-300"
                        >
                          <BsSend size={20} />
                        </button>
                        
                        <button 
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggleMenu(post.id, e);
                          }} 
                          className="text-white hover:text-gray-300"
                          data-more-button="true"
                        >
                          <FiMoreVertical size={20} />
                        </button>
                      </div>

                      {/* Add the bottom sheet for more options */}
                      {activeMenu === post.id && (
                        <div 
                          ref={bottomSheetRef}
                          className="absolute z-50 h-[110px] bg-[#111111] border-t-2 border-gray-700 rounded-t-2xl w-full bottom-0 transform transition-transform duration-300 ease-in-out animate-slide-up menu-container"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="h-full w-full p-4 flex items-center justify-center space-x-20">
                            <div className="flex flex-col items-center">
                              <button 
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePost(post.id, e);
                                }} 
                                className="text-red-700 border-[1px] p-2 rounded-full border-gray-700 hover:scale-105 mb-1"
                                title="Delete"
                              >
                                <RiDeleteBin6Line size={24} />
                              </button>
                              <span className="text-gray-300 text-xs font-sans">Delete</span>
                            </div>

                            <div className="flex flex-col items-center">
                              <button 
                                className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
                                onClick={(e) => handleSaveToggle(post.id, e)}
                                data-save-button={post.id}
                              >
                                <div className="p-1.5 rounded-full">
                                  <BsBookmark 
                                    className="h-[18px] w-[18px] transition-colors duration-200 empty-bookmark" 
                                    style={{
                                      display: (() => {
                                        const postId = post.id?.toString();
                                        if (postId && postId in visualState.current.savedPosts) {
                                          return visualState.current.savedPosts[postId] ? 'none' : 'block';
                                        }
                                        return savedPosts[post.id] ? 'none' : 'block';
                                      })()
                                    }} 
                                  />
                                  <BsBookmarkFill 
                                    className="h-[18px] w-[18px] text-white group-hover:text-gray-200 transition-colors duration-200 filled-bookmark" 
                                    style={{
                                      display: (() => {
                                        const postId = post.id?.toString();
                                        if (postId && postId in visualState.current.savedPosts) {
                                          return visualState.current.savedPosts[postId] ? 'block' : 'none';
                                        }
                                        return savedPosts[post.id] ? 'block' : 'none';
                                      })()
                                    }} 
                                  />
                                </div>
                              </button>
                              <span className="text-gray-300 text-xs">Save</span>
                            </div>

                            <div className="flex flex-col items-center">
                              <button 
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleCopyLink(post.id);
                                }} 
                                className="text-white border-[1px] p-3 rounded-full border-gray-700 hover:scale-105 mb-1" 
                                title="Copy Link"
                              >
                                <MdOutlineContentCopy size={24} />
                              </button>
                              <span className="text-gray-300 text-xs">Copy</span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </article>
              ))
            ) : (
              // No shorts found - show this for both empty array and null cases that aren't loading
              <div className="text-center py-10">
                <p className="text-gray-400">No shorts found.</p>
              </div>
            )
          ) : (
            // POSTS TAB
            postsLoading ? (
              <SkeletonTheme baseColor="#202020" highlightColor="#444">
                <ContentLoadingSkeleton />
              </SkeletonTheme>
            ) : userPosts.length > 0 ? (
              // Posts tab content when we have posts
              userPosts.map((post, index) => (
                <article
                  key={post.id}
                  ref={index === userPosts.length - 1 ? lastElementRef : null}
                  className="overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818]  bg-[#0a0a0a] md:bg-[#0c0c0c]  backdrop-blur-sm py-2 max-md:py-2 max-md:px-[0px] text-gray-300"
                >
                  {/* Post Header */}
                  <div className="flex items-center justify-between mb-3 px-3 max-md:px-2">
                    <div className="flex items-center gap-3 max-md:ml-[6px] pt-1 md:pt-2">
                      <div className="relative h-10 w-10 max-md:h-[36px] max-md:w-[36px] rounded-full overflow-hidden group cursor-pointer">
                        <img
                          src={userProfile.profilePicture
                            ? `${cloud}/cloudofscubiee/profilePic/${userProfile.profilePicture}`
                          : DefaultPicture}
                          alt={userProfile.username}
                          className="w-full h-full bg-gray-300 object-cover transition-transform duration-200 group-hover:scale-110"
                        />
                        <div className="absolute inset-0 bg-black/10 group-hover:bg-black/0 transition-colors duration-200"></div>
                      </div>
                      <div>
                        <div className="flex items-center gap-1">
                          <h3 className="mt-[-4px] text-[15px] max-md:text-[14px] font-semibold font-sans">
                            {userProfile.username}
                          </h3>
                          {userProfile.verified && (
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
                        className="text-gray-400 hover:text-white p-1 rounded-full hover:bg-gray-800/30 transition-colors duration-200" 
                        onClick={(e) => handleToggleMenu(post.id, e)}
                      >
                        <FiMoreVertical className="h-[19px] w-[19px]" />
                      </button>
                      
                      {activeMenu === post.id && (
                        <Portal>
                          <div 
                            className="fixed w-48  font-medium bg-[#0f0f0f] border border-gray-700 rounded-md shadow-lg z-[1000] menu-container"
                            style={{
                              top: `${menuPosition.top}px`,
                              left: `${menuPosition.left}px`,
                              maxHeight: '90vh',
                            }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ul className="py-1 text-gray-200">
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-500"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeletePost(post.id, e);
                                }}
                              >
                                Delete Post
                              </li>
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  copyToClipboard(`${window.location.origin}/viewpost/${post.id}`);
                                }}
                              >
                                Copy Link
                              </li>
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                                onClick={(e) => handleCancelMenu(e)}
                              >
                                Cancel
                              </li>
                            </ul>
                          </div>
                        </Portal>
                      )}
                    </div>
                  </div>

                  {/* Post Content - Clicking on it shows the post details */}
                  <div 
                    className="pr-4 pl-4 max-md:px-0 cursor-pointer"
                  >
                    {/* Text Content */}                    {(post.title || post.content || post.description) && (
                       <div className="mb-[10px] max-md:ml-2 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2">
                        <SmartTruncateText
                          text={post.title || post.content || post.description}
                          className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-medium"
                        />
                      </div>
                    )}

                    {/* Media Content - Updated to match Home.jsx implementation */}
                    {post.media && post.media.length > 0 && (
                      <div className="relative mb-4 max-md:mb-0 xl:w-[84%] md:w-[90%] mx-auto w-full">                        {/* Single media item - full width for both mobile and desktop */}
                        {post.media.length === 1 ? (                          <div className="relative mb-4">
                            <div className="max-md:w-[93%] max-md:mx-auto w-[100%] mx-auto" style={{ maxHeight: '550px' }}>
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
                                </div>                              ) : (                                <img 
                                  src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                                  alt="Post media" 
                                  loading="lazy"
                                  className="max-md:w-[100%] max-md:mx-auto max-md:rounded-lg w-full h-auto object-cover md:rounded-lg cursor-pointer max-h-[550px]"
                                  onClick={(e) => handleImageClick(e, post.media[0], post, 0)}
                                />
                              )}
                            </div>
                          </div>
                        ) : (
                          // Multiple media - use updated HorizontalImageScroll component
                          <HorizontalImageScroll 
                            imageFiles={post.media}
                            post={post}
                            handleImageClick={handleImageClick}
                            cloud={cloud}
                            registerVideo={registerVideo}
                            handleVideoClick={handleVideoClick}
                            videoOverlays={videoOverlays}
                          />
                        )}
                      </div>
                    )}
                  </div>                  {/* Post Actions */}
                    <div className="flex items-center md:w-[84%] xl:w-[78%] md:pl-[1px] md:mx-auto max-md:mr-[8px] max-md:ml-2 max-md:px-2 mb-3 max-md:mb-1 mt-1">                      {/* Upvote Button - Reddit/Daily.dev style */}
                    {/* Like Button */}
                    <button 
                      className={`flex items-center gap-1 px-3 py-[4px] rounded-full border transition-all duration-200 transform hover:scale-105 ${
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
                            
                            if (postId && postId in visualState.current.likedPosts) {
                              return visualState.current.likedPosts[postId] ? 'none' : 'block';
                            }
                            
                            return likedPosts[post.id] ? 'none' : 'block';
                          })()
                        }} 
                      />
                      <BiSolidUpvote 
                        className="h-4 w-4 text-gray-200 filled-heart" 
                        style={{
                          display: (() => {
                            const postId = post.id?.toString();
                            
                            if (postId && postId in visualState.current.likedPosts) {
                              return visualState.current.likedPosts[postId] ? 'block' : 'none';
                            }
                            
                            return likedPosts[post.id] ? 'block' : 'none';
                          })()
                        }} 
                      />                      <span className='text-sm font-medium'>
                        {(() => {
                          const postId = post.id?.toString();
                          const originalCount = post?.likes || 0;
                            
                          if (postId && postId in visualState.current.likedPosts) {
                            const originalLiked = likedPosts[post.id] || false;
                            
                            const visualDelta = visualState.current.likedPosts[postId] !== originalLiked
                              ? (visualState.current.likedPosts[postId] ? 1 : -1)
                              : 0;
                            
                            return Math.max(0, originalCount + visualDelta).toLocaleString();
                          }
                          
                          return originalCount.toLocaleString() || '0';
                        })()}
                      </span>
                    </button>

                    {/* Comment Button */}
                    <button 
                      className="flex items-center gap-2 text-gray-300 ml-6 group"
                      onClick={(e) => handleCommentClick(post.id, e)}
                    >
                      <div className="p-1.2 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                        <TfiCommentAlt className="mt-[1px] h-[18px] w-[18px] transition-colors duration-200" />
                      </div>
                      <span className='text-[14px] mt-[-1px] transition-colors duration-200'>
                        {(post.comments > 0) ? post.comments : '0'}
                      </span>
                    </button>

                    {/* Share Button */}
                    <button 
                      className="flex items-center text-gray-300 ml-auto group"
                      onClick={(e) => handleSharePost(post.id, e)}
                    >
                      <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                        <BsSend className="h-[18px] w-[18px] transition-colors duration-200" />
                      </div>
                    </button>

                    {/* Save Button */}
                    <button 
                      className="flex items-center text-gray-300 ml-6 group"
                      onClick={(e) => handleSaveToggle(post.id, e)}
                      data-save-button={post.id}
                    >
                      <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                        <BsBookmark 
                          className="h-[18px] w-[18px] transition-colors duration-200 empty-bookmark" 
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
                          className="h-[18px] w-[18px] text-white group-hover:text-gray-200 transition-colors duration-200 filled-bookmark" 
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
              ))
            ) : (
              // No posts found
              <div className="text-center py-10">
                <p className="text-gray-400">No posts found.</p>
              </div>
            )
          )}
          
          {/* Load more indicator - only shown when actively loading more content */}
          {loadingMore && (
            <div className="py-8 w-full text-center">
              <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]">
                <span className="!absolute !-m-px !h-px !w-px !overflow-hidden !whitespace-nowrap !border-0 !p-0 ![clip:rect(0,0,0,0)]">
                  Loading more...
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Overlay */}
      {(showOptions || selectedPost) && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-40"></div>
      )}

      {/* Short Display Widget */}
      {selectedShort && (
        <Share 
          shortId={selectedShort} 
          displayWidget={true}
          onClose={() => setSelectedShort(null)} 
        />
      )}

      {/* Comment Widget */}
      {isCommentOpen && (
        <CommentWidget
          postId={CommentPostId}
          isOpen={isCommentOpen}
          onClose={handleCommentClose}
        />
      )}

      {/* Share Widget */}
      {showShareWidget && (
        <ShareDialog 
          postId={sharePostId}
          onClose={() => setShowShareWidget(false)}
        />
      )}

      {/* Follows Widget */}
      {showFollowsWidget && (
        <FollowsWidget
          isOpen={showFollowsWidget}
          onClose={() => setShowFollowsWidget(false)}
          userId={userProfile.id}
          username={userProfile.username}
          initialTab={followsWidgetType}
        />
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
              className="max-h-[85vh] min-w-[98vw] object-contain"
            />
            
            {/* Always show navigation arrows if there are multiple images */}
            {viewingImage.postMedia && viewingImage.postMedia.filter(media => media.type !== 'video').length > 1 && (
              <>
                <button 
                  className="absolute max-md:hidden md:left-[-50px] left-2 top-1/2 transform -translate-y-1/2 bg-white/10 md:p-2 p-1 rounded-full z-10"
                  onClick={(e) => navigateImages(e, -1, viewingImage.postMedia)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="md:h-6  md:w-6 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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

      {/* Deleting Overlay */}
      {isDeleting && (
        <div className="fixed inset-0 z-[60] bg-black bg-opacity-60 flex items-center justify-center">
          <div className="bg-black bg-opacity-80 rounded-lg px-4 py-2 flex items-center">
            <span className="text-white mr-2">Deleting</span>
            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
          </div>
        </div>
      )}

      {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
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

      <div 
        className={`fixed inset-0 bg-black/60 backdrop-blur-sm z-40 transition-opacity duration-300 
                   ${showMenu ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={() => setShowMenu(false)}
      ></div>
        {/* Menu Trigger Button and Message Icon */}
      <div className="fixed top-5 right-5 max-md:top-3 max-md:right-3 z-30 flex space-x-3">
        {/* Message Icon */}
        <div 
          className="cursor-pointer"
          onClick={() => navigate('/chat')}
        >
          <div className="relative p-2 rounded-full bg-black/20 backdrop-blur-md border border-white/10 shadow-lg hover:bg-black/30 transition-all duration-200">
            <FiMessageCircle className="text-2xl text-white" />
            {chatDataLoaded && !isInitialRender && validatedUnreadCount > 0 && (
              <div className="absolute top-[-2px] right-[-2px] bg-red-500 text-white font-semibold text-xs rounded-full h-[18px] w-[18px] flex items-center justify-center">
                {validatedUnreadCount > 9 ? '9+' : validatedUnreadCount}
              </div>
            )}
          </div>
        </div>

        {/* Menu Button */}
        <button
          className="p-2 rounded-full bg-black/20 backdrop-blur-md border border-white/10 shadow-lg hover:bg-black/30 transition-all duration-200"
          onClick={() => setShowMenu(true)}
          aria-label="Open menu"
        >
          <MdMenu className="text-2xl text-white" />
        </button>
      </div>
      
      <div 
        className={`fixed top-0 right-0 h-full w-[290px]  max-md:w-[270px] bg-gradient-to-b from-[#111] to-[#080808] shadow-[-5px_0px_25px_rgba(0,0,0,0.6)] 
                   transform transition-all duration-400 ease-out z-50
                   ${showMenu ? 'translate-x-0' : 'translate-x-full'}`}
      >
        {/* Header with subtle gradient underline */}
        <div className="relative p-6 mb-1">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-white">Menu</h2>
            <button
              className="p-1.5 rounded-full hover:bg-white/15 active:scale-95 transition-all duration-200"
              onClick={() => setShowMenu(false)}
              aria-label="Close menu"
            >
              <MdClose className="text-2xl text-gray-200" />
            </button>
          </div>
          <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-gray-500/30 to-transparent"></div>
        </div>
        
        {/* User Profile Section with monochrome styling */}
        <div className="px-6 py-5">
          <div className="flex items-center space-x-3.5">
            <div className="h-14 w-14 rounded-full overflow-hidden ring-2 ring-white/10 ring-offset-1 ring-offset-gray-900 shadow-lg">
              <img 
                src={userProfile?.profilePicture 
                  ? `${cloud}/cloudofscubiee/profilePic/${userProfile.profilePicture}`
                  : DefaultPicture}
                alt="Profile"
                className="h-full w-full bg-slate-300 object-cover"
              />
            </div>
            <div>
              <h3 className="font-medium text-white text-lg">{userProfile?.fullName || 'User'}</h3>
              <p className="text-sm text-gray-400">@{userProfile?.username || 'username'}</p>
            </div>
          </div>
        </div>
        
        {/* Divider with subtle gradient */}
        <div className="h-px w-full bg-gradient-to-r from-transparent via-gray-700/40 to-transparent my-2"></div>
        
        {/* Menu Items with professional monochrome styling */}
        <div className="py-3 max-md:py-1 px-3">
          <nav className="space-y-[8px] md:space-y-[4px] text-[17px] max-md:text-[16px]">
            <a href="/posts/liked" className="group flex items-center text-gray-200 px-4 py-2 rounded-lg hover:bg-white/8 active:bg-white/10 transition-all duration-200">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/8 mr-3.5 group-hover:bg-white/12 transition-colors duration-200">
                <IoMdHeartEmpty className="text-white text-[21.5px] md:text-[24.5px]" />
              </div>
              <span className="font-medium">Liked Posts</span>
            </a>
            
            <a href="/posts/saved" className="group flex items-center text-gray-200 px-4 py-2 rounded-lg hover:bg-white/8 active:bg-white/10 transition-all duration-200">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/8 mr-3.5 group-hover:bg-white/12 transition-colors duration-200">
                <BsBookmark className="text-white text-[17px] md:text-[19px]" />
              </div>
              <span className="font-medium">Saved Posts</span>
            </a>
            
            <a href="/help-support" className="group flex items-center text-gray-200 px-4 py-2 rounded-lg hover:bg-white/8 active:bg-white/10 transition-all duration-200">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/8 mr-3.5 group-hover:bg-white/12 transition-colors duration-200">
                <MdOutlineHelpOutline className="text-white text-[21px] md:text-[24px]" />
              </div>
              <span className="font-medium">Help & Support</span>
            </a>
            
            <a href="/privacy-policy" className="group flex items-center text-gray-200 px-4 py-2 rounded-lg hover:bg-white/8 active:bg-white/10 transition-all duration-200">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/8 mr-3.5 group-hover:bg-white/12 transition-colors duration-200">
                <MdOutlinePrivacyTip className="text-white text-[21px] md:text-[24px]" />
              </div>
              <span className="font-medium">Privacy Policy</span>
            </a>
            
            <a href="/terms" className="group flex items-center text-gray-200 px-4 py-2 rounded-lg hover:bg-white/8 active:bg-white/10 transition-all duration-200">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/8 mr-3.5 group-hover:bg-white/12 transition-colors duration-200">
                <MdOutlineGavel className="text-white text-[21px] md:text-[24px]" />
              </div>
              <span className="font-medium">Terms of Service</span>
            </a>
            <a href="/about-us" className="group flex items-center text-gray-200 px-4 py-2 rounded-lg hover:bg-white/8 active:bg-white/10 transition-all duration-200">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-white/8 mr-3.5 group-hover:bg-white/12 transition-colors duration-200">
                <GrCircleInformation className="text-white text-[19.5px] md:text-[22.5px]" />
              </div>
              <span className="font-medium">About Us</span>
            </a>
          </nav>
        </div>
        
        {/* Footer Actions with subtle top border */}
        <div className="absolute bottom-0 left-0 right-0 p-5 border-t border-white/10 bg-black/20 backdrop-blur-sm">
          <button 
            className="flex items-center justify-center w-full px-5 py-3.5 text-red-400 bg-gradient-to-r from-red-950/30 to-red-900/20 rounded-xl hover:from-red-900/40 hover:to-red-800/30 active:scale-[0.98] transition-all duration-200"
            onClick={handleLogout}
            disabled={isLoggingOut}
          >
            {isLoggingOut ? (
              <>
                <div className="h-5 w-5 border-2 border-red-400 border-t-transparent rounded-full animate-spin mr-3"></div>
                <span className="font-medium">Logging out...</span>
              </>
            ) : (
              <>
                <MdLogout className="text-xl mr-3" />
                <span className="font-medium">Log Out</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default MyProfile;