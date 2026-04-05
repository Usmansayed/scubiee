import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { Twitter, Instagram, Facebook, Github, Youtube } from "lucide-react";
import PostWidget from "../components/PostWidget";
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import Share from './Shorts';
import { RiDeleteBin6Line } from 'react-icons/ri'; 

import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import { toast } from 'react-toastify';
import CommentWidget from "../components/CommentWidget";
import { useDispatch, useSelector } from 'react-redux';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import ShareDialog from "../components/shareWidget";
import { MdOutlineReport, MdOutlineContentCopy } from "react-icons/md";
import { IoCloseSharp } from "react-icons/io5";
import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
import ShortMediaCarousel from '../components/ShortMediaCarousel';
import ReportWidget from "../components/ReportWidget";
import { useInteractionManager } from '../hooks';
import FollowsWidget from "../components/FollowsWidget";
import { createPortal } from 'react-dom';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted ? createPortal(children, document.body) : null;
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

// Custom hook to detect the most visible video in viewport
const useVideoAutoplay = (dependencies = []) => {
  const [mostVisibleVideo, setMostVisibleVideo] = useState(null);
  const videoRefs = useRef({});
  const observers = useRef({});
  const visibilityRatios = useRef({});
  const userInteracted = useRef({});
  const manuallyPaused = useRef({});  
  const firstClickHandled = useRef({});

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

const Profile = ({ username }) => {
  const [activeTab, setActiveTab] = useState(false);
  const [userProfile, setUserProfile] = useState({
    id: "",
    fullName: "",
    username: "",
    badges: [],
    bio: "",
    posts: 0,
    followers: 0,
    following: 0,
    socialLinks: {},
    profilePicture: "",
    coverImage: "",
    followedByMe: false,
  });

  console.log(userProfile);
  // Updated state management for posts and shorts
  const [userPosts, setUserPosts] = useState([]);
  const [userShorts, setUserShorts] = useState(null); // Start as null to indicate not loaded yet
  const [loading, setLoading] = useState(false);
  const [hasMorePosts, setHasMorePosts] = useState(true);
  const [hasMoreShorts, setHasMoreShorts] = useState(true);
  const [error, setError] = useState(null);
  
  const [selectedPost, setSelectedPost] = useState(null);
  const [showOptions, setShowOptions] = useState(false);
  const [selectedShort, setSelectedShort] = useState(null);
  const navigate = useNavigate();
  const widgetRef = useRef(null);
  const observerRef = useRef(null);

  const DefaultPicture = "/logos/DefaultPicture.png"; // Path to Google SVG
  const DefaultCover = "/logos/DefualtCover.png"; // Path to Google SVG

  // Add separate loading states
  const [initialLoading, setInitialLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // Add this new state for content-specific loading
  const [contentLoading, setContentLoading] = useState(false);
  // Add this new state for profile not found error
  const [profileNotFound, setProfileNotFound] = useState(false);

  // Add these new states after existing state declarations
  const [likedPosts, setLikedPosts] = useState({});
  const [savedPosts, setSavedPosts] = useState({});
  const [activeMenu, setActiveMenu] = useState(null);
  const menuRef = useRef(null);
  const dispatch = useDispatch();
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [sharePostId, setSharePostId] = useState(null);
  const [CommentPostId, setCommentPostId] = useState(null);
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);

  // Add the bottomSheetRef for shorts menu
  const bottomSheetRef = useRef(null);
  
  // Add this ref for detecting scrolls
  const pageRef = useRef(null);

  // Add these new states for image viewing
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);

  // Add these state variables for media navigation
  const [shortMediaIndexes, setShortMediaIndexes] = useState({});

  // Add state to track video overlay icons
  const [videoOverlays, setVideoOverlays] = useState({});

  // Replace the current media navigation functions with these optimized versions:  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

  // Add state for copy notification
  const [showCopyNotification, setShowCopyNotification] = useState(false);

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  // Add this useEffect for preloading adjacent media
  useEffect(() => {
    // Preload images for shorts to make navigation feel instant
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

  // Add this new state for video playback
  const [playingVideos, setPlayingVideos] = useState({});

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

    // STRICT ENFORCEMENT: Always pause all other videos first
    const allVideos = document.querySelectorAll('video');
    allVideos.forEach(v => {
      if (v !== videoElement && !v.paused) {
        v.pause();
        const container = v.closest('.video-container');
        if (container && container.dataset.videoId) {
          const videoId = container.dataset.videoId;
          setPlayingVideos(prev => ({ ...prev, [videoId]: false }));
          setManuallyPaused(videoId, true); // Mark as manually paused to prevent auto-resume
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

  // Effect to handle automatic video playback - always respect global mute setting
  useEffect(() => {
    // STRICTLY enforce only one video playing at a time by first pausing ALL videos
    const videoElements = document.querySelectorAll('video');
    
    // First pass: Pause all videos that aren't the most visible one
    videoElements.forEach(video => {
      const videoContainer = video.closest('.video-container');
      if (!videoContainer) return;
      
      const videoId = videoContainer.dataset.videoId;
      // Always pause videos that aren't the most visible, regardless of user interaction
      if (videoId !== mostVisibleVideo) {
        if (!video.paused) {
          video.pause();
          setPlayingVideos && setPlayingVideos(prev => ({ ...prev, [videoId]: false }));
        }
      }
    });
    
    // Second pass: Only play the most visible video if it exists and wasn't manually paused
    if (mostVisibleVideo && videoRefs && videoRefs.current) {
      const targetVideo = videoRefs.current[mostVisibleVideo];
      if (targetVideo) {
        const wasManuallyPaused = isManuallyPaused(mostVisibleVideo);
        if (!wasManuallyPaused) {
          const userInteracted = hasUserInteracted(mostVisibleVideo);
          
          if (isTouchDevice) {
            targetVideo.muted = globalMuted;
            targetVideo.controls = true;
            globalUnmuteState.current = !globalMuted;
            targetVideo.play().catch(() => {
              if (!globalMuted) {
                targetVideo.muted = true;
                targetVideo.play().catch(() => {});
              }
            });
          } else {
            targetVideo.muted = userInteracted ? (videoStates.current[mostVisibleVideo]?.muted ?? globalMuted) : globalMuted;
            targetVideo.controls = userInteracted;
            const playPromise = targetVideo.play();
            if (playPromise !== undefined) {
              playPromise.catch(() => {
                targetVideo.muted = true;
                targetVideo.play().catch(() => {});
              });
            }
          }
          setPlayingVideos && setPlayingVideos(prev => ({ ...prev, [mostVisibleVideo]: true }));
        }
      }
    }
    
    // Add a final check after a small delay to ensure only one video is playing
    const enforceOnlyOneVideoPlaying = setTimeout(() => {
      let playingVideoFound = false;
      videoElements.forEach(video => {
        if (!video.paused) {
          if (playingVideoFound) {
            // More than one video is playing - pause this one
            video.pause();
            const container = video.closest('.video-container');
            if (container && container.dataset.videoId) {
              setPlayingVideos(prev => ({ ...prev, [container.dataset.videoId]: false }));
            }
          }
          playingVideoFound = true;
        }
      });
    }, 100);
    
    return () => {
      clearTimeout(enforceOnlyOneVideoPlaying);
    };
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
  // --- END VIDEO AUTOPLAY LOGIC ---

  // Add these new states and refs for follow functionality
  const [followLoading, setFollowLoading] = useState(false);
  const pendingFollowOperation = useRef(null);
  const visualFollowState = useRef(null);

  // Add these new states for follows widget
  const [showFollowsWidget, setShowFollowsWidget] = useState(false);
  const [followsWidgetType, setFollowsWidgetType] = useState('followers');

  // Add these new state variables for the report widget
  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportType, setReportType] = useState(null);
  const [reportTargetId, setReportTargetId] = useState(null);
  const reportWidgetRef = useRef(null);

  // Fetch profile data
  useEffect(() => {
    const fetchProfileData = async () => {
      try {
        setInitialLoading(true); // Set loading state to true at the start
        const { data } = await axios.get(`${api}/user/profile-info`, {
          withCredentials: true,
          params: { username },
        });

        if (data.user) {
          setUserProfile({
            id: data.user.id,
            fullName: `${data.user.firstName} ${data.user.lastName}`,
            username: data.user.username,
            bio: data.user.Bio || "",
            posts: data.user.posts || 0,
            followers: data.user.followers || 0,
            following: data.user.following || 0,
            socialLinks: JSON.parse(data.user.SocialMedia || "{}"),
            profilePicture: data.user.profilePicture,
            coverImage: data.user.coverImage || "",
            followedByMe: data.user.followedByMe,
            verified: data.user.Verified,
            badges: data.user.badges || [], // Make sure badges are extracted here

          });
          setProfileNotFound(false); // Make sure we reset this if we successfully find the profile
        } else {
          // Profile data is empty or invalid
          console.error("Profile not found");
          setProfileNotFound(true);
          setInitialLoading(false);
        }
      } catch (error) {
        console.error("Error fetching profile data:", error);
        setError("Failed to load profile data");
        setProfileNotFound(true);
        setInitialLoading(false);
      }
    };
    
    if (username) {
      fetchProfileData();
    }
  }, [username]);

  // Initial fetch for regular posts only (not shorts)
  useEffect(() => {
    if (userProfile.id) {
      fetchInitialPosts();
    }
  }, [userProfile.id]);

  useEffect(() => {
    setGlobalMuted(false);
  }, []);

  // Fetch initial posts (regular posts only, not shorts)
  const fetchInitialPosts = async () => {
    try {
      // Don't set initialLoading again as it's already set to true from profile fetch
      setError(null);
      
      const response = await axios.get(
        `${api}/post/post/details/${userProfile.id}?isShort=false`,
        { withCredentials: true }
      );
      
      // If we have posts, initialize the like and save states from the response data
      if (response.data && response.data.length > 0) {
        const newLikedPosts = {};
        const newSavedPosts = {};
        
        response.data.forEach(post => {
          if (post.interactions) {
            newLikedPosts[post.id] = post.interactions.liked || false;
            newSavedPosts[post.id] = post.interactions.saved || false;
          }
        });
        
        setLikedPosts(prev => ({...prev, ...newLikedPosts}));
        setSavedPosts(prev => ({...prev, ...newSavedPosts}));
      }
      
      setUserPosts(response.data || []);
      // Only set hasMorePosts to true if we got exactly 9 items
      setHasMorePosts(response.data && response.data.length === 9);
      setInitialLoading(false); // Finally set loading to false after all data is loaded
    } catch (error) {
      console.error("Error fetching user's posts:", error);
      setUserPosts([]);
      setError("Failed to load posts");
      setInitialLoading(false);
    }
  };

  // Fetch shorts when tab is clicked and shorts haven't been loaded yet
  useEffect(() => {
    if (activeTab && userShorts === null && userProfile.id) {
      fetchShorts();
    }
  }, [activeTab, userShorts, userProfile.id]);

  // Fetch shorts
  const fetchShorts = async () => {
    try {
      if (loadingMore) return;
      
      // Use contentLoading instead of initialLoading here
      setContentLoading(true);
      setError(null);
      
      const response = await axios.get(
        `${api}/post/post/details/${userProfile.id}?isShort=true`,
        { withCredentials: true }
      );
      
      // Add similar interaction state initialization for shorts
      if (response.data && response.data.length > 0) {
        const newLikedPosts = {};
        const newSavedPosts = {};
        
        response.data.forEach(post => {
          if (post.interactions) {
            newLikedPosts[post.id] = post.interactions.liked || false;
            newSavedPosts[post.id] = post.interactions.saved || false;
          }
        });
        
        setLikedPosts(prev => ({...prev, ...newLikedPosts}));
        setSavedPosts(prev => ({...prev, ...newSavedPosts}));
      }
      
      setUserShorts(response.data || []);
      // Only set hasMoreShorts to true if we got exactly 9 items
      setHasMoreShorts(response.data && response.data.length === 9);
      setContentLoading(false); // Use contentLoading instead
    } catch (error) {
      console.error("Error fetching user's shorts:", error);
      setUserShorts([]);
      setError("Failed to load shorts");
      setContentLoading(false); // Use contentLoading instead
    }
  };

  // Fetch more posts or shorts
  const fetchMoreContent = async (isShort) => {
    try {
      // Don't load more if initial loading is in progress or if we're already loading more
      if (initialLoading || loadingMore) return;
      
      const contentArray = isShort ? userShorts : userPosts;
      
      // Don't load more if we don't have exactly 9 or more items (signifying there might be more)
      if (!contentArray || contentArray.length === 0 || contentArray.length % 9 !== 0) {
        return;
      }
      
      setLoadingMore(true);
      setError(null);

      const lastItemId = contentArray[contentArray.length - 1].id;

      const response = await axios.post(
        `${api}/post/more-posts`,
        { isShort, postId: lastItemId },
        { withCredentials: true }
      );

      if (response.data && response.data.posts) {
        const newLikedPosts = {};
        const newSavedPosts = {};
        
        response.data.posts.forEach(post => {
          if (post.interactions) {
            newLikedPosts[post.id] = post.interactions.liked || false;
            newSavedPosts[post.id] = post.interactions.saved || false;
          }
        });
        
        setLikedPosts(prev => ({...prev, ...newLikedPosts}));
        setSavedPosts(prev => ({...prev, ...newSavedPosts}));
        
        if (isShort) {
          setUserShorts(prevShorts => [...prevShorts, ...response.data.posts]);
          // Only set hasMore to true if we got exactly 9 new items
          setHasMoreShorts(response.data.posts.length === 9);
        } else {
          setUserPosts(prevPosts => [...prevPosts, ...response.data.posts]);
          // Only set hasMore to true if we got exactly 9 new items
          setHasMorePosts(response.data.posts.length === 9);
        }
      } else {
        // If no posts were returned, there are no more posts
        if (isShort) {
          setHasMoreShorts(false);
        } else {
          setHasMorePosts(false);
        }
      }
      
      setLoadingMore(false);
    } catch (error) {
      console.error(`Error fetching more ${isShort ? 'shorts' : 'posts'}:`, error);
      setError(`Failed to load more ${isShort ? 'shorts' : 'posts'}`);
      setLoadingMore(false);
      // If an error occurs, we can't determine if there are more posts
      // So we'll set hasMore to false to prevent further loading attempts
      if (isShort) {
        setHasMoreShorts(false);
      } else {
        setHasMorePosts(false);
      }
    }
  };

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
          fetchMoreContent(activeTab);
        }
      }
    });

    if (node) {
      observerRef.current.observe(node);
    }
  }, [loadingMore, initialLoading, activeTab, hasMorePosts, hasMoreShorts, userPosts?.length, userShorts?.length]);
  
  // Handle tab change
  const handleTabChange = (isShortTab) => {
    setActiveTab(isShortTab);
    
    // If switching to shorts tab and shorts haven't been loaded yet
    if (isShortTab && userShorts === null) {
      fetchShorts();
    }
  };

  const handleMessage = () => {
    // Navigate directly to the chat with this userId in the URL
    navigate(`/chat/${userProfile.id}`);
  };

  // Replace the existing follow/unfollow handlers with this combined function
  const handleFollowToggle = async () => {
    // Store current follow state before changing it
    const wasFollowing = userProfile.followedByMe;
    
    // Update UI immediately for better UX
    setUserProfile((prev) => ({
      ...prev,
      followedByMe: !prev.followedByMe,
      followers: prev.followedByMe ? prev.followers - 1 : prev.followers + 1,
    }));
    
    // Set visual loading state
    setFollowLoading(true);
    
    // Cancel any pending operation
    if (pendingFollowOperation.current) {
      clearTimeout(pendingFollowOperation.current);
    }
    
    // Store the current visual state to check later if it changed
    visualFollowState.current = !wasFollowing;
    
    // Debounce the API call
    pendingFollowOperation.current = setTimeout(async () => {
      try {
        if (!wasFollowing) {
          // Follow
          await axios.post(`${api}/user/follow/${userProfile.id}`, {}, {
            withCredentials: true,
          });
        } else {
          // Unfollow
          await axios.delete(`${api}/user/follow/${userProfile.id}`, {
            withCredentials: true,
          });
        }
        
        // Success - clean up
        pendingFollowOperation.current = null;
        visualFollowState.current = null;
        setFollowLoading(false);
      } catch (error) {
        console.error(`Error ${wasFollowing ? 'unfollowing' : 'following'} user:`, error);
        
        // Revert UI state on error only if the visual state hasn't changed again
        if (visualFollowState.current === !wasFollowing) {
          setUserProfile((prev) => ({
            ...prev,
            followedByMe: wasFollowing,
            followers: wasFollowing ? prev.followers + 1 : prev.followers - 1,
          }));
          visualFollowState.current = null;
          toast.error(`Failed to ${wasFollowing ? 'unfollow' : 'follow'} user. Please try again.`);
        }
        setFollowLoading(false);
      }
    }, 300); // 300ms debounce
  };

  // Handle short click
  // const handleShortClick = (shortId) => {
  //   setSelectedShort(shortId);
  // };

  useEffect(() => {
    const handleClickOutside = (event) => {
      // Close active menu when clicking outside
      if (activeMenu && menuRef.current && !menuRef.current.contains(event.target) && 
          // Make sure we're not clicking on the more button itself
          !event.target.closest('[data-more-button="true"]')) {
        setActiveMenu(null);
      }
      
      // We'll keep the widgetRef logic for other widgets but not for post display
      if (widgetRef.current && !widgetRef.current.contains(event.target)) {
        setShowOptions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [widgetRef, activeMenu]);

  // Add the interaction manager hook
  const { createLikeHandler, createSaveHandler } = useInteractionManager();
  const pendingLikeOperations = useRef(new Map());


  const handleLikeToggle = (postId, e) => {
    if (e) e.stopPropagation();
    
    // Early return if offline
    if (!navigator.onLine) {
      toast.warning("You're offline. Please try again when connected.");
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
    
    // Remember the ORIGINAL backend state
    const originalLiked = likedPosts[postId] || false;
    
    // Find the post to get its current like count
    const post = activeTab ? 
      userShorts.find(p => p.id === postId) : 
      userPosts.find(p => p.id === postId);
    
    const originalCount = post?.likes || 0;
    
    // TOGGLE the local visual state
    const hasVisualState = postIdStr in visualState.current.likedPosts;
    const currentVisualState = hasVisualState 
      ? visualState.current.likedPosts[postIdStr] 
      : originalLiked;
    
    const newLiked = !currentVisualState;
    visualState.current.likedPosts[postIdStr] = newLiked;
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
    
    // Calculate visual delta
    const visualDelta = newLiked !== originalLiked 
      ? (newLiked ? 1 : -1) 
      : 0;
    
    // Update UI immediately (optimistic update)
    // 1. Update the likedPosts state
    setLikedPosts(prev => ({
      ...prev,
      [postId]: newLiked
    }));
    
    // 2. Update the post like count in the appropriate array
    const updatePostInArray = (posts) => 
      posts.map(post => 
        post.id === postId 
          ? { 
              ...post, 
              likes: Math.max(0, originalCount + visualDelta)
            }
          : post
      );
    
    if (activeTab) {
      setUserShorts(updatePostInArray(userShorts));
    } else {
      setUserPosts(updatePostInArray(userPosts));
    }
    
    // Debounce the API call
    if (pendingLikeOperations.current.has(postIdStr)) {
      clearTimeout(pendingLikeOperations.current.get(postIdStr));
    }
    
    const timerId = setTimeout(() => {
      // Only make the API call if the final visual state differs from backend state
      if (visualState.current.likedPosts[postIdStr] !== originalLiked) {
        // Include explicit action parameter based on target state
        axios.post(
          `${api}/user-interactions/like/${postId}`,
          { action: visualState.current.likedPosts[postIdStr] ? 'like' : 'unlike' },
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
          const revertPostInArray = (posts) => 
            posts.map(post => 
              post.id === postId 
                ? { 
                    ...post, 
                    likes: originalCount
                  }
                : post
            );
          
          if (activeTab) {
            setUserShorts(revertPostInArray(userShorts));
          } else {
            setUserPosts(revertPostInArray(userPosts));
          }
          
          visualState.current.likedPosts[postIdStr] = originalLiked;
          toast.error("Failed to update like status");
        });
      }
      pendingLikeOperations.current.delete(postIdStr);
    }, 500);
    
    pendingLikeOperations.current.set(postIdStr, timerId);
  };
  
  // Add cleanup effect
  useEffect(() => {
    return () => {
      // Clear pending operations
      if (pendingLikeOperations.current.size > 0) {
        pendingLikeOperations.current.forEach(timerId => clearTimeout(timerId));
        pendingLikeOperations.current.clear();
      }
      if (pendingSaveOperations.current.size > 0) {
        pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
        pendingSaveOperations.current.clear();
      }
    };
  }, []);

  const pendingSaveOperations = useRef(new Map());
  const visualState = useRef({
    likedPosts: {},
    savedPosts: {}
  });
  
  // Add this handler in the Profile component
const handleSaveToggle = (postId, e) => {
  if (e) e.stopPropagation();
  
  // Visual feedback animation
  if (e && e.currentTarget) {
    requestAnimationFrame(() => {
      e.currentTarget.classList.add('scale-90');
      setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
    });
  }
  
  const postIdStr = postId.toString();
  
  // Remember the ORIGINAL backend state (from Redux)
  const originalSaved = savedPosts[postId] || false;
  
  // TOGGLE the local visual state
  const hasVisualState = postIdStr in visualState.current.savedPosts;
  const currentVisualState = hasVisualState 
    ? visualState.current.savedPosts[postIdStr] 
    : originalSaved;
  
  const newSaved = !currentVisualState;
  visualState.current.savedPosts[postIdStr] = newSaved;
  
  // Update UI immediately for better UX
  setSavedPosts(prev => ({
    ...prev,
    [postId]: newSaved
  }));
  
  // Debounce the API call
  if (pendingSaveOperations.current.has(postIdStr)) {
    clearTimeout(pendingSaveOperations.current.get(postIdStr));
  }
  
  const timerId = setTimeout(() => {
    // Only make the API call if the final visual state differs from backend state
    if (visualState.current.savedPosts[postIdStr] !== originalSaved) {
      // Include explicit action parameter based on target state
      axios.post(
        `${api}/user-interactions/save/${postId}`,
        { action: visualState.current.savedPosts[postIdStr] ? 'save' : 'unsave' },
        { withCredentials: true }
      )
      .then(response => {
        if (response.data && response.data.success) {
          // Optional: show success message
          if (visualState.current.savedPosts[postIdStr]) {
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
        visualState.current.savedPosts[postIdStr] = originalSaved;
        toast.error("Failed to update saved status");
      });
    }
    pendingSaveOperations.current.delete(postIdStr);
  }, 500);
  
  pendingSaveOperations.current.set(postIdStr, timerId);
};

  // Add these new handlers before the return statement
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

  // Add this state for menu positioning
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

  // Update handleToggleMenu function to set position
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
      topPosition = Math.min(buttonRect.top, viewportHeight - 250);
      leftPosition = Math.max(viewportWidth - 192, 0); // 192px is width of menu (w-48)
    } else {
      // Desktop: position near the button without adding scroll
      topPosition = Math.min(buttonRect.top, viewportHeight - 250);
      
      // Position to the left of the button, but ensure it stays within viewport
      leftPosition = Math.min(
        Math.max(buttonRect.right - 192, 0),
        viewportWidth - 192
      );
    }
    
    // Set final position
    setMenuPosition({
      top: topPosition,
      left: leftPosition
    });
    
    setActiveMenu(postId);
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
  
  const handleReportPost = (postId, e) => {
    e.stopPropagation();
    setReportType('post');
    setReportTargetId(postId);
    setShowReportWidget(true);
    setActiveMenu(null);
  };

  const handleReportUser = (userId, e) => {
    e.stopPropagation();
    setReportType('user');
    setReportTargetId(userId);
    setShowReportWidget(true);
    setActiveMenu(null);
  };

  const handleCancelMenu = (e) => {
    e.stopPropagation();
    setActiveMenu(null);
  };

  // You need to add handleDeletePost and handleEditPost functions if they don't exist
  const handleDeletePost = async (postId, e) => {
    e.stopPropagation();
    toast.error("You don't have permission to delete this post");
    setActiveMenu(null);
  };
  
  const handleEditPost = (postId, e) => {
    e.stopPropagation();
    toast.error("You don't have permission to edit this post");
    setActiveMenu(null);
  };

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

  // Update the click outside handler to properly handle more menu closing
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Close active menu when clicking outside
      if (activeMenu && !event.target.closest('[data-more-button="true"]')) {
        // Check if the click is outside any menu container
        const isOutsideMenu = document.querySelectorAll('.menu-container').length > 0 && 
                             !event.target.closest('.menu-container');
        
        if (isOutsideMenu || !event.target.closest('.menu-container')) {
          setActiveMenu(null);
        }
      }
      
      // Handle other widget closing behavior
      if (widgetRef.current && !widgetRef.current.contains(event.target)) {
        setShowOptions(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [activeMenu]);

  // Add this function to handle image clicks
  const handleImageClick = (e, media, index) => {
    e.stopPropagation();
    if (media && media.type !== 'video') {
      setViewingImage(media);
      setImageIndex(index);
    }
  };
  
  // Function to close the image viewer
  const closeImageViewer = () => {
    setViewingImage(null);
    setImageIndex(0);
  };

  // Fix the navigateImages function to properly handle navigation
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

  // Skeleton component for the profile
  const ProfileSkeleton = () => (
    <div className="min-h-screen text-white font-sans">
      <section>
        <div className="w-full max-w-[700px] mx-auto">
          {/* Cover Image Skeleton */}
          <div className="relative h-48 w-full">
            <Skeleton height={192} width="100%" borderRadius={0} className="rounded-b-lg" />
          </div>

          <div className="flex">
            {/* Left Half */}
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

                  {/* Bio Skeleton */}
                  <div className="mt-4">
                    <Skeleton count={3} width={300} />
                  </div>

                  {/* Social Links Skeleton */}
                  <div className="flex space-x-4 mt-6">
                    <Skeleton circle width={24} height={24} />
                    <Skeleton circle width={24} height={24} />
                    <Skeleton circle width={24} height={24} />
                    <Skeleton width={80} height={34} borderRadius={20} />
                    <Skeleton width={80} height={34} borderRadius={20} />
                  </div>
                </div>
              </div>
            </div>

            {/* Right Half - Stats */}
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

  // Create a content skeleton component specifically for content loading
  const ContentLoadingSkeleton = () => (
    <div className="space-y-3 w-full my-4 mb-16 max-w-[640px]">
      {Array(3).fill().map((_, index) => (
        <div key={index} className="w-full">
          <Skeleton height={300} className="rounded-xl" />
        </div>
      ))}
    </div>
  );

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

  // Profile Not Found component
  const ProfileNotFoundView = () => (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#0a0a0a] text-white">
      <div className="bg-[#151515] p-10 rounded-lg flex flex-col items-center max-w-md mx-4">
        <div className="w-20 h-20 rounded-full bg-gray-700 flex items-center justify-center mb-6">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
        <h2 className="text-2xl font-bold mb-2">Profile Not Available</h2>
        <p className="text-gray-400 text-center mb-6">
          The user profile you're looking for doesn't exist or is no longer available.
        </p>
        <button 
          onClick={() => navigate('/')}
          className="px-5 py-2 bg-white text-black font-medium rounded-full hover:bg-gray-200 transition-colors"
        >
          Return Home
        </button>
      </div>
    </div>
  );

  // Show profile not found screen
  if (profileNotFound) {
    return <ProfileNotFoundView />;
  }

  // Show skeleton during loading
  if (initialLoading) {
    return (
      <SkeletonTheme baseColor="#202020" highlightColor="#444">
        <ProfileSkeleton />
      </SkeletonTheme>
    );
  }

  // Add this handler for the carousel to update local state
  const handleCarouselIndexChange = (postId, newIndex) => {
    setShortMediaIndexes(prev => ({
      ...prev,
      [postId]: newIndex
    }));
  };

  const handleShowFollows = (type) => {
    setFollowsWidgetType(type);
    setShowFollowsWidget(true);
  };

  return (
    <div className="min-h-screen  text-white font-sans" ref={pageRef}>
      <section id="theprofileinfo">
        <div className="w-full max-w-[700px] mx-auto">
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
            {/* Left Half */}
            <div
              id="lefthalf"
              className="w-[50%] max-xl:w-[60%] max-md:w-[100%]"
            >
              {/* Profile Information */}
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

                    className="w-40 h-40 max-md:h-32 bg-[#d6d6d6]  max-md:w-32 object-cover rounded-full border-4 border-white"
                  />
                  <div className="mt-[-60px] ml-36 w-full md:hidden">
                    <h1 className="text-3xl max-md:text-xl font-bold flex items-center gap-2">{userProfile.fullName} {userProfile.verified && <RiVerifiedBadgeFill className="text-blue-500 h-5 w-5"/>}   </h1>
                    
                    <p className="text-gray-300 text-sm">
                      @{userProfile.username}
                    </p>
                  </div>
                </div>

                {/* User Info and Actions */}
                <div className="pt-24 max-md:mt-0 pb-6">
                  <div className="flex justify-between items-center">
                    <div className="flex md:hidden max-lg:text-[22px] ml-1 mb-2 space-x-10 max-md:mt-[-10px] justify-center text-gray-300 font-semibold">
                      <div className="flex flex-col items-center">
                        <span>{userProfile.posts}</span>
                        <span className="text-[17px] max-md:text-[15px] max-sm:text-sm font-regular">
                          Posts
                        </span>
                      </div>
                      <div 
                        className="flex flex-col items-center cursor-pointer hover:opacity-80"
                        onClick={() => handleShowFollows('following')}
                      >
                        <span>{userProfile.following}</span>
                        <span className="text-[17px] max-md:text-[15px] max-sm:text-sm font-regular">
                          Following
                        </span>
                      </div>
                      <div 
                        className="flex flex-col items-center cursor-pointer hover:opacity-80"
                        onClick={() => handleShowFollows('followers')}
                      >
                        <span>{userProfile.followers}</span>
                        <span className="text-[17px] max-md:text-[15px] max-sm:text-sm font-regular">
                          Followers
                        </span>
                      </div>
                    </div>
                    <div className="max-md:hidden">
                      <h1 className="text-3xl max-md:text-xl font-bold flex items-center gap-2">
                        {userProfile.fullName}
                     {userProfile.verified && <RiVerifiedBadgeFill className="text-blue-500 h-[25px] w-[25px]"/>}
                      </h1>    
                      <p className="text-gray-300 text-sm">
                        @{userProfile.username}
                      </p>
                    </div>
                  </div>

                        {/* Tags/Badges */}
                        <div className="mt-3 mb-3 tags ml-2">
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
                    <p className="mt-4 max-md:mt-2 w-[200%] md:text-[16px] text-[15px] font-medium max-md:mr-4 max-md:w-[160%] max-500:w-[155%] max-md:pr-8 text-gray-300 font-sans">
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
                        className="text-gray-600 hover:text-gray-900"
                      >
                        <Youtube size={24} />
                      </a>
                    )}
                    {userProfile.socialLinks?.github && (
                      <a
                        href={userProfile.socialLinks.github}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-gray-600 hover:text-gray-900"
                      >
                        <Github size={24} />
                      </a>
                    )}
                    <div className="flex space-x-2 items-center ml-2">
                      <button
                        onClick={handleMessage}
                        className="px-4 py-1 bg-white font-medium text-[15px] text-black rounded-full hover:bg-zinc-300"
                      >
                        Message
                      </button>
                      
                      <button
                        onClick={handleFollowToggle}
                        disabled={followLoading}
                        className={`px-4 py-1 flex items-center justify-center min-w-[90px] ${
                          userProfile.followedByMe 
                            ? "bg-[#0a0a0a] text-white border border-white rounded-full hover:bg-zinc-900" 
                            : "bg-white font-medium  text-black rounded-full hover:bg-zinc-300"
                        } transition-all text-[15px] ${followLoading ? 'opacity-80' : ''}`}
                      >
                        {followLoading ? (
                          <span 
                            className={`h-4 w-4 border-2 border-t-transparent ${
                              userProfile.followedByMe 
                                ? "border-white" 
                                : "border-black"
                            } border-solid rounded-full inline-block animate-spin mr-1.5`}
                          ></span>
                        ) : null}
                        {userProfile.followedByMe ? "Following" : "Follow"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Half */}
            <div id="righthalf" className="space-y-4 w-[50%] h-full max-md:mt-4 mt-10 pr-2">
              {/* Stats (hidden on mobile) */}
              <div className="flex justify-end lg:font-bold w-full max-md:hidden space-x-8 mb-1 text-[30px] max-lg:text-[24px] text-gray-300 font-semibold">
                <div className="flex flex-col items-center">
                  <span>{userProfile.posts}</span>
                  <span className="text-[16px] font-medium">Posts</span>
                </div>
                <div 
                  className="flex flex-col items-center cursor-pointer hover:opacity-80 transition"
                  onClick={() => handleShowFollows('following')}
                >
                  <span>{userProfile.following}</span>
                  <span className="text-[16px] font-medium">Following</span>
                </div>
                <div 
                  className="flex flex-col items-center cursor-pointer hover:opacity-80 transition"
                  onClick={() => handleShowFollows('followers')}
                >
                  <span>{userProfile.followers}</span>
                  <span className="text-[16px] font-medium">Followers</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
 
     {/* Tabs Section */}
      <div className="mt-4 w-full flex flex-col items-center">
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
    
            {/* Content Area - Twitter-like feed format exactly like Home.jsx */}
            <div className="space-y-2 max-md:px-2 md:mt-8 md:space-y-3 w-full my-4 mb-16 max-w-[640px]">
            {contentLoading ? (
                <SkeletonTheme baseColor="#202020" highlightColor="#444">
                  {activeTab ? <ShortsLoadingSkeleton /> : <ContentLoadingSkeleton />}
                </SkeletonTheme>
              ) : activeTab ? (
                // Shorts section - Twitter-like feed
                userShorts !== null && userShorts.length > 0 ? (
                  userShorts.map((post, index) => (
                  // Replace the shorts article element with this:
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
                        <div div className="w-[100%]  rounded-2xl h-[50%] relative"
          onTouchMove={(e) => handleShortTouchMove(e, post.id, post.media?.length || 0)}
        >
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
      </div>                          {/* Action buttons - Right side */}                          <div className="absolute h-fit right-3 bottom-3 flex flex-col items-center space-y-7 ">                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleLikeToggle(post.id, e);
                              }}
                              className="hover:text-gray-300 border border-gray-600 hover:border-gray-500 transition-colors py-2 px-[5px] rounded-full flex flex-col items-center"
                              data-like-button={post.id}
                            >
                              <BiUpvote 
                                className='text-white empty-heart' 
                                size={20} 
                                style={{
                                  display: (() => {
                                    const postId = post.id?.toString();
                                    
                                    if (postId && postId in visualState.current.likedPosts) {
                                      return visualState.current.likedPosts[postId] ? 'none' : 'block';
                                    }
                                    
                                    return likedPosts[post.id] ? 'none' : 'block';
                                  })()
                                }} 
                              />                              <BiSolidUpvote 
                                className='text-gray-200 filled-heart' 
                                size={20} 
                                style={{
                                  display: (() => {
                                    const postId = post.id?.toString();
                                    
                                    if (postId && postId in visualState.current.likedPosts) {
                                      return visualState.current.likedPosts[postId] ? 'block' : 'none';
                                    }
                                    
                                    return likedPosts[post.id] ? 'block' : 'none';                                  })()
                                }} 
                              />
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
                                      handleReportPost(post.id, e);
                                    }} 
                                    className="text-red-700 border-[1px] p-2 rounded-full border-gray-700 hover:scale-105 mb-1"
                                    title="Report"
                                  >
                                    <MdOutlineReport size={24} />
                                  </button>
                                  <span className="text-gray-300 text-xs font-sans">Report</span>
                                </div>
    
                                <div className="flex flex-col items-center">
                                  <button 
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleSaveToggle(post.id, e);
                                    }} 
                                    className="text-white border-[1px] p-[13px] rounded-full border-gray-700 hover:scale-105 mb-1" 
                                    title="Save"
                                  >
                                    {savedPosts[post.id] ? <BsBookmarkFill size={21} /> : <BsBookmark size={21} />}
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
                ) : userShorts === null ? (
                  // Show shorts loader when null
                  <SkeletonTheme baseColor="#202020" highlightColor="#444">
                    <ShortsLoadingSkeleton />
                  </SkeletonTheme>
                ) : (
                  // No shorts found
                  <div className="text-center py-10">
                    <p className="text-gray-400">No shorts found.</p>
                  </div>
                )
              ) : (
                // Regular posts section - Twitter-like feed
            userPosts.length > 0 ? (
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
                            className="fixed w-48 font-medium bg-[#0f0f0f] border border-gray-700 rounded-md shadow-lg z-[1000] menu-container"
                            style={{
                              top: `${menuPosition.top}px`,
                              left: `${menuPosition.left}px`,
                              maxHeight: '90vh',
                              position: 'fixed'
                            }}
                          >
                            <ul className="py-1 text-gray-200">
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-600"
                                onClick={(e) => handleReportPost(post.id, e)}
                              >
                                <div className="flex items-center">
                                  <MdOutlineReport className="mr-2" />
                                  Report Post
                                </div>
                              </li>
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-600"
                                onClick={(e) => handleReportUser(userProfile.id, e)}
                              >
                                <div className="flex items-center">
                                  <MdOutlineReport className="mr-2" />
                                  Report User
                                </div>
                              </li>
                              <li 
                                className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                                onClick={(e) => copyToClipboard(`${window.location.origin}/viewpost/${post.id}`)}
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

                  {/* Post Content - Clicking on it shows the post details */}
                  <div 
                    className="pr-4 pl-4 max-md:px-0 cursor-pointer"
                  >                    {/* Text Content */}
                    {(post.title || post.content || post.description) && (
                       <div className="mb-[10px] max-md:ml-2 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2">
                        <SmartTruncateText
                          text={post.title || post.content || post.description}
                          className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-medium"
                        />
                      </div>
                    )}

                    {/* Media Content - Updated to match Home.jsx */}
                    {post.media && post.media.length > 0 && (
                      <div className="relative mb-4 xl:w-[84%] md:w-[90%] mx-auto w-full">                        {/* Single media item - full width for both mobile and desktop */}
                        {post.media.length === 1 ? (                          <div className="relative mb-4">
                            <div className="max-md:w-[100%] max-md:mx-auto w-[98%] mx-auto" style={{ maxHeight: '550px' }}>
                              {post.media[0].type === 'video' ? (
                                <div 
                                    className="max-md:rounded-lg max-md:w-[96%] md:w-full mx-auto rounded-lg h-full video-container bg-black  cursor-pointer overflow-hidden relative" 
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
                                </div>                              ) : (
                                <img 
                                  src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                                  alt="Post image" 
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
                            videoOverlays={videoOverlays}
                          />
                        )}
                      </div>
                    )}
                  </div>

                  {/* Post Actions - Unchanged */}
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
                      <div className="p-1.2 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
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
                      <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                        <BsSend className="h-[18px] w-[18px]  transition-colors duration-200" />
                      </div>
                    </button>

                    {/* Save Button */}
                    <button 
                      className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
                      onClick={(e) => handleSaveToggle(post.id, e)}
                    >
                      <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                        {savedPosts[post.id] ? (
                          <BsBookmarkFill className="h-[18px] w-[18px] text-white group-hover:text-gray-200 transition-colors duration-200" />
                        ) : (
                          <BsBookmark className="h-[18px] w-[18px]  transition-colors duration-200" />
                        )}
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

      {/* Image Viewer */}
      {viewingImage && (
        <div 
          className="fixed inset-0 bg-black/90 z-50 flex items-center justify-center"
          onClick={closeImageViewer}
        >
          <div className="relative max-h-[85vh] min-w-[98vw]">
            <img 
              src={`${cloud}/cloudofscubiee/postImages/${viewingImage.url}`
              }
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
      )}     {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
        </div>
      )}
    </div>
  );
};

export default Profile;