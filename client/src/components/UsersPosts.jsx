import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import axios from "axios";
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import { BiArrowBack } from "react-icons/bi";
import { toast } from 'react-toastify';
import { useDispatch, useSelector } from 'react-redux';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import ShareDialog from "../components/shareWidget";
import { MdOutlineReport, MdOutlineContentCopy, MdOutlineDeleteOutline } from "react-icons/md";
import { IoCloseSharp } from "react-icons/io5";
import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
import ShortMediaCarousel from '../components/ShortMediaCarousel';
import CommentWidget from "../components/CommentWidget";
import ReportWidget from "../components/ReportWidget";
import { useInteractionManager } from '../hooks';
import { createPortal } from 'react-dom';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

// Portal component for modals
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  // Check if document exists (for SSR safety) and only render when component is mounted
  return mounted && typeof document !== 'undefined' ? createPortal(children, document.body) : null;
};

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

// Custom hook for horizontal scroll index
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
};

const UsersPosts = () => {
  // Get the type from URL instead of props
  const { type } = useParams(); // Will be 'liked' or 'saved'
  
  // States for content
  const [activeTab, setActiveTab] = useState(false);
  const [posts, setPosts] = useState([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [contentLoading, setContentLoading] = useState(false);
  const [error, setError] = useState(null);
  const [renderError, setRenderError] = useState(false);
  
  // UI states
  const [likedPosts, setLikedPosts] = useState({});
  const [savedPosts, setSavedPosts] = useState({});
  const [shortMediaIndexes, setShortMediaIndexes] = useState({});
  const [playingVideos, setPlayingVideos] = useState({});
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);
  const [activeMenu, setActiveMenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [sharePostId, setSharePostId] = useState(null);
  const [CommentPostId, setCommentPostId] = useState(null);
  const [showCopyNotification, setShowCopyNotification] = useState(false);
  // Refs
  const observerRef = useRef(null);
  const menuRef = useRef(null);
  const pageRef = useRef(null);
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map());
  const visualState = useRef({
    likedPosts: {},
    savedPosts: {}
  });
  const visualSavedState = useRef({});

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);
  
  // Other hooks
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);
  const { createLikeHandler, createSaveHandler } = useInteractionManager();
  
  const DefaultPicture = "/logos/DefaultPicture.png";
  
  // Add current user data from Redux
  const currentUser = useSelector(state => state.user.userData);
  
  // Add states for delete confirmation and report widget
  const [deleteConfirmation, setDeleteConfirmation] = useState({
    isOpen: false,
    postId: null,
    postTitle: ''
  });
  const [isDeleting, setIsDeleting] = useState(false);
  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportType, setReportType] = useState(null);
  const [reportTargetId, setReportTargetId] = useState(null);
  const reportWidgetRef = useRef(null);
  
  // Add state and ref for bottom sheet menu
  const [showBottomSheet, setShowBottomSheet] = useState(false);
  const [selectedMenuPost, setSelectedMenuPost] = useState(null);
  const bottomSheetRef = useRef(null);
  
  // Validating the type parameter
  useEffect(() => {
    if (type !== 'liked' && type !== 'saved') {
      navigate('/'); // Redirect to home if invalid type
      toast.error('Invalid post type specified');
    }
  }, [type, navigate]);
  
  // Fetch initial posts/shorts based on type and active tab
  useEffect(() => {
    try {
      if (type === 'liked' || type === 'saved') {
        setPage(1);
        setPosts([]);
        setHasMore(true);
        fetchPosts(1, true);
      }
    } catch (err) {
      console.error("Failed to initialize posts:", err);
      setError("Failed to load content. Please try refreshing the page.");
      setRenderError(true);
    }
  }, [type, activeTab]);
  
  // Fetch posts function
  const fetchPosts = async (pageNum = 1, isInitialFetch = false) => {
    try {
      if (isInitialFetch) {
        setInitialLoading(true);
      } else {
        setLoadingMore(true);
      }
      
      setError(null);
      
      const response = await axios.get(`${api}/post/user-posts`, {
        params: {
          type: type, // 'liked' or 'saved' from URL params
          isShort: activeTab, // false for posts, true for shorts
          page: pageNum,
          limit: 10
        },
        withCredentials: true
      });
      
      if (response.data && response.data.posts) {
        if (pageNum === 1) {
          // Initial fetch - replace existing posts
          setPosts(response.data.posts);
        } else {
          // Load more - append to existing posts
          setPosts(prev => [...prev, ...response.data.posts]);
        }
        
        // Update pagination state
        setHasMore(response.data.pagination.hasMore);
        
        // Process interaction states
        const newLikedPosts = {};
        const newSavedPosts = {};
        
        response.data.posts.forEach(post => {
          if (post.userInteraction) {
            newLikedPosts[post.id] = post.userInteraction.liked || false;
            newSavedPosts[post.id] = post.userInteraction.saved || false;
          }
        });
        
        setLikedPosts(prev => ({...prev, ...newLikedPosts}));
        setSavedPosts(prev => ({...prev, ...newSavedPosts}));
      } else {
        setPosts([]);
        setHasMore(false);
      }
    } catch (error) {
      console.error(`Error fetching ${type} posts:`, error);
      setError(`Failed to load ${type} posts. Please try again.`);
      setPosts([]);
      setHasMore(false);
    } finally {
      setInitialLoading(false);
      setLoadingMore(false);
    }
  };
  
  // Load more posts when user scrolls to the bottom
  const lastElementRef = useCallback((node) => {
    if (initialLoading || loadingMore) return;
    
    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    observerRef.current = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && hasMore) {
        const nextPage = page + 1;
        setPage(nextPage);
        fetchPosts(nextPage, false);
      }
    });

    if (node) {
      observerRef.current.observe(node);
    }
  }, [loadingMore, initialLoading, hasMore, page]);
  
  // Handle tab change
  const handleTabChange = (isShortTab) => {
    setActiveTab(isShortTab);
    setPage(1);
    setPosts([]);
    setHasMore(true);
  };
  
  // Handle image clicks
  const handleImageClick = (e, media, index) => {
    e.stopPropagation();
    if (media && media.type !== 'video') {
      setViewingImage(media);
      setImageIndex(index);
    }
  };
  
  // Close image viewer
  const closeImageViewer = () => {
    setViewingImage(null);
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
  
  // Navigate between images in a post
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

  const videoStates = useRef({});
  const globalUnmuteState = useRef(false);
  const [globalMuted, setGlobalMuted] = useState(true);

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
          setManuallyPaused(videoKey, false);
          setPlayingVideos(prev => ({ ...prev, [videoKey]: true }));
          setVideoOverlays(prev => ({ 
            ...prev, 
            [videoKey]: 'play' 
          }));
          setTimeout(() => {
            setVideoOverlays(prev => ({
              ...prev,
              [videoKey]: null
            }));
          }, 800);
        }).catch(err => {
          console.error('Error playing video:', err);
          if (!videoElement.muted) {
            videoElement.muted = true;
            videoElement.play().catch(e => console.error('Failed to play even with mute:', e));
          }
        });
      }
    } else {
      // Pause the video
      videoElement.pause();
      setManuallyPaused(videoKey, true);
      setPlayingVideos(prev => ({ ...prev, [videoKey]: false }));
      setVideoOverlays(prev => ({ 
        ...prev, 
        [videoKey]: 'pause' 
      }));
      setTimeout(() => {
        setVideoOverlays(prev => ({
          ...prev,
          [videoKey]: null
        }));
      }, 800);
    }
    
    // --- Always hide controls, even on small screens ---
    videoElement.controls = false;
    
    // Store current mute state
    videoStates.current[videoKey] = { muted: videoElement.muted };
  };

  // Effect to handle automatic video playback - always respect global mute setting
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
          // --- Remove controls for all screens ---
          targetVideo.muted = userInteracted ? (videoStates.current[mostVisibleVideo]?.muted ?? globalMuted) : globalMuted;
          targetVideo.controls = false; // Always hide controls
          const playPromise = targetVideo.play();
          if (playPromise !== undefined) {
            playPromise.catch(() => {
              targetVideo.muted = true;
              targetVideo.play().catch(() => {});
            });
          }
          setPlayingVideos(prev => ({ ...prev, [mostVisibleVideo]: true }));
        }
      }
    }
  }, [mostVisibleVideo, hasUserInteracted, videoRefs, isManuallyPaused, isTouchDevice, globalMuted]);

  // Update all video elements when global mute state changes
  useEffect(() => {
    const videoElements = document.querySelectorAll('video');
    videoElements.forEach(video => {
      if (!video.paused) {
        video.muted = globalMuted;
      }
    });
  }, [globalMuted]);

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
  
  const handleCarouselIndexChange = (postId, newIndex) => {
    setShortMediaIndexes(prev => ({
      ...prev,
      [postId]: newIndex
    }));
  };
  
  const goToPrevShortMedia = (postId, e) => {
    if (e) e.stopPropagation();
    
    // Get current index
    const currentIndex = shortMediaIndexes[postId] || 0;
    if (currentIndex === 0) return;
    
    // Update state FIRST - this is key
    const newIndex = currentIndex - 1;
    setShortMediaIndexes({
      ...shortMediaIndexes,
      [postId]: newIndex
    });
    
    // Then handle visual feedback with requestAnimationFrame
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 100);
      });
    }
  };
  useEffect(() => {
    setGlobalMuted(false);
  }, []);
  const goToNextShortMedia = (postId, mediaLength, e) => {
    if (e) e.stopPropagation();
    
    // Get current index
    const currentIndex = shortMediaIndexes[postId] || 0;
    if (currentIndex >= mediaLength - 1) return;
    
    // Update state FIRST - this is key
    const newIndex = currentIndex + 1;
    setShortMediaIndexes({
      ...shortMediaIndexes,
      [postId]: newIndex
    });
    
    // Then handle visual feedback with requestAnimationFrame
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 100);
      });
    }
  };
  
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
  
  const handleShortTouchStart = useRef({ x: 0, postId: null });
  const handleShortTouchEnd = useRef({ x: 0, postId: null });
  
  const handleLikeToggle = (postId, e) => {
    if (e) e.stopPropagation();
    
    // Early return if offline
    if (!navigator.onLine) {
      toast.warning("You're offline. This action will be available when you're back online.");
      return;
    }
    
    // Find the post first to avoid using undefined variables later
    const post = posts.find(p => p.id === postId);
    if (!post) {
      console.error(`Post with id ${postId} not found`);
      return;
    }
    
    // Visual feedback animation
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => {
          if (e.currentTarget) {
            e.currentTarget.classList.remove('scale-90');
          }
        }, 150);
      });
    }
    
    const postIdStr = postId.toString();
    
    // Remember the ORIGINAL liked state
    const originalLiked = likedPosts[postId] || false;
    const newLiked = !originalLiked;
    
    // Get the original count from the post object
    const originalCount = post?.likes || 0;
      // If this is a like action (not unlike), show a simple upvote animation
    if (newLiked) {
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
    
    // Update visual state
    visualState.current.likedPosts[postIdStr] = newLiked;
    
    // Calculate the visual delta
    const visualDelta = newLiked !== originalLiked 
      ? (newLiked ? 1 : -1) 
      : 0;
    
    // Update local state immediately (optimistic update)
    setLikedPosts(prev => ({
      ...prev,
      [postId]: newLiked
    }));
    
    // Update post like count in the posts array
    setPosts(prev => 
      prev.map(p => 
        p.id === postId 
          ? { 
              ...p, 
              likes: Math.max(0, originalCount + visualDelta)
            }
          : p
      )
    );
    
    // Additional direct DOM updates for buttons with data-like-button attribute
    try {
      const likeButtons = document.querySelectorAll(`[data-like-button="${postId}"]`);
      likeButtons.forEach(button => {
        // Update icon
        const emptyHeart = button.querySelector('.empty-heart');
        const filledHeart = button.querySelector('.filled-heart');
        
        if (emptyHeart && filledHeart) {
          emptyHeart.style.display = newLiked ? 'none' : 'block';
          filledHeart.style.display = newLiked ? 'block' : 'none';
        }
        
        // Update count based on original count + visual delta
        const countSpan = button.querySelector('span');
        if (countSpan) {
          countSpan.textContent = Math.max(0, originalCount + visualDelta).toString();
        }
      });
    } catch (error) {
      console.log("DOM update error:", error);
    }
    
    // Debounce the API call
    if (pendingLikeOperations.current.has(postIdStr)) {
      clearTimeout(pendingLikeOperations.current.get(postIdStr));
    }
    
    const timerId = setTimeout(() => {
      // Make direct axios call with explicit action parameter
      axios.post(
        `${api}/user-interactions/like/${postId}`,
        { action: newLiked ? 'like' : 'unlike' }, // CRITICAL: explicit action parameter
        { withCredentials: true }
      )
      .catch(error => {
        console.error("Error updating like status:", error);
        // Revert UI state on error
        setLikedPosts(prev => ({
          ...prev,
          [postId]: originalLiked
        }));
        
        // Also revert the post like count
        setPosts(prev => 
          prev.map(p => 
            p.id === postId 
              ? { 
                  ...p, 
                  likes: originalCount
                }
              : p
          )
        );
        
        try {
          // Update visual buttons on error
          const likeButtons = document.querySelectorAll(`[data-like-button="${postId}"]`);
          likeButtons.forEach(button => {
            const emptyHeart = button.querySelector('.empty-heart');
            const filledHeart = button.querySelector('.filled-heart');
            
            if (emptyHeart && filledHeart) {
              emptyHeart.style.display = originalLiked ? 'none' : 'block';
              filledHeart.style.display = originalLiked ? 'block' : 'none';
            }
            
            // Update count on error
            const countSpan = button.querySelector('span');
            if (countSpan) {
              countSpan.textContent = originalCount.toString();
            }
          });
        } catch (error) {
          console.log("DOM revert error:", error);
        }
        
        // Reset visual state ref
        visualState.current.likedPosts[postIdStr] = originalLiked;
        
        toast.error("Failed to update like status");
      });
      
      pendingLikeOperations.current.delete(postIdStr);
    }, 400);
    
    pendingLikeOperations.current.set(postIdStr, timerId);
  };
  const handleSaveToggle = (postId, e) => {
    if (e) e.stopPropagation();
    
    // Early return if offline
    if (!navigator.onLine) {
      toast.warning("You're offline. This action will be available when you're back online.");
      return;
    }
    
    // Visual feedback animation
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => {
          if (e.currentTarget) {
            e.currentTarget.classList.remove('scale-90');
          }
        }, 150);
      });
    }
    
    const postIdStr = postId.toString();
    
    // Remember the ORIGINAL saved state
    const originalSaved = savedPosts[postId] || false;
    
    // TOGGLE the local visual state
    const newSaved = !originalSaved;
    visualSavedState.current[postIdStr] = newSaved;
    
    // Update local state immediately (optimistic update)
    setSavedPosts(prev => ({
      ...prev,
      [postId]: newSaved
    }));
    
    // Additional direct DOM updates for buttons
    const saveButtons = document.querySelectorAll(`[data-save-button="${postId}"]`);
    saveButtons.forEach(button => {
      // Update icon
      const emptyBookmark = button.querySelector('.empty-bookmark');
      const filledBookmark = button.querySelector('.filled-bookmark');
      
      if (emptyBookmark && filledBookmark) {
        emptyBookmark.style.display = newSaved ? 'none' : 'block';
        filledBookmark.style.display = newSaved ? 'block' : 'none';
      }
    });
    
    // Debounce API call
    if (pendingSaveOperations.current.has(postIdStr)) {
      clearTimeout(pendingSaveOperations.current.get(postIdStr));
    }
    
    const timerId = setTimeout(() => {
      // Make direct axios call with explicit action parameter
      axios.post(
        `${api}/user-interactions/save/${postId}`,
        { action: newSaved ? 'save' : 'unsave' }, // CRITICAL: explicit action parameter
        { withCredentials: true }
      )
      .then(response => {
        if (response.data && response.data.success) {
          // Optional toast notification
          if (newSaved) {
            toast.success("Post saved successfully");
          } else {
            toast.success("Post unsaved successfully");
          }
        }
      })
      .catch(error => {
        console.error("Error saving post:", error);
        // Revert UI state on error
        setSavedPosts(prev => ({
          ...prev,
          [postId]: originalSaved
        }));
        
        // Update visual buttons on error
        saveButtons.forEach(button => {
          const emptyBookmark = button.querySelector('.empty-bookmark');
          const filledBookmark = button.querySelector('.filled-bookmark');
          
          if (emptyBookmark && filledBookmark) {
            emptyBookmark.style.display = originalSaved ? 'none' : 'block';
            filledBookmark.style.display = originalSaved ? 'block' : 'none';
          }
        });
        
        // Reset visual state ref
        visualSavedState.current[postIdStr] = originalSaved;
        
        toast.error("Failed to update saved status");
      });
      
      pendingSaveOperations.current.delete(postIdStr);
    }, 400);
    
    pendingSaveOperations.current.set(postIdStr, timerId);
  };
  
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
  
  const handleToggleMenu = (postId, e) => {
    e.stopPropagation();
    
    // Toggle menu visibility for the post
    if (activeMenu === postId) {
      setActiveMenu(null);
      return;
    }
    
    // Regular posts use dropdown position calculation
    if (!activeTab) {
      // Get the position of the clicked button
      const buttonRect = e.currentTarget.getBoundingClientRect();
      
      // Calculate menu position - fixed for both dimensions
      if (window.innerWidth < 768) {
        // Mobile: position at button level but right-aligned
        setMenuPosition({
          top: buttonRect.top, // Keep at the same vertical level
          left: window.innerWidth - 192, // Right align the menu (192px = menu width)
        });
      } else {
        // Desktop: position at button level, with right edge aligned to button right edge
        setMenuPosition({
          top: buttonRect.top, // Keep at the same vertical level
          left: buttonRect.right - 192, // Align right edges
        });
      }
    }
    
    // Set the active menu to this post
    setActiveMenu(postId);
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
  
  // Function to determine if the current user is the post owner
  const isPostOwner = (post) => {
    return currentUser && post.author && currentUser.id === post.author.id;
  };
  
  // Add delete post handler
  const handleDeletePost = (postId, e) => {
    if (e) e.stopPropagation();
    
    // Find the post to get its title
    const post = posts.find(p => p.id === postId);
    if (!post) return;
    
    // Open the confirmation modal
    setDeleteConfirmation({
      isOpen: true,
      postId: postId,
      postTitle: post.title || post.content?.substring(0, 30) || 'this post'
    });
    
    setActiveMenu(null); // Close the menu
  };
  
  // Confirm delete post function
  const confirmDeletePost = async () => {
    if (!deleteConfirmation.postId || isDeleting) return;
    
    setIsDeleting(true);
    
    try {
      await axios.delete(`${api}/post/${deleteConfirmation.postId}`, {
        withCredentials: true
      });
      
      // Remove post from UI
      setPosts(prev => prev.filter(post => post.id !== deleteConfirmation.postId));
      
      toast.success("Post deleted successfully");
    } catch (error) {
      console.error("Error deleting post:", error);
      toast.error("Failed to delete post. Please try again.");
    } finally {
      setIsDeleting(false);
      setDeleteConfirmation({
        isOpen: false,
        postId: null,
        postTitle: ''
      });
    }
  };
  
  // Cancel delete post function
  const cancelDeletePost = () => {
    setDeleteConfirmation({
      isOpen: false,
      postId: null,
      postTitle: ''
    });
  };
  
  // Add report post handler
  const handleReportPost = (postId, e) => {
    if (e) e.stopPropagation();
    
    setReportType('post');
    setReportTargetId(postId);
    setShowReportWidget(true);
    setActiveMenu(null); // Close the menu
  };
  
  // Add report user handler
  const handleReportUser = (userId, e) => {
    if (e) e.stopPropagation();
    
    setReportType('user');
    setReportTargetId(userId);
    setShowReportWidget(true);
    setActiveMenu(null); // Close the menu
  };
  
  // Close menu on scroll
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
      window.removeEventListener('scroll', handleScroll);
    };
  }, [activeMenu]);
  
  // Preload adjacent media for shorts
  useEffect(() => {
    // Preload images for shorts to make navigation feel instant
    Object.entries(shortMediaIndexes).forEach(([postId, currentIndex]) => {
      // Find the post that matches this postId
      const post = posts.find(p => p.id === postId);
      
      if (post?.media && post.media.length > 1) {
        // Only preload if there are multiple media items
        const prevIndex = currentIndex === 0 ? post.media.length - 1 : currentIndex - 1;
        const nextIndex = currentIndex === post.media.length - 1 ? 0 : currentIndex + 1;
        
        // Preload previous and next images (skip videos)
        if (post.media[prevIndex]?.type === 'image') {
          const prevImg = new Image();
          prevImg.src = `${cloud}/cloudofscubiee/${activeTab ? 'shortImages' : 'postImages'}/${post.media[prevIndex].url}`;
        }
        
        if (post.media[nextIndex]?.type === 'image') {
          const nextImg = new Image();
          nextImg.src = `${cloud}/cloudofscubiee/${activeTab ? 'shortImages' : 'postImages'}/${post.media[nextIndex].url}`;
        }
      }
    });
  }, [shortMediaIndexes, posts, activeTab]);
  
  // Clean up any pending timers when component unmounts
  useEffect(() => {
    return () => {
      pendingLikeOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
    };
  }, []);
  
  // Click outside handlers
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Check for menu click outside
      if (activeMenu !== null && !event.target.closest('[data-more-button="true"]') && 
          !event.target.closest('.menu-container')) {
        setActiveMenu(null);
      }
      
      // Check for delete confirmation click outside
      if (deleteConfirmation.isOpen && !event.target.closest('.delete-confirmation-container')) {
        // Optionally close delete confirmation on outside click
        // Commenting this out since most confirmation dialogs shouldn't close on outside click
        // cancelDeletePost();
      }
      
      // Check for report widget click outside
      if (showReportWidget && reportWidgetRef.current && 
          !reportWidgetRef.current.contains(event.target)) {
        setShowReportWidget(false);
      }
    };
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [activeMenu, deleteConfirmation.isOpen, showReportWidget]);
  
  // Add an effect to handle bottom sheet click outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (showBottomSheet && 
          bottomSheetRef.current && 
          !bottomSheetRef.current.contains(event.target)) {
        setShowBottomSheet(false);
      }
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showBottomSheet]);
  
  // Loading skeletons
  const ContentLoadingSkeleton = () => (
    <div className="space-y-3 w-full my-4 mb-16 max-w-[640px]">
      {Array(3).fill().map((_, index) => (
        <div key={index} className="w-full">
          <Skeleton height={300} className="rounded-xl" />
        </div>
      ))}
    </div>
  );
  
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

  const renderMenu = (postId) => {
    if (activeMenu !== postId) return null;
    
    return (
      <Portal>
        <div 
          className="fixed w-48 font-medium bg-[#0f0f0f] border border-gray-700 rounded-md shadow-lg z-[1000] menu-container"
          style={{
            top: `${menuPosition.top}px`,
            left: `${menuPosition.left}px`,
            maxHeight: '90vh',
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* ...menu content... */}
        </div>
      </Portal>
    );
  };

  if (renderError) {
    return (
      <div className="min-h-screen max-w-[650px] mx-auto py-10 flex flex-col items-center justify-center text-white">
        <div className="bg-[#111111] p-6 rounded-xl text-center max-w-md">
          <h2 className="text-xl font-semibold mb-3">Something went wrong</h2>
          <p className="mb-4 text-gray-300">{error || "Failed to load content. Please try again."}</p>
          <button 
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-md text-white"
          >
            Refresh Page
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen max-w-[650px]  mx-auto  text-white font-sans" ref={pageRef}>
      {/* Header with Back Button */}
      <div className="sticky top-0   z-10 bg-[#0a0a0a] py-4 max-md:py-2 px-4 flex items-center">
      <button 
  onClick={() => navigate(currentUser?.username ? `/${currentUser.username}` : '/')}
  className="text-white mr-4 cursor-pointer"
>
  <BiArrowBack size={24} />
</button>
        <h1 className="text-xl  font-bold">
          {type === 'liked' ? 'Posts You\'ve Liked' : 'Posts You\'ve Saved'}
        </h1>
      </div>
      
      {/* Content */}
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
        {/* Content */}
        <div className="space-y-2 md:space-y-3 w-full my-4 mb-16 max-w-[640px]">
          {initialLoading ? (
            <SkeletonTheme baseColor="#202020" highlightColor="#444">
              {activeTab ? <ShortsLoadingSkeleton /> : <ContentLoadingSkeleton />}
            </SkeletonTheme>
          ) : posts.length > 0 ? (
            activeTab ? (
              // Shorts section
              posts.map((post, index) => (
                <article 
                  key={post.id}
                  ref={index === posts.length - 1 ? lastElementRef : null}
                  className="relative max-md:mx-4 flex justify-center bg-[#111111] 
                    w-full max-w-sm mx-auto h-[94vh] md:max-h-[650px] border-[1px] border-gray-800 
                    bg-card rounded-xl overflow-hidden"
                  onTouchMove={(e) => handleShortTouchMove(e, post.id, post.media?.length || 0)}
                >
                  {/* Content container */}
                  <div className="w-full h-full relative flex flex-col">
                    {/* Media Section - Top 40% */}
                    <div className="w-[100%] rounded-2xl h-[50%] relative">
                      {post.media && post.media.length > 0 ? (
                        <ShortMediaCarousel
                          media={post.media}
                          postId={post.id}
                          currentIndex={shortMediaIndexes[post.id] || 0}
                          autoPlay={false}
                          isRedux={false}
                          onIndexChange={handleCarouselIndexChange}
                          api={api}
                          videoRef={(el) => {
                            if (el) {
                              const videoKey = `short-${post.id}`;
                              registerVideo(videoKey, el);
                            }
                          }}
                          videoKey={`short-${post.id}`}
                          onVideoPlay={(videoElement) => {
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
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center bg-gray-900 rounded-2xl">
                          <p className="text-gray-500">No media available</p>
                        </div>
                      )}
                    </div>
                
                    {/* Content area - Bottom 60% */}
                    <div className="absolute top-[52%] left-0 w-full h-[46%] flex flex-col">
                      {/* Text Content */}
                      <div className="relative flex-1 px-3 pr-11 text-gray-300 pb-16 overflow-y-scroll hide-scrollbar">
                        <p className="max-md mt-1">
                          {post.content}
                        </p>
                      </div>
                
                      {/* User Info - Fixed position at bottom */}
                      <div className="flex bg-[#111111] w-full absolute bottom-0 left-0 items-center justify-between px-4 pt-2">
                        <div className="flex items-center">
                          <img
                            src={post.author.profilePicture
                              ? `${cloud}/cloudofscubiee/profilePic/${post.author.profilePicture}`
                              : DefaultPicture}
                            alt={post.author.username}
                            className="w-9 h-9 bg-gray-300 rounded-full mr-3 object-cover"
                            onClick={() => navigate(`/profile/${post.author.username}`)}
                          />
                          <div>
                            <div className="flex items-center gap-1">
                              <h3 className="text-[15px] font-semibold">
                                {post.author.username}
                              </h3>
                              {!!post.author.verified && (
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
                      <div className="absolute h-fit right-3 bottom-3 flex flex-col items-center space-y-7">                        <button
                          onClick={(e) => handleLikeToggle(post.id, e)}
                          className="flex items-center gap-1 px-3 py-[4px] rounded-full border border-gray-500 transition-all duration-200 transform hover:scale-105 text-gray-300"
                          data-like-button={post.id}
                        >
                          <BiUpvote 
                            className="h-4 w-4 empty-heart" 
                            style={{display: likedPosts[post.id] ? 'none' : 'block'}} 
                          />
                          <BiSolidUpvote 
                            className="h-4 w-4 text-gray-300 filled-heart" 
                            style={{display: likedPosts[post.id] ? 'block' : 'none'}} 
                          />
                          <span className="text-sm font-medium">
                            {post.likes?.toLocaleString() || '0'}
                          </span>
                        </button>
                        
                        <button 
                          onClick={(e) => handleCommentClick(post.id, e)} 
                          className="text-white hover:text-gray-300"
                        >
                          <TfiCommentAlt size={20} />
                        </button>
                        
                        <button 
                          onClick={(e) => handleSharePost(post.id, e)} 
                          className="text-white hover:text-gray-300"
                        >
                          <BsSend size={20} />
                        </button>
                        
                        <button 
                          onClick={(e) => handleToggleMenu(post.id, e)} 
                          className="text-white hover:text-gray-300"
                          data-more-button="true"
                        >
                          <FiMoreVertical size={20} />
                        </button>
                      </div>
                
                      {/* Add Options Menu inside the card (replaces bottom sheet) */}
                      {activeMenu === post.id && (
  <div 
    className="absolute z-50 bg-[#111111] border-t-2 border-gray-800 
      rounded-t-2xl h-[110px] left-0 right-0 bottom-0
      transform transition-transform duration-300 ease-in-out animate-slide-up menu-container"
    onClick={(e) => {
      e.preventDefault();
      e.stopPropagation();
    }}
  >
    <div className="w-12 h-1 bg-gray-600 mx-auto mt-3 rounded-full"></div>
    <div 
      className="h-full w-full p-4 flex items-center justify-center space-x-20"
      onClick={(e) => e.stopPropagation()}
    >
      <div 
        className="flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        {isPostOwner(post) ? (
          <>
            <button 
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                handleDeletePost(post.id, e);
              }}
              className="text-red-700 border-[1px] p-2 rounded-full border-gray-700 hover:scale-105 mb-1" 
              title="Delete"
            >
              <MdOutlineDeleteOutline size={26} />
            </button>
            <span 
              className="text-gray-300 text-xs font-sans"
              onClick={(e) => e.stopPropagation()}
            >
              Delete
            </span>
          </>
        ) : (
          <>
            <button 
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                handleReportPost(post.id, e);
              }}
              className="text-red-700 border-[1px] p-2 rounded-full border-gray-700 hover:scale-105 mb-1" 
              title="Report"
            >
              <MdOutlineReport size={32} />
            </button>
            <span 
              className="text-gray-300 text-xs font-sans"
              onClick={(e) => e.stopPropagation()}
            >
              Report
            </span>
          </>
        )}
      </div>

      <div 
        className="flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        <button 
          onClick={(e) => {
            e.stopPropagation();
            handleSaveToggle(post.id, e);
          }}
          className="text-white border-[1px] p-[13px] rounded-full border-gray-700 transition-transform duration-200 hover:scale-105 mb-1" 
          title="Save"
        >
          {savedPosts[post.id] ? <BsBookmarkFill size={21} /> : <BsBookmark size={21} />}
        </button>
        <span 
          className="text-gray-300 text-xs"
          onClick={(e) => e.stopPropagation()}
        >
          Save
        </span>
      </div>

      <div 
        className="flex flex-col items-center"
        onClick={(e) => e.stopPropagation()}
      >
        <button 
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            handleCopyLink(post.id);
            setActiveMenu(null);
          }}
          className="text-white border-[1px] p-3 rounded-full border-gray-700 hover:scale-105 mb-1"  
          title="Copy Link"
        >
          <MdOutlineContentCopy size={24} />
        </button>
        <span 
          className="text-gray-300 text-xs"
          onClick={(e) => e.stopPropagation()}
        >
          Copy
        </span>
      </div>
    </div>
  </div>
)}
                    </div>
                  </div>
                </article>
              ))
            ) : (
              // Regular posts section
              posts.map((post, index) => (
                <article
                  key={post.id}
                  ref={index === posts.length - 1 ? lastElementRef : null}
                  className="overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818] bg-[#0a0a0a] md:bg-[#0c0c0c] backdrop-blur-sm py-2 max-md:py-2 max-md:px-[4px] text-gray-300"
                >
                  {/* Post Header */}
                  <div className="flex items-center justify-between mb-3 px-3 max-md:px-2">
                    <div className="flex items-center gap-3 max-md:ml-[6px] pt-1 md:pt-2">
                      <div 
                        className="relative h-10 w-10 max-md:h-[36px] max-md:w-[36px] rounded-full overflow-hidden group cursor-pointer"
                        onClick={() => navigate(`/profile/${post.author.username}`)}
                      >
                        <img
                          src={post.author.profilePicture
                            ? `${cloud}/cloudofscubiee/profilePic/${post.author.profilePicture}`
                            : DefaultPicture}
                          alt={post.author.username}
                          className="w-full h-full bg-gray-300 object-cover transition-transform duration-200 group-hover:scale-110"
                        />
                        <div className="absolute inset-0 bg-black/10 group-hover:bg-black/0 transition-colors duration-200"></div>
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
                        className="text-gray-400 hover:text-white p-1 rounded-full hover:bg-gray-800/30 transition-colors duration-200" 
                        onClick={(e) => handleToggleMenu(post.id, e)}
                        data-more-button="true"
                      >
                        <FiMoreVertical className="h-[19px] w-[19px]" />
                      </button>
                      
                      {renderMenu(post.id)}
                    </div>
                  </div>

                  {/* Post Content */}
                  <div 
                    className="pr-4 pl-4 max-md:px-2 cursor-pointer"
                    onClick={() => navigate(`/viewpost/${post.id}`)}
                  >
                    {/* Text Content */}                    {(post.title || post.content || post.description) && (
                       <div className="mb-[10px] max-md:ml-2 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2">
                        <SmartTruncateText
                          text={post.title || post.content || post.description}
                          className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-semibold"
                        />
                      </div>
                    )}

                    {/* Media Content */}
                    {post.media && post.media.length > 0 && (
                      <div className="relative mb-4 xl:w-[84%] md:w-[90%] mx-auto w-full">                        {/* Single media item - full width for both mobile and desktop */}
                        {post.media.length === 1 ? (                          <div className="relative mb-4">
                            <div className="max-md:w-[93%] max-md:mx-auto w-[98%] mx-auto" style={{ maxHeight: '550px' }}>
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
                          /* Multiple media - carousel for both mobile and desktop */
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
                    <button 
                      className={`flex items-center gap-1 px-3 py-[4px] rounded-full border transition-all duration-200 transform hover:scale-105 ${
                        likedPosts[post.id] 
                          ? ' border-gray-500 bg-white/05 text-gray-200' 
                          : 'border-gray-500 bg-white/05 text-gray-300 '
                      }`}
                      onClick={(e) => handleLikeToggle(post.id, e)}
                      data-like-button={post.id}
                    >
                      <BiUpvote 
                        className="h-4 w-4 empty-heart" 
                        style={{display: likedPosts[post.id] ? 'none' : 'block'}} 
                      />
                      <BiSolidUpvote 
                        className="h-4 w-4 text-gray-300 filled-heart" 
                        style={{display: likedPosts[post.id] ? 'block' : 'none'}} 
                      />
                      <span className='text-sm font-medium'>
                        {post.likes?.toLocaleString() || '0'}
                      </span>
                    </button>

                    {/* Comment Button */}
                    <button 
                      className="flex items-center gap-2 text-gray-300 ml-6 group"
                      onClick={(e) => handleCommentClick(post.id, e)}
                    >
                      <div className="p-1.2 rounded-full transition-colors duration-200">
                        <TfiCommentAlt className="mt-[1px] h-[18px] w-[18px]  transition-colors duration-200" />
                      </div>
                      <span className='text-[14px] mt-[-1px]  transition-colors duration-200'>
                        {(post.comments > 0) ? post.comments : '0'}
                      </span>
                    </button>

                    {/* Share Button */}
                    <button 
                      className="flex items-center text-gray-300 ml-auto group"
                      onClick={(e) => handleSharePost(post.id, e)}
                    >
                      <div className="p-1.5 rounded-full transition-colors duration-200">
                        <BsSend className="h-[18px] w-[18px]  transition-colors duration-200" />
                      </div>
                    </button>

                    {/* Save Button */}
                    <button 
                      className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
                      onClick={(e) => handleSaveToggle(post.id, e)}
                      data-save-button={post.id}
                    >
                      <div className="p-1.5 rounded-full transition-colors duration-200">
                        <BsBookmark 
                          className="h-[18px] w-[18px] empty-bookmark" 
                          style={{display: savedPosts[post.id] ? 'none' : 'block'}} 
                        />
                        <BsBookmarkFill 
                          className="h-[18px] w-[18px] text-white group-hover:text-gray-200 filled-bookmark" 
                          style={{display: savedPosts[post.id] ? 'block' : 'none'}} 
                        />
                      </div>
                    </button>
                  </div>
                </article>
              ))
            )
          ) : (
            // No posts found
            <div className="text-center py-10">
              <p className="text-gray-400">
                No {activeTab ? 'shorts' : 'posts'} found that you've {type === 'liked' ? 'liked' : 'saved'}.
              </p>
            </div>
          )}
          
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
        </div>
      </div>
      
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
            
            {/* Navigation arrows */}
            {viewingImage.postMedia && viewingImage.postMedia.filter(media => media.type !== 'video').length > 1 && (
              <>
                <button 
                  className="absolute max-md:hidden md:left-[-50px] left-2 top-1/2 transform -translate-y-1/2 bg-white/10 md:p-2 p-1 rounded-full z-10"
                  onClick={(e) => navigateImages(e, -1, viewingImage.postMedia)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="md:h-6 md:w-6 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7" />
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
      
      {/* Comment Widget */}
      {isCommentOpen && (
        <CommentWidget
          postId={CommentPostId}
          isOpen={isCommentOpen}
          onClose={() => dispatch(setIsCommentOpen(false))}
        />
      )}

      {/* Share Widget */}
      {showShareWidget && (
        <ShareDialog 
          postId={sharePostId}
          onClose={() => setShowShareWidget(false)}
        />
      )}
      
      {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">Link copied</div>
          
        
      )}
      
      {/* Add Delete Confirmation Dialog */}
      {deleteConfirmation.isOpen && (
        <Portal>
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
            <div 
              className="bg-gradient-to-b from-[#222] to-[#111] p-6 rounded-xl w-[90%] max-w-[400px] shadow-2xl border border-gray-700 delete-confirmation-container"
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
                  onClick={cancelDeletePost}
                  className="px-5 py-2.5 bg-transparent border border-gray-600 hover:bg-gray-800 text-gray-200 rounded-full transition duration-200 font-medium"
                  disabled={isDeleting}
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDeletePost}
                  className="px-5 py-2.5 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-700 hover:to-red-800 rounded-full text-white transition duration-200 font-medium flex items-center"
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <>
                      <div className="mr-2 h-4 w-4 border-2 border-t-transparent border-white border-solid rounded-full animate-spin"></div>
                      Deleting...
                    </>
                  ) : (
                    <>
                      <MdOutlineDeleteOutline size={18} className="mr-1.5" />
                      Delete
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </Portal>
      )}

      {/* Add Report Widget */}
      {showReportWidget && (
        <Portal>
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
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
        </Portal>
      )}
    </div>
  );
};

export default UsersPosts;
