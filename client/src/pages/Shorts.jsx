import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { BiUpvote, BiSolidUpvote } from 'react-icons/bi';
import { TfiCommentAlt } from 'react-icons/tfi';
import { BsSend, BsBookmarkFill, BsBookmark } from 'react-icons/bs';
import { FiMoreVertical } from 'react-icons/fi';
import { FaPlay, FaArrowUp, FaArrowDown } from "react-icons/fa";
import { MdRefresh, MdOutlineDeleteOutline } from "react-icons/md";
import './Short.css';
import { useDispatch, useSelector } from 'react-redux';
import { MdOutlineReport } from "react-icons/md";
import { MdOutlineContentCopy } from "react-icons/md";
import { RiDeleteBin6Line } from "react-icons/ri";
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import { fetchShortsFeed, fetchMoreShorts, setCurrentShortIndex, updateShortInteraction, deleteShort, checkForNewShorts, toggleLikePost, setOnlineStatus } from '../Slices/ShortsSlice';
import { toast } from 'react-toastify';
import ShareDialog from "../components/shareWidget";
import CommentWidget from '../components/CommentWidget';
import ReportWidget from '../components/ReportWidget';
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom';
import ShortMediaCarousel from '../components/ShortMediaCarousel';
import { useInteractionManager } from '../hooks';
import { useMediaCache, RECENT_SHORTS_WINDOW } from '../context/MediaCacheContext';
import ErrorBoundary from '../components/ErrorBoundary';
import { createPortal } from 'react-dom';
const vcloud = import.meta.env.VITE_VIDEO_CLOUD_URL;

const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted ? createPortal(children, document.body) : null;
};
// Video Player Component
function VideoPlayer({ src }) {
  const videoRef = useRef(null);
  const [isPaused, setIsPaused] = useState(false);
  const [progress, setProgress] = useState(0);

  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play();
      setIsPaused(false);
    } else {
      video.pause();
      setIsPaused(true);
    }
  };

  const handleTimeUpdate = () => {
    const video = videoRef.current;
    if (video && video.duration) {
      setProgress((video.currentTime / video.duration) * 100);
    }
  };

  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.playsInline = true;
      const playPromise = video.play();
      if (playPromise !== undefined) {
        playPromise
          .then(() => {
            setIsPaused(false);
          })
          .catch(error => {
            setIsPaused(true);
          });
      }
    }
  }, [src]);

  const handleProgressClick = (e) => {
    const video = videoRef.current;
    if (!video || !video.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const newTime = (clickX / rect.width) * video.duration;
    video.currentTime = newTime;
    setProgress((newTime / video.duration) * 100);
  };

  useEffect(() => {
    const video = videoRef.current;
    if (video) {
      video.addEventListener('ended', () => {
        setIsPaused(true);
        setProgress(0);
      });
    }
    return () => {
      if (video) {
        video.removeEventListener('ended', () => {});
      }
    };
  }, []);

  return (
    <div className="relative w-full h-full">
      <video
        ref={videoRef}
        src={src}
        autoPlay
        controlsList="nodownload"
        onClick={togglePlay}
        onTimeUpdate={handleTimeUpdate}
        className="w-full h-full object-cover rounded-t-2xl"
      />
      {isPaused && (
        <button
          onClick={togglePlay}
          className="absolute inset-0 flex items-center justify-center bg-black bg-opacity-50 text-gray-300"
        >
          <FaPlay size={40} />
        </button>
      )}
      <div
        className="absolute bottom-0 left-0 right-0 h-[2px] bg-gray-400 cursor-pointer"
        onClick={handleProgressClick}
      >
        <div className="bg-white h-full" style={{ width: `${progress}%` }}></div>
      </div>
    </div>
  );
}

function isRunningAsPWA() {
  // Standard PWA detection
  const isPWAStandard = window.matchMedia('(display-mode: standalone)').matches || 
                        window.navigator.standalone;
  
  // TWA detection (Android app)
  const userAgent = navigator.userAgent.toLowerCase();
  const isTWA = userAgent.includes('android') && 
                !userAgent.includes('chrome/') && 
                document.referrer === '';
  
  // URL bar absence detection - check if window.innerHeight is close to screen.height
  // This helps detect both PWA and TWA where URL bar isn't shown
  const heightRatio = window.innerHeight / window.screen.height;
  const isFullScreenLike = heightRatio > 0.9; // URL bar usually takes ~10% of height
  
  return isPWAStandard || isTWA || isFullScreenLike;
}

export default function ShortsWithErrorBoundary(props) {
  const [hasDirectAccessError, setHasDirectAccessError] = useState(false);
  const { shortId } = useParams();
  
  useEffect(() => {
    if (shortId) {
      setHasDirectAccessError(false);
    }
  }, [shortId]);
  
  if (shortId && hasDirectAccessError) {
    return (
      <div className={`flex justify-center h-screen ${containerHeight}  md:items-center  bg-[#0a0a0a]`}>
        <div className="relative flex justify-center aspect-[9/16] md:bg-[#0c0d11] 
                     border-gray-800 md:border-[1px] w-full 500:max-w-sm max-500:max-w-full
                     bg-card md:rounded-3xl overflow-hidden">
          <div className="flex flex-col justify-center items-center h-full w-full bg-[#0c0d11] text-white p-6 md:rounded-t-2xl">
            <div className="mb-4 text-red-500">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <h3 className="text-xl font-bold mb-2">Short Not Available</h3>
            <p className="text-gray-400 text-center mb-6">
              This short may have been removed or is temporarily unavailable.
            </p>
            <Link to="/shorts" className="flex items-center justify-center bg-primary hover:bg-primary/80 text-white py-2 px-4 rounded-lg transition duration-200">
              <MdRefresh className="mr-2" size={20} /> 
              Go to Shorts Feed
            </Link>
          </div>
        </div>
      </div>
    );
  }
  
  return (
    <ErrorBoundary 
      componentName="Shorts" 
      errorMessage="We couldn't load the shorts feed due to a technical issue."
      resetButtonText="Reload Page"
      forceRefresh={true}
    >
      <Shorts {...props} onDirectAccessError={() => setHasDirectAccessError(true)} />
    </ErrorBoundary>
  );
}

function Shorts({ displayWidget = false, onClose, onDirectAccessError }) {
  const location = useLocation();
  const { shortId: paramShortId } = useParams();
  const navigate = useNavigate();
  const dispatch = useDispatch();

  // Add state for notification data
  const [notificationData, setNotificationData] = useState(null);

  const [isInitializing, setIsInitializing] = useState(false);
  const [isDirectAccessMode, setIsDirectAccessMode] = useState(!!paramShortId);
  const [feedInitialized, setFeedInitialized] = useState(false);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [globalTimeout, setGlobalTimeout] = useState(false);
  const [loadingStartTime, setLoadingStartTime] = useState(Date.now());
  const [circuitBroken, setCircuitBroken] = useState(false);
  const [transitionDirection, setTransitionDirection] = useState(null);
  const cloud = import.meta.env.VITE_CLOUD_URL;
  const [mediaLoaded, setMediaLoaded] = useState(false);

  const isFetchingRef = useRef(false);
  const pendingLikeOperations = useRef(new Map()); // Add this ref to track debounced like operations
  const visualState = useRef({  // Add visual state tracking separate from Redux/API
    likedPosts: {}  // Track visual likes separate from Redux
  });
  const hasNavigatedFromDirectAccessRef = useRef(false);
  const renderCountRef = useRef(0);
  const lastRenderTimeRef = useRef(Date.now());
  const consecutiveRapidRendersRef = useRef(0);
  const networkRequestsRef = useRef(new Map());
  const memoryMonitorRef = useRef(null);
  const memoryUsageThreshold = 200; // MB
  const isCommentOpen = useSelector((state) => state.widget.isCommentOpen);
  const { shorts, currentShortIndex, pagination, loading, loadingMore, isOnline } = useSelector((state) => state.shorts);
  const userData = useSelector((state) => state.user.userData);

  const [isPWA, setIsPWA] = useState(isRunningAsPWA());
  const DefaultPicture = "/logos/DefaultPicture.png";
  const bottomSheetRef = useRef(null);
  const shortsContainerRef = useRef(null);
  const containerRef = useRef(null);

  const [isMobile, setIsMobile] = useState(false);
  const [isLargeScreen, setIsLargeScreen] = useState(false);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [currentMediaIndex, setCurrentMediaIndex] = useState(0);

  const [singleShortData, setSingleShortData] = useState(null);
  const [shortInteractions, setShortInteractions] = useState({
    liked: false,
    saved: false,
    likesCount: 0
  });

  const [showReportWidget, setShowReportWidget] = useState(false);
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [reportType, setReportType] = useState(null);
  const [reportTargetId, setReportTargetId] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const api = import.meta.env.VITE_API_URL;
  const viewedShortsRef = useRef(new Set()); // Track which shorts have been viewed in this session

  const currentShort = isDirectAccessMode ? singleShortData : shorts[currentShortIndex] || null;

  const [isContentExpanded, setIsContentExpanded] = useState(false);
  const [isContentOverflowing, setIsContentOverflowing] = useState(false);
  const contentRef = useRef(null);

  const [prefetchedShorts, setPrefetchedShorts] = useState(new Set());
  const prefetchingInProgress = useRef(new Set());

  const processingShorts = useRef(new Set());

  useEffect(() => {
    setMediaLoaded(false);
  }, [currentShort?.id, currentMediaIndex]);

  useEffect(() => {
    let lastTouchY = 0;
    let maybePrevent = false;
  
    function onTouchStart(e) {
      if (e.touches.length !== 1) return;
      lastTouchY = e.touches[0].clientY;
      // Only consider if at the top of the page
      maybePrevent = (window.scrollY === 0 || document.body.scrollTop === 0);
    }
  
    function onTouchMove(e) {
      const touchY = e.touches[0].clientY;
      const deltaY = touchY - lastTouchY;
      lastTouchY = touchY;
  
      // If at top and swiping down, prevent pull-to-refresh
      if (maybePrevent && deltaY > 0) {
        e.preventDefault();
      }
    }
  
    window.addEventListener('touchstart', onTouchStart, { passive: false });
    window.addEventListener('touchmove', onTouchMove, { passive: false });
  
    return () => {
      window.removeEventListener('touchstart', onTouchStart);
      window.removeEventListener('touchmove', onTouchMove);
    };
  }, []);
  
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "IMG" || e.target.tagName === "VIDEO") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  // Add online/offline event listeners to update Redux state
  useEffect(() => {
    const handleOnline = () => {
      console.log('Shorts component is now online');
      dispatch(setOnlineStatus(true));
    };
    
    const handleOffline = () => {
      console.log('Shorts component is now offline');
      dispatch(setOnlineStatus(false));
    };
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [dispatch]);

  const { 
    preloadMedia, 
    getCachedMedia, 
    isMediaCached, 
    markShortAsViewed, 
    getRecentlyViewedShorts,
    getMetrics 
  } = useMediaCache();

  const [visibleShortIds, setVisibleShortIds] = useState(new Set());

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  

  useEffect(() => {
    if (currentShort?.id) {
      markShortAsViewed(currentShort.id);
    }
  }, [currentShort?.id, markShortAsViewed]);

  const prefetchShortMedia = useCallback((short) => {
    if (!short?.id || 
        isMediaCached(short.id) || 
        processingShorts.current.has(short.id)) {
      return;
    }
    
    processingShorts.current.add(short.id);
    
    if (short.media && short.media.length > 0) {
      const mediaItems = short.media.map(mediaItem => {
        const mediaUrl = mediaItem.type === 'video'
          ? `${cloud}/cloudofscubiee/shortVideos/${mediaItem.url}`
          : `${cloud}/cloudofscubiee/shortImages/${mediaItem.url}`;
        
        return {
          ...mediaItem,
          cachedUrl: mediaUrl,
        };
      });
      
      preloadMedia(short.id, mediaItems)
        .then(() => {
          setPrefetchedShorts(prev => new Set([...prev, short.id]));
        })
        .catch(error => {
        })
        .finally(() => {
          processingShorts.current.delete(short.id);
        });
    }
  }, [api, preloadMedia, isMediaCached]);

  const areSetsEqual = useCallback((a, b) => {
    if (!a || !b) return false;
    if (a.size !== b.size) return false;
    for (const item of a) if (!b.has(item)) return false;
    return true;
  }, []);

  const maintainPrefetchWindow = useCallback(() => {
    if (isDirectAccessMode || !shorts || shorts.length === 0) {
      return;
    }
    
    const recentlyViewed = getRecentlyViewedShorts();
    
    const prefetchAhead = 3;
    const prefetchBehind = 2;
    
    const shortsToPrefetch = [];
    
    for (let i = 1; i <= prefetchAhead; i++) {
      const nextIndex = currentShortIndex + i;
      if (nextIndex < shorts.length) {
        const short = shorts[nextIndex];
        if (short && short.id && !isMediaCached(short.id) && !processingShorts.current.has(short.id)) {
          shortsToPrefetch.push({
            short,
            priority: 1,
            direction: 'ahead'
          });
        }
      }
    }
    
    for (let i = 1; i <= prefetchBehind; i++) {
      const prevIndex = currentShortIndex - i;
      if (prevIndex >= 0) {
        const short = shorts[prevIndex];
        if (short && short.id && !isMediaCached(short.id) && !processingShorts.current.has(short.id)) {
          shortsToPrefetch.push({
            short,
            priority: 2,
            direction: 'behind'
          });
        }
      }
    }
    
    shortsToPrefetch.sort((a, b) => a.priority - b.priority);
    
    if (shortsToPrefetch.length > 0) {
    
      
      shortsToPrefetch.forEach(({ short }, index) => {
        setTimeout(() => {
          prefetchShortMedia(short);
        }, index * 150);
      });
    }
    
    const newVisibleIds = new Set();
    
    if (shorts[currentShortIndex]?.id) {
      newVisibleIds.add(shorts[currentShortIndex].id);
    }
    
    if (currentShortIndex > 0 && shorts[currentShortIndex - 1]?.id) {
      newVisibleIds.add(shorts[currentShortIndex - 1].id);
    }
    
    if (currentShortIndex < shorts.length - 1 && shorts[currentShortIndex + 1]?.id) {
      newVisibleIds.add(shorts[currentShortIndex + 1].id);
    }
    
    if (!areSetsEqual(visibleShortIds, newVisibleIds) && newVisibleIds.size > 0) {
      setVisibleShortIds(newVisibleIds);
    }
  }, [
    currentShortIndex, 
    shorts, 
    isDirectAccessMode, 
    prefetchShortMedia, 
    isMediaCached, 
    visibleShortIds, 
    areSetsEqual, 
    getRecentlyViewedShorts
  ]);

  const lastPositionRef = useRef(0);
  
  useEffect(() => {
    if (currentShortIndex !== lastPositionRef.current) {
      const direction = currentShortIndex > lastPositionRef.current ? 'up' : 'down';
      setTransitionDirection(direction);
      
      // Reset animation after it completes
      const timer = setTimeout(() => {
        setTransitionDirection(null);
      }, 600); // Animation duration + a little buffer
      
      lastPositionRef.current = currentShortIndex;
      
      return () => clearTimeout(timer);
    }
  }, [currentShortIndex]);

  const handleLoadMoreShorts = useCallback(() => {
    if (isDirectAccessMode) {
      if (hasNavigatedFromDirectAccessRef.current) {
        return; // Prevent duplicate transitions
      }
      
      hasNavigatedFromDirectAccessRef.current = true;
      setIsDirectAccessMode(false);
  
      if (!feedInitialized && !isFetchingRef.current) {
        isFetchingRef.current = true;
        setError(null);
        
        
        // First, add the current short to viewedShorts to prevent duplicate recording
        if (singleShortData?.id) {
          viewedShortsRef.current.add(singleShortData.id);
          
          // Make sure the short is marked as viewed so backend won't include it again
          markShortAsViewed(singleShortData.id);
          
          // Also explicitly tell the server to record this view
          axios.post(
            `${api}/user-interactions/view/${singleShortData.id}`, 
            {}, 
            { withCredentials: true }
          ).catch(error => console.error(`Error recording view for short ${singleShortData.id}:`, error));
        }
        
        // Fetch feed WITHOUT firstShortId to prevent it appearing in results
        dispatch(fetchShortsFeed())
          .unwrap()
          .then((data) => {
            
            if (!data.shorts || data.shorts.length === 0) {
              setError({
                type: 'empty_feed',
                message: 'Please check your Internet connection and try again.',
              });
              isFetchingRef.current = false;
              return;
            }
            
            // Start at index 0
            dispatch(setCurrentShortIndex(0));
            setFeedInitialized(true);
            setIsInitializing(false);
            isFetchingRef.current = false;
          })
          .catch(error => {
            setError({
              type: 'feed',
              message: error.response?.data?.error || 'Failed to load shorts. Please try again.',
              status: error.response?.status
            });
            // Reset for another attempt
            hasNavigatedFromDirectAccessRef.current = false;
            setIsDirectAccessMode(true);
            setIsInitializing(false);
            isFetchingRef.current = false;
          });
      }
    } else {
      // Rest of the function remains unchanged
      if (pagination.hasMore && !isFetchingRef.current) {
        isFetchingRef.current = true;
        setError(null);
        
        dispatch(fetchMoreShorts(pagination.nextCursor))
          .then(() => {
            isFetchingRef.current = false;
          })
          .catch(error => {
            setError({
              type: 'more_shorts',
              message: error.response?.data?.error || 'Failed to load more shorts. Please try again.',
              status: error.response?.status
            });
            isFetchingRef.current = false;
          });
      }
    }
  }, [isDirectAccessMode, feedInitialized, dispatch, paramShortId, singleShortData?.id, pagination, api, markShortAsViewed]);

  const goToPrevShort = useCallback(() => {
    if (isDirectAccessMode) return;
  
    if (currentShortIndex > 0) {
      setTransitionDirection('down');
      lastPositionRef.current = currentShortIndex;
      dispatch(setCurrentShortIndex(currentShortIndex - 1));
      setCurrentMediaIndex(0);
    } else {
      // Don't animate if we're at the first short
      setTransitionDirection(null);
    }
  }, [currentShortIndex, dispatch, isDirectAccessMode]);
  
  const goToNextShort = useCallback(() => {
    setTransitionDirection('up');
    if (isDirectAccessMode) {
      
      if (!isOnline) {
        setError({
          type: 'offline',
          message: "You're currently offline. Please check your internet connection.",
          status: 'OFFLINE'
        });
        return;
      }
      
      // Make sure to mark the current short as viewed before transition
      if (singleShortData?.id) {
        viewedShortsRef.current.add(singleShortData.id);
        markShortAsViewed(singleShortData.id);
      }
      
      // Prevent UI issues by showing loading state during transition
      setIsInitializing(true);
      
      // Transition with proper error handling
      try {
        handleLoadMoreShorts();
      } catch (error) {
        console.error("Error during transition to feed mode:", error);
        setError({
          type: 'transition',
          message: 'Failed to load shorts feed. Please try again.',
        });
        setIsInitializing(false);
      }
      return;
    }
    
    if (currentShortIndex < shorts.length - 1) {
      setTransitionDirection('up');
      lastPositionRef.current = currentShortIndex;
      dispatch(setCurrentShortIndex(currentShortIndex + 1));
      setCurrentMediaIndex(0);
    } else {
      // Don't animate if we're at the last short
      setTransitionDirection(null);
    }  }, [
    currentShortIndex, 
    shorts.length, 
    dispatch, 
    isDirectAccessMode, 
    pagination, 
    handleLoadMoreShorts,
    shorts,
    singleShortData?.id,
    markShortAsViewed,
    isOnline
  ]);
  useEffect(() => {
    if (loading || loadingMore) return;
    
    maintainPrefetchWindow();
  }, [currentShortIndex, shorts, isDirectAccessMode, loading, loadingMore, maintainPrefetchWindow]);

  useEffect(() => {
    if (!isDirectAccessMode && 
        shorts && 
        shorts.length > 0 && 
        !loadingMore && 
        !loading) {
      
      const initialBatch = [
        shorts[currentShortIndex],
        ...(shorts.slice(currentShortIndex + 1, currentShortIndex + 4) || [])
      ].filter(Boolean);
      
      initialBatch.forEach((short, index) => {
        setTimeout(() => {
          prefetchShortMedia(short);
        }, index * 150);
      });

      const initialVisibleIds = new Set();
      if (shorts[currentShortIndex]?.id) {
        initialVisibleIds.add(shorts[currentShortIndex].id);
      }
      if (currentShortIndex < shorts.length - 1 && shorts[currentShortIndex + 1]?.id) {
        initialVisibleIds.add(shorts[currentShortIndex + 1].id);
      }
      
      if (initialVisibleIds.size > 0 && !areSetsEqual(visibleShortIds, initialVisibleIds)) {
        setVisibleShortIds(initialVisibleIds);
      }
    }
  }, [shorts, isDirectAccessMode, loadingMore, loading, currentShortIndex, prefetchShortMedia, areSetsEqual]);

  useEffect(() => {
    return () => {
      networkRequestsRef.current.forEach((controller, id) => {
        try {
          controller.abort();
        } catch (e) {
        }
      });
      networkRequestsRef.current.clear();
      
      if (memoryMonitorRef.current) {
        clearInterval(memoryMonitorRef.current);
      }
      
      const metrics = getMetrics();
     
    };
  }, [getMetrics]);

  useEffect(() => {
    if (window.performance && window.performance.memory) {
      memoryMonitorRef.current = setInterval(() => {
        const memoryInfo = window.performance.memory;
        const usedJSHeapSize = memoryInfo.usedJSHeapSize / (1024 * 1024);
        
        if (usedJSHeapSize > memoryUsageThreshold) {
  
          setCircuitBroken(true);
          clearInterval(memoryMonitorRef.current);
        }
      }, 5000);
    }
    
    return () => {
      if (memoryMonitorRef.current) {
        clearInterval(memoryMonitorRef.current);
      }
    };
  }, []);

  useEffect(() => {
    renderCountRef.current += 1;
    const now = Date.now();
    const timeSinceLastRender = now - lastRenderTimeRef.current;
    
    if (timeSinceLastRender < 50) {
      consecutiveRapidRendersRef.current += 1;
    } else {
      consecutiveRapidRendersRef.current = 0;
    }
    
    if (consecutiveRapidRendersRef.current > 20) {
      setCircuitBroken(true);
      
      networkRequestsRef.current.forEach((controller, id) => {
        try {
          controller.abort();
        } catch (e) {
        }
      });
      networkRequestsRef.current.clear();
    }
    
    lastRenderTimeRef.current = now;
  });
  const fetchSingleShort = useCallback(async (shortId) => {
    if (isFetchingRef.current) {
      return;
    }
    
    isFetchingRef.current = true;
    
    if (!isOnline) {
      setError({
        type: 'offline',
        message: "You're currently offline. Please check your internet connection.",
        status: 'OFFLINE'
      });
      isFetchingRef.current = false;
      return;
    }
    
    const requestId = `short_${shortId}_${Date.now()}`;
    const controller = new AbortController();
    networkRequestsRef.current.set(requestId, controller);
    
    setLoadingStartTime(Date.now());
    
    try {
      setError(null);
      
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => {
          reject(new Error('TIMEOUT'));
          if (networkRequestsRef.current.has(requestId)) {
            networkRequestsRef.current.get(requestId).abort();
            networkRequestsRef.current.delete(requestId);
          }
        }, 10000);
      });
      
      const fetchPromise = axios.get(`${api}/post/short/details/${shortId}`, {
        withCredentials: true,
        signal: controller.signal,
        timeout: 8000
      });
      
      const response = await Promise.race([fetchPromise, timeoutPromise]);
      
      networkRequestsRef.current.delete(requestId);
      
      if (circuitBroken) {
        isFetchingRef.current = false;
        return;
      }
      
      if (!response.data || !response.data.id) {
        throw new Error('Invalid short data received');
      }
      
      setSingleShortData(response.data);
      setShortInteractions({
        liked: response.data.isLiked || false,
        saved: response.data.isSaved || false,
        likesCount: response.data.likes || 0
      });
    } catch (error) {
      networkRequestsRef.current.delete(requestId);
      
      if (circuitBroken) {
        isFetchingRef.current = false;
        return;
      }
      
      
      if (isDirectAccessMode && onDirectAccessError) {
        onDirectAccessError();
      }
        if (!isOnline || 
          error.name === 'AbortError' || 
          error.code === 'ECONNABORTED' || 
          error.message === 'TIMEOUT' ||
          (error.message && (error.message.includes('timeout') || error.message.includes('Network Error'))) || 
          !error.response) {
        
        const isTimeout = error.message === 'TIMEOUT' || 
                          error.name === 'AbortError' || 
                          error.code === 'ECONNABORTED' ||
                          (error.message && error.message.includes('timeout'));
        
        setError({
          type: isTimeout ? 'timeout' : 'network',
          message: isTimeout 
            ? "Request timed out. Please check your internet connection and try again."
            : "Network connection issue. Please check your connection and try again.",
          status: isTimeout ? 'TIMEOUT' : 'NETWORK_ERROR'
        });
      } else {
        setError({
          type: 'single_short',
          message: error.response?.data?.error || 
                  'Unable to load content. Please check your connection and try again.',
          status: error.response?.status || 'NETWORK_ERROR'
        });
      }    } finally {
      isFetchingRef.current = false;
    }
  }, [api, circuitBroken, isDirectAccessMode, onDirectAccessError, isOnline]);

  const handleRetry = useCallback(() => {
    setCircuitBroken(false);
    setGlobalTimeout(false);
    setLoadingStartTime(Date.now());
    renderCountRef.current = 0;
    consecutiveRapidRendersRef.current = 0;
    
    networkRequestsRef.current.forEach((controller, id) => {
      try {
        controller.abort();
      } catch (e) {
      }
    });    networkRequestsRef.current.clear();
    
    if (!isOnline) {
      setError({
        type: 'offline',
        message: "You're currently offline. Please check your internet connection.",
        status: 'OFFLINE'
      });
      return;
    }
    
    setRetryCount(prev => prev + 1);
    setError(null);
    
    if (!isDirectAccessMode) {
      if (!feedInitialized) {
        dispatch(fetchShortsFeed())
          .then(() => setFeedInitialized(true))          .catch(error => {
            if (!isOnline) {
              setError({
                type: 'offline',
                message: "You're currently offline. Please check your internet connection.",
                status: 'OFFLINE'
              });
            } else {
              setError({
                type: 'feed',
                message: error.response?.data?.error || 'Failed to load shorts. Please try again.',
                status: error.response?.status || 'NETWORK_ERROR'
              });
            }
          });
      }
    } else if (paramShortId) {
      fetchSingleShort(paramShortId);
    }
  }, [dispatch, isDirectAccessMode, feedInitialized, paramShortId, fetchSingleShort, isOnline]);

  const shortsAlreadyLoaded = useSelector(state => state.shorts.shorts.length > 0);
  const isFirstMount = useRef(true);
  const needsRefreshCheck = useRef(true);

  useEffect(() => {
    if (isFirstMount.current) {
      isFirstMount.current = false;
      
      if (!isDirectAccessMode && !shortsAlreadyLoaded && !feedInitialized && !isInitializing) {
        setIsInitializing(true);
          if (!isOnline) {
          setError({
            type: 'offline',
            message: "You're currently offline. Please check your internet connection.",
            status: 'OFFLINE'
          });
          setIsInitializing(false);
          return;
        }
        
        const controller = new AbortController();
        
        const timeoutId = setTimeout(() => {
          controller.abort();
          setError({
            type: 'timeout',
            message: 'Request timed out. Please check your internet connection and try again.',
            status: 'TIMEOUT'
          });
          setIsInitializing(false);
        }, 15000);
          if (needsRefreshCheck.current) {
          needsRefreshCheck.current = false;
          dispatch(checkForNewShorts())
            .then(() => {
              clearTimeout(timeoutId);
              setFeedInitialized(true);
              setIsInitializing(false);
            })
            .catch(error => {
              clearTimeout(timeoutId);
              setIsInitializing(false);
              
              if (!isOnline || 
                  error.name === 'AbortError' || 
                  error.code === 'ECONNABORTED' || 
                  (error.message && error.message.includes('Network Error'))) {
                setError({
                  type: 'offline',
                  message: "Network connection issue. Please check your connection and try again.",
                  status: 'NETWORK_ERROR'
                });
              } else {
                setError({
                  type: 'feed',
                  message: error.response?.data?.error || 
                          'Unable to load content. Please check your connection and try again.',
                  status: error.response?.status || 'NETWORK_ERROR'
                });
              }
            });
        } else {
          dispatch(fetchShortsFeed())
            .then(() => {
              clearTimeout(timeoutId);
              setFeedInitialized(true);
              setIsInitializing(false);
            })
            .catch(error => {
              clearTimeout(timeoutId);              setIsInitializing(false);
              
              if (!isOnline || 
                  error.name === 'AbortError' || 
                  error.code === 'ECONNABORTED' || 
                  (error.message && error.message.includes('Network Error'))) {
                setError({
                  type: 'offline',
                  message: "Network connection issue. Please check your connection and try again.",
                  status: 'NETWORK_ERROR'
                });
              } else {
                setError({
                  type: 'feed',
                  message: error.response?.data?.error || 
                          'Unable to load content. Please check your connection and try again.',
                  status: error.response?.status || 'NETWORK_ERROR'
                });
              }
            });
        }
      } else if (shortsAlreadyLoaded && !isDirectAccessMode) {
        setFeedInitialized(true);
      }
    }
  }, [dispatch, isDirectAccessMode, feedInitialized, shortsAlreadyLoaded, isInitializing]);

  useEffect(() => {
    if (paramShortId && isDirectAccessMode) {
      fetchSingleShort(paramShortId);
    }
  }, [paramShortId, isDirectAccessMode, fetchSingleShort]);

  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < 768);
      setIsLargeScreen(window.innerWidth >= 768);
    }

    window.addEventListener('resize', handleResize);
    handleResize();

    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    if (!isDirectAccessMode && currentShort) {
      navigate(`/shorts/${currentShort.id}`, { replace: true });
    }
  }, [currentShort, navigate, isDirectAccessMode]);
  useEffect(() => {
    if (
      !isDirectAccessMode &&
      !loading &&
      !loadingMore &&
      !isFetchingRef.current &&
      pagination.hasMore &&
      currentShortIndex >= shorts.length - 2
    ) {      // Check if user is offline before attempting to load more shorts
      if (!isOnline) {
        toast.warning("You're offline. New shorts will load when you're back online.");
        return;
      }
      
      isFetchingRef.current = true;
      dispatch(fetchMoreShorts(pagination.nextCursor))
        .finally(() => {
          isFetchingRef.current = false;
        });
    }
  }, [currentShortIndex, shorts.length, loading, loadingMore, pagination, dispatch, isDirectAccessMode]);

  useEffect(() => {
    if (!isDirectAccessMode) {
      const handleKeyDown = (e) => {
        if (e.key === 'ArrowUp') {
          goToPrevShort();
        } else if (e.key === 'ArrowDown') {
          goToNextShort();
        }
      };

      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [goToPrevShort, goToNextShort, isDirectAccessMode]);

  const touchStartRef = useRef({ x: 0, y: 0, time: 0 });
  const touchEndRef = useRef({ x: 0, y: 0, time: 0 });
  const isSwiping = useRef(false);

  const handleTouchStart = (e) => {
    // Store initial touch position with timestamp
    touchStartRef.current = {
      x: e.touches[0].clientX,
      y: e.touches[0].clientY,
      time: Date.now()
    };
    isSwiping.current = false;
  };

  const handleTouchMove = (e) => {
    // Store current position during movement
    touchEndRef.current = {
      x: e.touches[0].clientX,
      y: e.touches[0].clientY,
      time: Date.now()
    };
  
    // Calculate vertical difference as we move
    const diffY = touchStartRef.current.y - touchEndRef.current.y;
  
    // If significant vertical movement detected, mark as swiping
    if (Math.abs(diffY) > 30) {
      isSwiping.current = true;
      // Prevent pull-to-refresh if swiping vertically and at the top of the page
      if (window.scrollY === 0 && diffY < 0) {
        e.preventDefault();
      }
    }
  };

  const handleTouchEnd = (e) => {
    // Calculate vertical and horizontal differences
    const diffY = touchStartRef.current.y - touchEndRef.current.y;
    const diffX = touchStartRef.current.x - touchEndRef.current.x;
    
    // Calculate time difference and speed
    const timeDiff = touchEndRef.current.time - touchStartRef.current.time;
    const velocity = Math.abs(diffY) / timeDiff; // pixels per ms
    
    // Minimum swipe distance and maximum swipe time
    const minSwipeDistance = 70;
    const maxSwipeTime = 600; // milliseconds
    const minVelocity = 0.3; // pixels per ms
    
    if (Math.abs(diffY) > Math.abs(diffX) && 
      (Math.abs(diffY) > minSwipeDistance || velocity > minVelocity) && 
      timeDiff < maxSwipeTime && 
      isSwiping.current) {
    
    if (diffY > 0) {
      // Allow going next in both direct access mode and normal mode
      if (isDirectAccessMode || (!isDirectAccessMode && currentShortIndex < shorts.length - 1)) {
        console.log(`Swipe UP detected: ${diffY.toFixed(2)}px in ${timeDiff}ms`);
        goToNextShort();
      }
    } else {
      // Only goPrev if not at the beginning and not in direct access mode
      if (!isDirectAccessMode && currentShortIndex > 0) {
        console.log(`Swipe DOWN detected: ${Math.abs(diffY).toFixed(2)}px in ${timeDiff}ms`);
        goToPrevShort();
      }
    }
  }
  
  isSwiping.current = false;
  };

  const { createLikeHandler, createSaveHandler } = useInteractionManager();
  

  const handleLikeToggle = useCallback((e) => {
    if (!currentShort) return;
    
    // Add robust checks before accessing classList
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
    
    const postId = isDirectAccessMode ? paramShortId : currentShort.id;
    const postIdStr = postId.toString();
    
    // 1. Remember the ORIGINAL backend state (from Redux)
    const originalBackendState = isDirectAccessMode 
      ? shortInteractions.liked 
      : currentShort?.userInteraction?.liked || false;
      
    const originalCount = isDirectAccessMode
      ? shortInteractions.likesCount
      : currentShort?.likes || 0;
    
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
        console.log("Heart animation error:", error);
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
  }, [currentShort, dispatch, isDirectAccessMode, shortInteractions, paramShortId]);

  const [followLoading, setFollowLoading] = useState(false);
  const pendingFollowOperationRef = useRef(null);
  const pendingSaveOperations = useRef(new Map()); // Add this ref to track save operations

  const handleSaveToggle = useCallback((e) => {
    if (!currentShort) return;

    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
      });
    }    // Early return if offline
    if (!isOnline) {
      toast.warning("You're offline. This action will be available when you're back online.");
      return;
    }

    if (isDirectAccessMode) {
      // Direct access mode handling
      const shortId = paramShortId;
      const originalSaved = shortInteractions.saved;
      
      // Update UI immediately for better UX
      setShortInteractions(prev => ({
        ...prev,
        saved: !originalSaved
      }));
      
      // Cancel any pending operation for this short
      if (pendingSaveOperations.current.has(shortId)) {
        clearTimeout(pendingSaveOperations.current.get(shortId));
      }
      
      // Debounce API call
      const timerId = setTimeout(async () => {
        try {
          // Make the direct API call with explicit action parameter
          await axios.post(
            `${api}/user-interactions/save/${shortId}`,
            { action: !originalSaved ? 'save' : 'unsave' },
            { withCredentials: true }
          );
          console.log(`Successfully ${!originalSaved ? 'saved' : 'unsaved'} short`);
        } catch (err) {
          console.error('Error toggling save status:', err);
          // Revert UI on error
          setShortInteractions(prev => ({
            ...prev,
            saved: originalSaved
          }));
          toast.error('Failed to update save status');
        } finally {
          pendingSaveOperations.current.delete(shortId);
        }
      }, 500);
      
      pendingSaveOperations.current.set(shortId, timerId);
      
    } else {
      // Feed mode handling
      const shortId = currentShort.id;
      const isSaved = currentShort.userInteraction?.saved || false;
      
      // Update Redux state optimistically
      dispatch(updateShortInteraction({
        shortId,
        type: 'save',
        value: !isSaved
      }));
      
      // Cancel any pending operation for this short
      if (pendingSaveOperations.current.has(shortId)) {
        clearTimeout(pendingSaveOperations.current.get(shortId));
      }
      
      // Debounce API call
      const timerId = setTimeout(async () => {
        try {
          // Make the direct API call with explicit action parameter
          const response = await axios.post(
            `${api}/user-interactions/save/${shortId}`,
            { action: !isSaved ? 'save' : 'unsave' },
            { withCredentials: true }
          );
          console.log(`Successfully ${!isSaved ? 'saved' : 'unsaved'} short:`, response.data);
        } catch (err) {
          console.error('Error toggling save status:', err);
          // Revert Redux state on error
          dispatch(updateShortInteraction({
            shortId,
            type: 'save',
            value: isSaved
          }));
          toast.error('Failed to update save status');
        } finally {
          pendingSaveOperations.current.delete(shortId);
        }
      }, 500);
      
      pendingSaveOperations.current.set(shortId, timerId);
    }
  }, [currentShort, dispatch, isDirectAccessMode, shortInteractions, paramShortId, api, isOnline]);

  // Cleanup pending operations on unmount
  useEffect(() => {
    return () => {
      if (pendingFollowOperationRef.current) {
        clearTimeout(pendingFollowOperationRef.current);
      }
      
      // Clear all pending save operations
      pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingSaveOperations.current.clear();
      
      // Clear all pending like operations
      pendingLikeOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingLikeOperations.current.clear();
    };
  }, []);

  const handleFollowToggle = useCallback((e) => {
    if (e) e.stopPropagation();
    if (!currentShort || followLoading) return;
    
    // Clear any pending follow operation
    if (pendingFollowOperationRef.current) {
      clearTimeout(pendingFollowOperationRef.current);
    }
    
    setFollowLoading(true);
    
    const authorId = isDirectAccessMode 
      ? singleShortData?.author?.id
      : currentShort?.author?.id;
    
    if (!authorId) {
      setFollowLoading(false);
      return;
    }
    
    // Optimistically update UI
    if (isDirectAccessMode) {
      const currentFollowState = singleShortData.isFollowing;
      setSingleShortData(prev => ({
        ...prev,
        isFollowing: !currentFollowState
      }));
      
      // Perform the actual API call after a short delay
      pendingFollowOperationRef.current = setTimeout(async () => {
        try {
          // Use a more resilient approach with try/catch for each API call
          if (currentFollowState) {
            try {
              // Directly use axios delete instead of the endpoint that's causing issues
              await axios.delete(`${api}/user/follow/${authorId}`, {
                withCredentials: true
              });
              console.log('Successfully unfollowed user');
            } catch (err) {
              console.error('Error unfollowing user:', err);
              // Even if server errors out, we won't revert the UI since the operation might have succeeded
              if (err.response && err.response.status === 404) {
                console.log('User was already unfollowed');
              }
            }
          } else {
            try {
              await axios.post(`${api}/user/follow/${authorId}`, {}, {
                withCredentials: true
              });
              console.log('Successfully followed user');
            } catch (err) {
              console.error('Error following user:', err);
              if (err.response && err.response.status === 400) {
                console.log('Already following this user');
              }
            }
          }
        } catch (err) {
          console.error('Error in follow toggle operation:', err);
          // Revert UI state on catastrophic errors only
          if (err.message && err.message.includes('Network Error')) {
            setSingleShortData(prev => ({
              ...prev,
              isFollowing: currentFollowState
            }));
          }
        } finally {
          setFollowLoading(false);
          pendingFollowOperationRef.current = null;
        }
      }, 300);
      
    } else {
      const currentFollowState = currentShort.userInteraction?.isFollowing || false;
      const shortId = currentShort.id;
      
      // Update Redux state optimistically
      dispatch(updateShortInteraction({
        shortId,
        type: 'follow',
        value: !currentFollowState
      }));
      
      // Perform the actual API call after a short delay
      pendingFollowOperationRef.current = setTimeout(async () => {
        try {
          if (currentFollowState) {
            try {
              await axios.delete(`${api}/user/follow/${authorId}`, {
                withCredentials: true
              });
              console.log('Successfully unfollowed user');
            } catch (err) {
              console.error('Error unfollowing user:', err);
              // Don't revert UI for specific error codes that indicate the operation might have still worked
              if (err.response && err.response.status === 404) {
                console.log('User was already unfollowed');
              } else if (err.message && !err.message.includes('ERR_HTTP_HEADERS_SENT')) {
                // Only revert if it's not the headers error (which means the operation likely succeeded)
                dispatch(updateShortInteraction({
                  shortId,
                  type: 'follow',
                  value: currentFollowState
                }));
              }
            }
          } else {
            try {
              await axios.post(`${api}/user/follow/${authorId}`, {}, {
                withCredentials: true
              });
              console.log('Successfully followed user');
            } catch (err) {
              console.error('Error following user:', err);
              if (err.response && err.response.status === 400) {
                console.log('Already following this user');
              } else if (err.message && !err.message.includes('ERR_HTTP_HEADERS_SENT')) {
                // Only revert if it's not the headers error
                dispatch(updateShortInteraction({
                  shortId,
                  type: 'follow',
                  value: currentFollowState
                }));
              }
            }
          }
        } catch (err) {
          console.error('Error in follow toggle operation:', err);
          // Only revert UI on catastrophic errors
          if (err.message && err.message.includes('Network Error')) {
            dispatch(updateShortInteraction({
              shortId,
              type: 'follow',
              value: currentFollowState
            }));
          }
        } finally {
          setFollowLoading(false);
          pendingFollowOperationRef.current = null;
        }
      }, 300);
    }
  }, [currentShort, api, dispatch, isDirectAccessMode, singleShortData, followLoading]);

  // Cleanup pending operations on unmount
  useEffect(() => {
    return () => {
      if (pendingFollowOperationRef.current) {
        clearTimeout(pendingFollowOperationRef.current);
      }
    };
  }, []);

  const handleCommentClick = () => {
    dispatch(setIsCommentOpen(true));
  };

  const handleReportPost = () => {
    setReportType('post');
    setReportTargetId(currentShort?.id);
    setShowReportWidget(true);
    setIsMoreOpen(false);
  };

  const [showCopyNotification, setShowCopyNotification] = useState(false);

  const handleCopyLink = () => {
    if (!currentShort) return;
    const shortUrl = `${window.location.origin}/${isDirectAccessMode ? 'short' : 'shorts'}/${currentShort.id}`;
    navigator.clipboard.writeText(shortUrl)
      .then(() => {
        // Show notification
        setShowCopyNotification(true);
        setTimeout(() => setShowCopyNotification(false), 2000);
        
        toast.success("Link copied to clipboard");
        setIsMoreOpen(false);
      })
      .catch((error) => {
        console.error('Failed to copy text:', error);
        toast.error("Failed to copy link");
      });
  };

  const handleShare = () => {
    setShowShareWidget(true);
  };

  const handleMoreClick = () => {
    setIsMoreOpen(!isMoreOpen);
  };

  const [deleteConfirmation, setDeleteConfirmation] = useState({
    isOpen: false,
    shortId: null,
    shortTitle: ''
  });

  const handleDeleteShort = useCallback(() => {
    if (!currentShort?.id) return;
    
    setDeleteConfirmation({
      isOpen: true,
      shortId: currentShort.id,
      shortTitle: currentShort.content?.substring(0, 30) || 'this short'
    });
    
    setIsMoreOpen(false);
  }, [currentShort]);

  const confirmDelete = useCallback(() => {
    console.log("Confirming delete for short:", deleteConfirmation.shortId);
    // Show deleting UI
    setIsDeleting(true);
    
    // Close the modal immediately
    setDeleteConfirmation({
      isOpen: false,
      shortId: null,
      shortTitle: ''
    });
    
    if (deleteConfirmation.shortId) {
      if (isDirectAccessMode) {
        // Direct access mode - use axios and navigate away
        axios.delete(`${api}/post/${deleteConfirmation.shortId}`, {
          withCredentials: true
        })
        .then(() => {
          toast.success("Short deleted successfully");
          navigate('/', { replace: true });
        })
        .catch(error => {
          console.error('Error deleting short:', error);
          toast.error('Failed to delete short. Please try again.');
        })
        .finally(() => {
          setIsDeleting(false);
        });
      } else {
        // Use Redux thunk for better state management
        dispatch(deleteShort(deleteConfirmation.shortId))
          .then((result) => {
            if (result.meta.requestStatus === 'fulfilled') {
              // Dispatch to other reducers to ensure consistency across the app
              dispatch({ type: 'home/removePost', payload: deleteConfirmation.shortId });
              dispatch({ type: 'profile/removeUserPost', payload: deleteConfirmation.shortId });
              
              toast.success("Short deleted successfully");
            } else {
              toast.error('Failed to delete short. Please try again.');
            }
          })
          .finally(() => {
            setIsDeleting(false);
          });
      }
    }
  }, [deleteConfirmation.shortId, isDirectAccessMode, dispatch, navigate, api]);

  const cancelDelete = useCallback(() => {
    setDeleteConfirmation({
      isOpen: false,
      shortId: null,
      shortTitle: ''
    });
  }, []);

  useEffect(() => {
    function handleClickOutside(event) {
      if (isMoreOpen &&
        bottomSheetRef.current &&
        !bottomSheetRef.current.contains(event.target) &&
        !event.target.closest('[data-more-button="true"]')) {
        setIsMoreOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isMoreOpen]);

  useEffect(() => {
    const handleDisplayModeChange = () => setIsPWA(isRunningAsPWA());

    window.addEventListener('resize', handleDisplayModeChange);
    return () => window.removeEventListener('resize', handleDisplayModeChange);
  }, []);

  useEffect(() => {
    if (!currentShort || !currentShort.id) {
      return;
    }

    const shortId = currentShort.id.toString();
    if (viewedShortsRef.current.has(shortId)) {
      return;
    }

    viewedShortsRef.current.add(shortId);

    const recordView = () => {
      axios.post(
        `${api}/user-interactions/view/${shortId}`, 
        {}, 
        { withCredentials: true }
      )
      .then(response => {
        console.log(`✅ View recorded successfully for short: ${shortId}`, response.data);
      })
      .catch(error => {
        console.error(`❌ Error recording view for short ${shortId}:`, error);
      });
    };
    
    const viewTimer = setTimeout(recordView, 500);
    
    return () => {
      clearTimeout(viewTimer);
    };
  }, [currentShort?.id, api]);

  useEffect(() => {
    if (contentRef.current) {
      const element = contentRef.current;
      setIsContentOverflowing(element.scrollHeight > element.clientHeight);
    }
  }, [currentShort?.content]);

  useEffect(() => {
    setIsContentExpanded(false);
  }, [currentShortIndex, paramShortId]);

  const handleExpandContent = () => {
    setIsContentExpanded(true);
    setTimeout(() => {
      if (contentRef.current) {
        contentRef.current.scrollTop = 0;
      }
    }, 50);
  };

  // Add useEffect to parse notification data from URL
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const notificationType = searchParams.get('notificationType');
    const referenceId = searchParams.get('referenceId');
    
    if (notificationType && ['comment', 'reply', 'comment_like', 'reply_like'].includes(notificationType)) {
      setNotificationData({
        type: notificationType,
        reference_id: referenceId,
        post_id: currentShort?.id || paramShortId
      });
    }
  }, [location, currentShort?.id, paramShortId]);

  // Add useEffect to auto-open comment widget when notification data is present
  useEffect(() => {
    if (notificationData && 
        ['comment', 'reply', 'comment_like', 'reply_like'].includes(notificationData.type) && 
        (currentShort?.id === notificationData.post_id || paramShortId === notificationData.post_id)) {
      // Slight delay to ensure short is loaded first
      const timer = setTimeout(() => {
        dispatch(setIsCommentOpen(true));
      }, 300);
      
      return () => clearTimeout(timer);
    }
  }, [notificationData, currentShort?.id, paramShortId, dispatch]);

  const containerHeight = isPWA
    ? "max-md:h-[calc(100vh-50px)] md:h-screen"
    : "max-md:h-[calc(100vh-105px)] md:h-screen";

  const ShortsSkeleton = () => {
    const [skeletonTimeout, setSkeletonTimeout] = useState(false);
    
    useEffect(() => {
      const timer = setTimeout(() => {
        setSkeletonTimeout(true);
      }, 8000);
      
      return () => clearTimeout(timer);
    }, []);
    
    if (skeletonTimeout) {
      return (
        <div className={`flex justify-center ${containerHeight} md:items-center max-md:mt-2 bg-[#0a0a0a]`}>
          <div className="relative flex justify-center aspect-[9/16] md:bg-[#0c0d11] 
                       border-gray-800 md:border-[1px] w-full 500:max-w-sm max-500:max-w-full
                       bg-card md:rounded-3xl overflow-hidden">
            <ErrorDisplay 
              error={{type: 'timeout', message: 'Loading is taking longer than expected. Please try again.'}} 
              onRetry={handleRetry} 
            />
          </div>
        </div>
      );
    }
    
    return (
      <div className={`flex justify-center ${containerHeight} md:items-center  bg-[#0a0a0a]`}>
        <div className="relative flex justify-center aspect-[9/16] md:bg-[#0c0d11] 
                      border-gray-800 md:border-[1px] w-full 500:max-w-sm max-500:max-w-full
                      bg-card md:rounded-3xl overflow-hidden">
          <div className="w-[96%] mx-auto mt-2 rounded-2xl h-[40%] bg-gray-800 animate-pulse"></div>
          
          <div className="absolute top-[42%] left-0 w-full h-[50%]">
            <div className="relative flex-1 px-3 pr-11 h-[75%]">
              <div className="h-4 bg-gray-700 rounded w-3/4 mb-2 animate-pulse"></div>
              <div className="h-4 bg-gray-700 rounded w-full mb-2 animate-pulse"></div>
              <div className="h-4 bg-gray-700 rounded w-2/3 animate-pulse"></div>
            </div>
            
            <div className="absolute right-3 bottom-11 flex flex-col items-center space-y-7">
              {[1, 2, 3, 4].map(i => (
                <div key={i} className="w-6 h-6 bg-gray-700 rounded-full animate-pulse"></div>
              ))}
            </div>
            
            <div className="flex md:bg-[#0c0d11] w-[90%] absolute bottom-4 left-0 items-center px-4 pt-2 pb-4">
              <div className="flex items-center">
                <div className="w-9 h-9 bg-gray-700 rounded-full mr-3 animate-pulse"></div>
                <div className="flex-1">
                  <div className="h-4 bg-gray-700 rounded w-24 mb-1 animate-pulse"></div>
                  <div className="h-3 bg-gray-700 rounded w-16 animate-pulse"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const isLoading = !circuitBroken && !globalTimeout && (
    (isDirectAccessMode && !singleShortData && !error) || 
    (!isDirectAccessMode && loading && !currentShort && !error)
  );

  const isEmpty = !globalTimeout && (
    (isDirectAccessMode && !singleShortData && !error) || 
    (!isDirectAccessMode && !loading && shorts.length === 0 && !error)
  );

  if (isLoading && Date.now() - loadingStartTime > 10000) {
    return (
      <div className={`flex justify-center ${containerHeight} max-md:h-[calc(100vh-105px)] md:items-center  bg-[#0a0a0a]`}>
        <div className="relative flex justify-center aspect-[9/16] md:bg-[#0c0d11] 
                     border-gray-800 md:border-[1px] w-full 500:max-w-sm max-500:max-w-full
                     bg-card md:rounded-3xl overflow-hidden">
          <ErrorDisplay 
            error={{type: 'timeout', message: 'Loading is taking longer than expected. Please try again.'}} 
            onRetry={handleRetry} 
          />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`flex justify-center ${containerHeight} max-md:h-[calc(100vh-105px)] md:items-center max-md:mt-2 bg-[#0a0a0a]`}>
        <div className="relative flex justify-center aspect-[9/16] md:bg-[#0c0d11] 
                       border-gray-800 md:border-[1px] w-full 500:max-w-sm max-500:max-w-full
                       bg-card md:rounded-3xl overflow-hidden">
          <ErrorDisplay error={error} onRetry={handleRetry} />
        </div>
      </div>
    );
  }

  if (isLoading) {
    return <ShortsSkeleton />;
  }

  if (isEmpty) {
    return (
      <div className="flex flex-col justify-center items-center h-screen bg-[#0a0a0a] text-white">
        <p className="text-xl mb-4">No {isDirectAccessMode ? 'short' : 'shorts'} available right now</p>
        {!isDirectAccessMode && (
          <button
            onClick={() => dispatch(fetchShortsFeed())}
            className="px-4 py-2 bg-primary rounded-lg"
          >
            Refresh
          </button>
        )}
      </div>
    );
  }

  const likesCount = isDirectAccessMode
    ? shortInteractions.likesCount
    : currentShort?.likes || 0;

  const isLiked = isDirectAccessMode
    ? shortInteractions.liked
    : currentShort?.userInteraction?.liked || false;

  const isSaved = isDirectAccessMode
    ? shortInteractions.saved
    : currentShort?.userInteraction?.saved || false;

  const isFollowing = isDirectAccessMode
    ? singleShortData?.isFollowing
    : currentShort?.userInteraction?.isFollowing || false;

  return (
    <>
      <div
        className={`flex scrollbar-hidden shorts-container scrollbar-hidden justify-center h-screen ${containerHeight} max-md:h-[calc(100vh-105px)] md:items-center  bg-[#0a0a0a]`}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        ref={shortsContainerRef}
      >
        {isLargeScreen && (
          <div className="absolute right-10 top-1/2 transform -translate-y-1/2 flex flex-col gap-4">
            <button
              onClick={goToPrevShort}
              disabled={isDirectAccessMode || currentShortIndex === 0}
              className={`text-white p-3 rounded-full ${
                isDirectAccessMode || currentShortIndex === 0 ? 'opacity-30 cursor-not-allowed' : 'opacity-80 hover:opacity-100 bg-gray-800'
              }`}
              title="Previous Short"
            >
              <FaArrowUp size={24} />
            </button>

            <button
              onClick={goToNextShort}
              className={`text-white p-3 rounded-full opacity-80 hover:opacity-100 bg-gray-800`}
              title={isDirectAccessMode ? "Load More Shorts" : "Next Short"}
            >
              <FaArrowDown size={24} />
            </button>
          </div>
        )}

        <div
          ref={containerRef}
          className={`relative flex justify-center aspect-[9/16] md:bg-[#0c0d11]
            border-gray-800 md:border-[1px] w-full 500:max-w-sm max-500:max-w-full
            bg-card md:rounded-3xl overflow-hidden scrollbar-hidden
            ${displayWidget ? 'z-50 border-gray-800 border-[1px] bg-[#0c0d11]' : ''}
            ${transitionDirection === 'up' ? 'animate-slide-up' : transitionDirection === 'down' ? 'animate-slide-down' : ''}`}
        >
          {currentShort && (
            <>
              <div className="w-[100vw] mx-auto md:rounded-t-2xl h-[50%] relative">
                {currentShort.media && currentShort.media.length > 0 ? (
                  <>
                    <ShortMediaCarousel
                      media={currentShort.media}
                      postId={currentShort.id}
                      currentIndex={currentMediaIndex}
                      autoPlay={true}
                      isRedux={false}
                      onIndexChange={(postId, newIndex) => setCurrentMediaIndex(newIndex)}
                      api={api}
                      isPrefetched={prefetchedShorts.has(currentShort.id)}
                      cachedMedia={getCachedMedia(currentShort.id)}
                      onMediaLoaded={() => setMediaLoaded(true)} 
                    />
                    {!mediaLoaded && (
                      <div className="absolute inset-0 flex items-center justify-center bg-gray-900 rounded-2xl z-10">
                        <div className="w-10 h-10 border-4 border-t-primary border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin" />
                      </div>
                    )}
                  </>
                ) : (
                  <div className="w-full h-full flex items-center justify-center bg-gray-900 md:rounded-t-2xl">
                    <p className="text-gray-500">No media available</p>
                  </div>
                )}
              </div>

              <div className="absolute top-[52%] md:top-[51%] left-0 w-full h-[50%]">
                <div 
                  ref={contentRef}
                  className={`relative flex-1 px-3 pr-11 text-gray-300 ${
                    isContentExpanded ? 'h-[75%] overflow-y-scroll' : 'h-[75%] overflow-hidden'
                  } hide-scrollbar`}
                >
                  <p className="max-md mt-1 max-md:text-[16.4px] fontNeed" style={{ fontFamily: 'Nunito-san' }}>
                    {currentShort.content || ""}
                  </p>
                  
                  {isContentOverflowing && !isContentExpanded && (
                    <div className="absolute text-lg font-sans bottom-0 -left-10 w-full bg-gradient-to-t from-[#0c0d11] to-transparent h-8 flex justify-end items-end">
                      <button 
                        onClick={handleExpandContent}
                        className="text-blue-500 hover:text-blue-400 text-sm font-medium mr-4 mb-1"
                      >
                        more
                      </button>
                    </div>
                  )}
                </div>

                <div className="absolute right-3 bottom-11 flex flex-col items-center space-y-7">                <button
  onClick={handleLikeToggle}
  className="hover:text-gray-300 border border-gray-600 hover:border-gray-500 transition-colors py-2 px-[5px] rounded-full"
  data-like-button={currentShort?.id}
>
  <div className="flex flex-col items-center">
    <BiUpvote 
      className="text-white empty-heart" 
      size={20}
      style={{
        display: (() => {
          const postId = currentShort?.id?.toString();
          
          // If we've interacted with this post, visualState is the source of truth
          if (postId && postId in visualState.current.likedPosts) {
            return visualState.current.likedPosts[postId] ? 'none' : 'block';
          }
          
          // Otherwise fall back to Redux state
          return isDirectAccessMode
            ? (shortInteractions.liked ? 'none' : 'block')
            : (currentShort?.userInteraction?.liked ? 'none' : 'block');
        })()
      }} 
    />
    <BiSolidUpvote 
      className="text-gray-300 filled-heart" 
      size={20}
      style={{
        display: (() => {
          const postId = currentShort?.id?.toString();
          
          // If we've interacted with this post, visualState is the source of truth
          if (postId && postId in visualState.current.likedPosts) {
            return visualState.current.likedPosts[postId] ? 'block' : 'none';
          }
          
          // Otherwise fall back to Redux state
          return isDirectAccessMode
            ? (shortInteractions.liked ? 'block' : 'none')
            : (currentShort?.userInteraction?.liked ? 'block' : 'none');
        })()
      }}
    />
    <span className="text-sm block mt-2 text-center">
      {(() => {
        const postId = currentShort?.id?.toString();
        const originalCount = isDirectAccessMode 
          ? shortInteractions.likesCount
          : currentShort?.likes || 0;
          
        // If we've interacted with this post, calculate adjusted count
        if (postId && postId in visualState.current.likedPosts) {
          const originalLiked = isDirectAccessMode 
            ? shortInteractions.liked 
            : currentShort?.userInteraction?.liked || false;
          
          const visualDelta = visualState.current.likedPosts[postId] !== originalLiked
            ? (visualState.current.likedPosts[postId] ? 1 : -1)
            : 0;
          
          return Math.max(0, originalCount + visualDelta).toString();
        }
        
        // Otherwise show original count
        return originalCount.toString();
      })()}
    </span>
  </div>
</button>
                  <button
                    onClick={handleCommentClick}
                    className="text-white hover:text-gray-300"
                  >
                    <TfiCommentAlt size={20} />
                    <span className="text-sm block mt-1 text-center">
                      {(currentShort.comments > 0) ? currentShort.comments : '0'}
                    </span>
                  </button>

                  <button
                    onClick={handleShare}
                    className="text-white hover:text-gray-300"
                  >
                    <BsSend size={20} />
                  </button>

                  <button
                    onClick={handleMoreClick}
                    className="text-white hover:text-gray-300"
                    data-more-button={true}
                  >
                    <FiMoreVertical size={20} />
                  </button>
                </div>

                <div className="flex md:bg-[#0c0d11] w-[90%] absolute bottom-4 left-0 items-center justify-between px-4 pt-2 pb-4">
                  <div className="flex items-center">                    <Link to={`/${currentShort.author?.username}`} className="flex items-center">
                      <img
                        className={`${currentShort.author?.profilePicture ? "" : "border-[1px] bg-white border-gray-200"} w-9 h-9 rounded-full mr-3 object-cover`}
                        src={
                          currentShort.author?.profilePicture ?
                          `${cloud}/cloudofscubiee/profilePic/${currentShort.author.profilePicture}` :
                          DefaultPicture
                        }
                        alt="User profile"
                      />
                      <div className="flex flex-col">
                        <h2 className="text-md font-bold text-white hover:text-gray-300 transition-colors">
                          {currentShort.author?.username || "Loading..."}
                        </h2>
                        <h3 className="text-xs text-gray-400">
                          {new Date(currentShort.createdAt).toLocaleDateString('en-US', {
                            day: 'numeric',
                            month: 'short',
                            year: 'numeric'
                          })}
                        </h3>
                      </div>
                    </Link>
                    {currentShort.author?.id !== userData?.id && (
                      <button
                        className={`ml-3 text-[13px] font-medium font-sans border rounded-lg py-1 px-3 flex items-center ${
                          isFollowing ?
                          'bg-transparent text-white' : 'bg-secondary text-white'
                        } ${followLoading ? 'opacity-80' : ''}`}
                        onClick={handleFollowToggle}
                        disabled={followLoading}
                      >
                        {followLoading && (
                          <span className="h-3 w-3 border-2 border-t-transparent border-white border-solid rounded-full inline-block animate-spin mr-1.5"></span>
                        )}
                        {isFollowing ? "Following" : "Follow"}
                      </button>
                    )}
                  </div>
                </div>

                <div
                  ref={bottomSheetRef}
                  className={`
                  z-50 h-[110px] bg-[#111111] border-t-2 border-gray-800 rounded-t-2xl
                  transition-transform duration-300 absolute bottom-0 left-0 w-full
                  ${isMoreOpen ? "translate-y-0" : "translate-y-full"}
                `}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="h-full w-full p-4 flex items-center justify-center space-x-20">
                    <div className="flex flex-col items-center">
                      {currentShort?.author?.id === userData?.id ? (
                        <>
                          <button
                            onClick={handleDeleteShort}
                            className="text-red-700 border-[1px] p-2 rounded-full border-gray-700 hover:scale-105 mb-1"
                            title="Delete"
                          >
                            <RiDeleteBin6Line size={26} />
                          </button>
                          <span className="text-gray-300 text-xs font-sans">Delete</span>
                        </>
                      ) : (
                        <>
                          <button onClick={handleReportPost} className="text-red-700 border-[1px] p-2 rounded-full border-gray-700 hover:scale-105 mb-1" title="Report">
                            <MdOutlineReport size={32} />
                          </button>
                          <span className="text-gray-300 text-xs font-sans">Report</span>
                        </>
                      )}
                    </div>

                    <div className="flex flex-col items-center">
                      <button onClick={handleSaveToggle} className="text-white border-[1px] p-[13px] rounded-full border-gray-700 transition-transform duration-200 hover:scale-105 mb-1" title="Bookmark">
                        {isSaved ? <BsBookmarkFill size={21} /> : <BsBookmark size={21} />}
                      </button>
                      <span className="text-gray-300 text-xs">Save</span>
                    </div>

                    <div className="flex flex-col items-center">
                      <button onClick={handleCopyLink} className="text-white border-[1px] p-3 rounded-full border-gray-700 hover:scale-105 mb-1" title="Copy Link">
                        <MdOutlineContentCopy size={24} />
                      </button>
                      <span className="text-gray-300 text-xs">Copy</span>
                    </div>
                  </div>
                </div>
              </div>

              {isDeleting && (
                <div className="absolute inset-0 z-[60] bg-black bg-opacity-60 flex items-center justify-center">
                  <div className="bg-black bg-opacity-80 rounded-lg px-4 py-2 flex items-center">
                    <span className="text-white mr-2">Deleting</span>
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Add Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
        </div>
      )}

      {showShareWidget && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
          onClick={() => setShowShareWidget(false)}
        >
          <div onClick={(e) => e.stopPropagation()} className="z-[110]">
            <ShareDialog
              postId={currentShort?.id}
              onClose={() => setShowShareWidget(false)}
            />
          </div>
        </div>
      )}

      {isCommentOpen && currentShort && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
          onClick={() => dispatch(setIsCommentOpen(false))}
        >
          <div onClick={(e) => e.stopPropagation()} className="z-[110]">
            <CommentWidget
              postId={currentShort.id}
              isOpen={isCommentOpen}
              onClose={() => dispatch(setIsCommentOpen(false))}
              userId={currentShort.author?.id}
              notificationData={notificationData} // Add this prop
            />
          </div>
        </div>
      )}

      {showReportWidget && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70"
          onClick={() => setShowReportWidget(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="bg-[#1a1a1a] p-4 rounded-md w-[90%] sm:w-[400px] text-white z-[110]"
          >
            <ReportWidget
              onClose={() => setShowReportWidget(false)}
              type={reportType}
              targetId={reportTargetId}
            />
          </div>
        </div>
      )}

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
                <h3 className="text-xl font-semibold text-white">Delete Short</h3>
              </div>

              <div className="h-px w-full bg-gradient-to-r from-transparent via-gray-700 to-transparent my-3"></div>

              <p className="text-gray-300 mb-6 pl-1">
                Are you sure you want to delete {deleteConfirmation.shortTitle ? (
                  <span className="font-medium text-white">"{deleteConfirmation.shortTitle.length > 25 ?
                    deleteConfirmation.shortTitle.substring(0, 25) + '...' :
                    deleteConfirmation.shortTitle}"</span>
                ) : 'this short'}? This action cannot be undone.
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
    </>
  );
}