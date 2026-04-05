import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import axios from 'axios';
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import { IoCloseSharp } from "react-icons/io5";
import { MdOutlineReport, MdOutlineContentCopy, MdOutlineDeleteOutline } from "react-icons/md";
import { toast } from 'react-toastify';
import { useDispatch, useSelector } from 'react-redux';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import CommentWidget from "../components/CommentWidget";
import ShareDialog from "../components/shareWidget";
import ReportWidget from "../components/ReportWidget";
import './ViewPost.css';
import { useInteractionManager } from '../hooks';
import { createPortal } from 'react-dom';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;
const DefaultPicture = "/logos/DefaultPicture.png";

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
                  onClick={(e) => handleImageClick(e, media, post, i)}
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

// Remove the useVideoAutoplay hook from Home.jsx and add it here
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

function ViewPost() {
  const { id } = useParams();
  const location = useLocation(); // Add this to access URL query parameters
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const userData = useSelector((state) => state.user.userData);
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);
  const pendingLikeOperations = useRef(new Map());
  const visualLikedState = useRef(false);
  
  // Add local state for notification data from URL
  const [notificationData, setNotificationData] = useState(null);
  
  const hasLoggedView = useRef(false);
  
  // Widgets and UI state
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportType, setReportType] = useState(null);
  const [reportTargetId, setReportTargetId] = useState(null);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  
  // Image viewer state
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);
  
  // Interaction states
  const [interactions, setInteractions] = useState({
    liked: false,
    saved: false,
    likesCount: 0,
    isFollowing: false,
  });

  // Refs
  const moreOptionsRef = useRef(null);
  const reportWidgetRef = useRef(null);
  
  // Add this state for short media navigation
  const [currentShortMediaIndex, setCurrentShortMediaIndex] = useState(0);

  // Add state for video handling
  const [videoOverlays, setVideoOverlays] = useState({});
  const [globalMuted, setGlobalMuted] = useState(false);
  const [isTouchDevice, setIsTouchDevice] = useState(false);
  const videoStates = useRef({});
  const globalUnmuteState = useRef(false);
  
  // Add the video autoplay hook
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
  } = useVideoAutoplay([post]);

  // Add these short media navigation functions
  const goToPrevShortMedia = () => {
    if (currentShortMediaIndex > 0) {
      setCurrentShortMediaIndex(currentShortMediaIndex - 1);
    }
  };

  const goToNextShortMedia = () => {
    if (post?.media && currentShortMediaIndex < post.media.length - 1) {
      setCurrentShortMediaIndex(currentShortMediaIndex + 1);
    }
  };

  // Handle touch events for short media navigation
  const shortTouchStart = useRef(0);
  const shortTouchEnd = useRef(0);

  const handleShortTouchStart = (e) => {
    shortTouchStart.current = e.touches[0].clientX;
  };

  const handleShortTouchMove = (e) => {
    shortTouchEnd.current = e.touches[0].clientX;
  };

  const handleShortTouchEnd = () => {
    // Calculate swipe distance
    const diff = shortTouchStart.current - shortTouchEnd.current;
    
    // If the swipe is significant enough
    if (Math.abs(diff) > 50) {
      if (diff > 0) {
        // Swiped left - go to next media
        goToNextShortMedia();
      } else {
        // Swiped right - go to previous media
        goToPrevShortMedia();
      }
    }
  };

  // Reset current media index when post changes
  useEffect(() => {
    setCurrentShortMediaIndex(0);
  }, [post?.id]);

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  // Add this ref to target the first video element
  const firstVideoRef = useRef(null);

  // After post loads, autoplay and unmute the first video if present
  useEffect(() => {
    setGlobalMuted(false);
    
    // Attempt to unmute all videos after a short delay
    const timer = setTimeout(() => {
      const allVideos = document.querySelectorAll('video');
      allVideos.forEach(video => {
        video.muted = false;
      });
    }, 500);
    
    return () => clearTimeout(timer);
  }, []);

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
          // Explicitly set unmuted for better user experience
          targetVideo.muted = false;
          targetVideo.controls = false;
          
          // Try to play the video unmuted first
          const playPromise = targetVideo.play();
          
          if (playPromise !== undefined) {
            playPromise.catch(err => {
              console.log('Failed to autoplay unmuted:', err);
              
              // If unmuted autoplay fails, try muted
              targetVideo.muted = true;
              targetVideo.play().then(() => {
                // Try to unmute after successful muted playback
                // This helps with some browsers that require initial muted playback
                setTimeout(() => {
                  targetVideo.muted = false;
                }, 200);
              }).catch(e => {
                console.log('Failed to autoplay even with mute:', e);
              });
            });
          }
        }
      }
    }
  }, [mostVisibleVideo, hasUserInteracted, videoRefs, isManuallyPaused]);

  useEffect(() => {
    if (post && post.media && post.media.length > 0) {
      const firstVideo = post.media.find(m => m.type === 'video');
      if (firstVideo && firstVideoRef.current) {
        // Set video properties
        firstVideoRef.current.muted = false;
        firstVideoRef.current.volume = 1;
        firstVideoRef.current.controls = false;
        
        // Try to play unmuted first
        const playPromise = firstVideoRef.current.play();
        
        if (playPromise !== undefined) {
          playPromise.catch(err => {
            console.log('Failed to autoplay first video unmuted:', err);
            
            // If unmuted playback fails, try with mute
            firstVideoRef.current.muted = true;
            firstVideoRef.current.play().then(() => {
              // Try to unmute after successful muted playback
              setTimeout(() => {
                firstVideoRef.current.muted = false;
              }, 200);
            }).catch(e => {
              console.log('Failed to autoplay first video even with mute:', e);
            });
          });
        }
      }
    }
  }, [post]);

  // Fetch post data
  useEffect(() => {
    const fetchPost = async () => {
      try {
        setLoading(true);
        // First fetch the main post data
        const response = await axios.get(`${api}/post/${id}`, {
          withCredentials: true,
        });
        
        
        // Transform the response to include a properly formatted media array if it doesn't exist
        const postData = { ...response.data };
        
        // If media is empty but we have a thumbnail, try to use it
        if ((!postData.media || postData.media.length === 0) && postData.thumbnail) {
          // Attempt to determine if it's a video or image based on extension
          const isVideo = /\.(mp4|mov|avi|wmv)$/i.test(postData.thumbnail);
          
          postData.media = [{
            type: isVideo ? 'video' : 'image',
            url: postData.thumbnail,
            originalName: postData.thumbnail
          }];
        } 
        
        // If media is still empty, try to fetch detailed post data to get media
        if (!postData.media || postData.media.length === 0) {
          try {
            // Attempt to fetch more detailed post info that might contain media
            const detailsResponse = await axios.get(`${api}/post/post/details/${postData.author.id}?isShort=${postData.isShort || false}`, {
              withCredentials: true,
            });
            
            
            // Find the matching post in the response
            if (Array.isArray(detailsResponse.data)) {
              const detailedPost = detailsResponse.data.find(p => p.id === id);
              if (detailedPost && detailedPost.media && detailedPost.media.length > 0) {
                postData.media = detailedPost.media;
              }
            }
          } catch (detailsError) {
            // If fetching details fails, we'll continue with what we have
          }
        }
        
        // Initialize as empty array if no media exists at all
        if (!postData.media) {
          postData.media = [];
        }
        
        setPost(postData);
        
        // Set interactions
        if (postData.userInteraction) {
          setInteractions({
            liked: postData.userInteraction.liked,
            saved: postData.userInteraction.saved,
            likesCount: postData.likes || 0,
            isFollowing: postData.userInteraction.isFollowing,
          });
        } else {
          setInteractions(prev => ({
            ...prev,
            likesCount: postData.likes || 0
          }));
        }
        
        setLoading(false);
      } catch (err) {
        setError('Failed to load post. Please try again later.');
        setLoading(false);
      }
    };

    if (id) {
      fetchPost();
    }
  }, [id]);

  
  // Log post view
  useEffect(() => {
    if (!id || hasLoggedView.current) return;
    
    const logPostView = async () => {
      try {
        await axios.post(`${api}/user-interactions/view/${id}`, {}, {
          withCredentials: true
        });
        hasLoggedView.current = true;
      } catch (error) {
      }
    };
    
    logPostView();
    
    return () => {
      hasLoggedView.current = false;
    };
  }, [id]);
  
  // Parse notification data from URL parameters
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const notificationType = searchParams.get('notificationType');
    const referenceId = searchParams.get('referenceId');
    
    if (notificationType && ['comment', 'reply', 'comment_like', 'reply_like'].includes(notificationType)) {
      setNotificationData({
        type: notificationType,
        reference_id: referenceId,
        post_id: id
      });
    }
  }, [location, id]);
  
  // Handle notifications from URL params - replace the previous effect that used Redux
  useEffect(() => {
    if (notificationData && ['comment', 'reply', 'comment_like', 'reply_like'].includes(notificationData.type)) {
      if (notificationData.post_id === id) {
        // Slight delay to ensure post is loaded first
        const timer = setTimeout(() => {
          dispatch(setIsCommentOpen(true));
        }, 300);
        
        return () => clearTimeout(timer);
      }
    }
  }, [notificationData, id, dispatch]);
  
  // Handle click outside for more options menu
  useEffect(() => {
    function handleClickOutside(event) {
      // Check if we're clicking on a menu container or more button
      const isInsideMenu = event.target.closest('.menu-container');
      const isMoreButton = event.target.closest('[data-more-button="true"]');
      
      // Only close the menu if clicking outside both the menu and the more button
      if (moreOptionsRef.current && !isInsideMenu && !isMoreButton) {
        setIsMoreOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  // Add the interaction manager hook
  const { createLikeHandler, createSaveHandler } = useInteractionManager();

  const handleLikeToggle = (e) => {
    if (!post) return;
    
    // Early return if offline
    if (!navigator.onLine) {
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
    
    // Remember original value for immediate UI update
    const originalLiked = interactions.liked;
    const originalLikesCount = interactions.likesCount || 0;
    
    // Toggle liked state immediately for responsive UI
    const newLiked = !originalLiked;
    visualLikedState.current = newLiked;
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
    
    // Calculate the new count based purely on the click action
    const newLikesCount = newLiked ? 
      originalLikesCount + 1 : 
      Math.max(0, originalLikesCount - 1);
    
    // Update local state immediately (optimistic update)
    setInteractions(prev => ({
      ...prev,
      liked: newLiked,
      likesCount: newLikesCount
    }));
    
    // Debounce the API call
    if (pendingLikeOperations.current.has(post.id)) {
      clearTimeout(pendingLikeOperations.current.get(post.id));
    }
    
    const timerId = setTimeout(() => {
      // Direct axios call to the backend with action parameter
      axios.post(
        `${api}/user-interactions/like/${post.id}`,
        { action: visualLikedState.current ? 'like' : 'unlike' }, // Explicit action parameter
        { withCredentials: true }
      )
      .catch(error => {
        // Only revert UI state on error
        console.error('Error updating like status:', error);
        setInteractions(prev => ({
          ...prev,
          liked: originalLiked,
          likesCount: originalLikesCount
        }));
        visualLikedState.current = originalLiked;
        toast.error("Failed to update like status");
      })
      .finally(() => {
        pendingLikeOperations.current.delete(post.id);
      });
    }, 400);
    
    pendingLikeOperations.current.set(post.id, timerId);
  };

  
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
  // Add these refs at the component level
const pendingSaveOperations = useRef(new Map());
const visualSavedState = useRef(false);

// Update the handleSaveToggle function with direct axios call
const handleSaveToggle = (e) => {
  if (!post) return;
  
  // Early return if offline
  if (!navigator.onLine) {
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
  
  // Remember original value for immediate UI update
  const originalSaved = interactions.saved;
  
  // Toggle saved state immediately for responsive UI
  const newSaved = !originalSaved;
  visualSavedState.current = newSaved;
  
  // Update local state immediately (optimistic update)
  setInteractions(prev => ({
    ...prev,
    saved: newSaved
  }));
  
  // Debounce the API call
  if (pendingSaveOperations.current.has(post.id)) {
    clearTimeout(pendingSaveOperations.current.get(post.id));
  }
  
  const timerId = setTimeout(() => {
    // Direct axios call to the backend
    axios.post(
      `${api}/user-interactions/save/${post.id}`,
      { action: visualSavedState.current ? 'save' : 'unsave' }, // Critical part: explicit action
      { withCredentials: true }
    )
    .then(response => {
      if (response.data && response.data.success) {
        // Optional: show success message
        if (visualSavedState.current) {
          toast.success("Post saved successfully");
        } else {
          toast.success("Post unsaved successfully");
        }
      }
    })
    .catch(error => {
      // Revert UI state on error
      setInteractions(prev => ({
        ...prev,
        saved: originalSaved
      }));
      visualSavedState.current = originalSaved;
      toast.error("Failed to update saved status");
    });
    
    pendingSaveOperations.current.delete(post.id);
  }, 400);
  
  pendingSaveOperations.current.set(post.id, timerId);
};

// Add cleanup effect
useEffect(() => {
  return () => {
    if (pendingSaveOperations.current.size > 0) {
      pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
      pendingSaveOperations.current.clear();
    }
  };
}, []);
  
  // UI interaction handlers
  const handleCommentClick = () => {
    dispatch(setIsCommentOpen(true));
  };

  const handleShare = () => {
    setShowShareWidget(true);
  };

  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });

  const handleMoreClick = (e) => {
    // Don't toggle the menu if it's already closing
    if (isMoreOpen) {
      setIsMoreOpen(false);
      return;
    }
    
    // Get the position of the clicked button
    const buttonRect = e.currentTarget.getBoundingClientRect();
    
    // Calculate menu position based on device
    if (window.innerWidth < 768) {
      // Mobile: position above the button
      setMenuPosition({
        top: buttonRect.top - 10, // Position slightly above button
        left: window.innerWidth - 192, // 192px is width of menu (w-48)
      });
    } else {
      // Desktop: position to the right of the button
      setMenuPosition({
        top: buttonRect.top + window.scrollY,
        left: buttonRect.right - 192, // Align right edge of menu with button
      });
    }
    
    setIsMoreOpen(true);
  };
  
  // Add this state for delete confirmation
  const [deleteConfirmation, setDeleteConfirmation] = useState({
    isOpen: false,
    postId: null,
    postTitle: ''
  });

  // Replace handleDeletePost with this function
  const handleDeletePost = (e) => {
    if (e) e.stopPropagation();
    
    if (!navigator.onLine) {
      toast.warning("You're offline. Please try again when connected.");
      return;
    }
    
    // Validate that user is the author
    if (userData && post && userData.id === post.author.id) {
      // Open the confirmation modal
      setDeleteConfirmation({
        isOpen: true,
        postId: id,
        postTitle: post.title || post.content?.substring(0, 30) || 'this post'
      });
    } else {
      toast.error("You don't have permission to delete this post");
    }
    
    setIsMoreOpen(false);
  };

  // Add confirmation function
  const confirmDelete = () => {
    // Show deleting UI
    setIsLoading(true);
    
    // Call the delete API
    if (deleteConfirmation.postId) {
      axios.delete(`${api}/post/${deleteConfirmation.postId}`, {
        withCredentials: true
      })
      .then(() => {
        // Show success message
        
        // Navigate back after deletion - this is the key difference from Home.jsx
        // since we're viewing a single post, we need to navigate away
        navigate('/', { replace: true });
      })
      .catch(error => {
      })
      .finally(() => {
        // Hide deleting UI after operation completes
        setIsLoading(false);
        // Close the modal
        setDeleteConfirmation({
          isOpen: false,
          postId: null,
          postTitle: ''
        });
      });
    }
  };

  // Add cancel function
  const cancelDelete = () => {
    // Just close the modal
    setDeleteConfirmation({
      isOpen: false,
      postId: null,
      postTitle: ''
    });
  };

  const handleReportPost = () => {
    setReportType('post');
    setReportTargetId(id);
    setShowReportWidget(true);
    setIsMoreOpen(false);
  };

  const handleReportUser = () => {
    setReportType('user');
    setReportTargetId(post?.author?.id);
    setShowReportWidget(true);
    setIsMoreOpen(false);
  };

  const handleFollowToggle = async () => {
    // Implementation for following/unfollowing user
  };
  
  // Add state for copy notification
  const [showCopyNotification, setShowCopyNotification] = useState(false);

  const handleCopyLink = (e) => {
    e.stopPropagation();
    const postUrl = `${window.location.origin}/viewpost/${id}`;
    navigator.clipboard.writeText(postUrl);
    
    // Show notification
    setShowCopyNotification(true);
    setTimeout(() => setShowCopyNotification(false), 2000);
    
    // Close menu if it's open
    if (isMoreOpen) {
      setIsMoreOpen(false);
    }
  };
  
  // Image viewer handlers
  const handleImageClick = (e, media, index) => {
    e.stopPropagation();
    if (media && media.type !== 'video') {
      setViewingImage(media);
      setImageIndex(index);
    }
  };
  
  const closeImageViewer = () => {
    setViewingImage(null);
    setImageIndex(0);
  };
  
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
  
  // Add this new state for video playback
  const [playingVideos, setPlayingVideos] = useState({});

  // Add this function to handle video click
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
          // Just pause other videos
        }
      }
    });

    // Toggle play/pause with visual feedback
    if (videoElement.paused) {
      // Always unmute when trying to play
      videoElement.muted = false;
      const playPromise = videoElement.play();
      
      if (playPromise !== undefined) {
        playPromise.then(() => {
          // Successfully played - update states
          setManuallyPaused(videoKey, false);
          
          // Show play icon briefly
          setVideoOverlays(prev => ({ 
            ...prev, 
            [videoKey]: 'play' 
          }));
          
          // Hide play icon after delay
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
            videoElement.play().then(() => {
              // Try to unmute after successful muted playback
              setTimeout(() => {
                videoElement.muted = false;
              }, 200);
            }).catch(e => console.error('Failed to play even with mute:', e));
          }
        });
      }
    } else {
      // Pause the video
      videoElement.pause();
      
      // Update states
      setManuallyPaused(videoKey, true);
      
      // Show pause icon briefly
      setVideoOverlays(prev => ({ 
        ...prev, 
        [videoKey]: 'pause' 
      }));
      // Hide pause icon after delay
      setTimeout(() => {
        setVideoOverlays(prev => ({
          ...prev,
          [videoKey]: null
        }));
      }, 800);
    }
    
    // Don't show controls initially - let the user click again for controls
    videoElement.controls = false;
    
    // Store current mute state
    videoStates.current[videoKey] = { muted: videoElement.muted };
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

  // Display loading/error states
  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-screen bg-[#0c0c0c] text-white">
        <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]">
          <span className="!absolute !-m-px !h-px !w-px !overflow-hidden !whitespace-nowrap !border-0 !p-0 ![clip:rect(0,0,0,0)]">
            Loading...
          </span>
        </div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="flex flex-col justify-center items-center min-h-screen bg-[#0c0c0c] text-white p-4">
        <p className="text-lg text-red-400 mb-4">{error}</p>
        <button 
          className="px-4 py-2 bg-white text-black rounded-lg hover:bg-gray-200 transition"
          onClick={() => navigate('/')}
        >
          Return to Home
        </button>
      </div>
    );
  }
  
  if (!post) {
    return (
      <div className="flex flex-col justify-center items-center min-h-screen bg-[#0c0c0c] text-white p-4">
        <p className="text-lg text-gray-400 mb-4">Post not found</p>
        <button 
          className="px-4 py-2 bg-white text-black rounded-lg hover:bg-gray-200 transition"
          onClick={() => navigate('/')}
        >
          Return to Home
        </button>
      </div>
    );
  }

  return (
    <div className="max-md:h-[calc(100vh-65px)] h-full  text-white py-2 mb-12">
      <div className="mx-auto p-4 w-full max-w-[700px] max-md:max-w-full max-md:px-0">
        {/* Back button */}
        <button 
          onClick={() => navigate(-1)} 
          className="flex items-center mb-4 border-2 max-md:hidden rounded-full border-gray-500 px-4 py-1 text-gray-400 hover:text-white transition duration-200 hover:opacity-80"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          <span className="text-[17px] font-semibold tracking-wide">Back</span> 
        </button>

        
        {/* Post Content */}
        <article className="overflow-hidden rounded-2xl border-2 border-[#181818] bg-[#0a0a0a] md:bg-[#0c0c0c] backdrop-blur-sm py-3 text-gray-300 w-full max-md:border-b-4 max-md:rounded-none max-md:border-0  max-md:border-[#181818]">
          {/* Post Header */}
          <div className="flex items-center justify-between mb-3 px-4">
            <Link 
              to={`/${post.author.username}`} 
              className="flex items-center gap-3"
            >
              <div className="relative h-10 w-10 rounded-full overflow-hidden group cursor-pointer">
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
                  <h3 className="text-[15px] font-semibold">
                    {post.author.username}
                  </h3>
                  {post.author.Verified && (
                    <RiVerifiedBadgeFill className="text-blue-500 h-[14px] w-[14px]" />
                  )}
                </div>
                <h3 className="text-xs text-gray-400">
                  {new Date(post.createdAt).toLocaleDateString('en-US', {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric'
                  })}
                </h3>
              </div>
            </Link>
            
            {/* Post menu button */}
            <div className="relative" ref={moreOptionsRef}>
              <button 
                className="text-gray-400 hover:text-white p-1 rounded-full hover:bg-gray-800/30 transition-colors duration-200" 
                onClick={handleMoreClick}
                data-more-button="true"
              >
                <FiMoreVertical className="h-[19px] w-[19px]" />
              </button>
              
              {isMoreOpen && (
                <Portal>
                  <div 
                    className="fixed w-48 font-medium bg-[#0f0f0f] border border-gray-700 rounded-md shadow-lg z-[1000] menu-container"
                    style={{
                      top: `${menuPosition.top}px`,
                      left: `${menuPosition.left}px`,
                      maxHeight: '90vh',
                    }}
                  >
                    <ul className="py-1 text-gray-200">
                      {post.author.id === userData?.id ? (
                        // Options for the user's own post
                        <>
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-500"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeletePost(e);
                            }}
                          >
                            <div className="flex items-center">
                              <MdOutlineDeleteOutline className="mr-2" size={16}/>
                              Delete Post
                            </div>
                          </li>
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCopyLink(e);
                            }}
                          >
                            <div className="flex items-center">
                              <MdOutlineContentCopy className="mr-2" />
                              Copy Link
                            </div>
                          </li>
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMoreClick(e);
                            }}
                          >
                            <div className="flex items-center">
                              <IoCloseSharp className="mr-2" />
                              Cancel
                            </div>
                          </li>
                        </>
                      ) : (
                        // Options for other users' posts
                        <>
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-600"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleReportPost();
                            }}
                          >
                            <div className="flex items-center">
                              <MdOutlineReport className="mr-2" />
                              Report Post
                            </div>
                          </li>
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-600"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleReportUser();
                            }}
                          >
                            <div className="flex items-center">
                              <MdOutlineReport className="mr-2" />
                              Report User
                            </div>
                          </li>
                          
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCopyLink(e);
                            }}
                          >
                            <div className="flex items-center">
                              <MdOutlineContentCopy className="mr-2" />
                              Copy Link
                            </div>
                          </li>
                          <li 
                            className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleMoreClick(e);
                            }}
                          >
                            <div className="flex items-center">
                              <IoCloseSharp className="mr-2" />
                              Cancel
                            </div>
                          </li>
                        </>
                      )}
                    </ul>
                  </div>
                </Portal>
              )}
            </div>
          </div>

          {/* Post Title & Content */}
          <div className="md:px-4 mb-4">
            {post.title && (
              <h2 className="text-xl font-bold mb-3 text-gray-100">
                {post.title}
              </h2>
            )}            {/* Show either content or description with smart truncation */}
            {(post.content || post.description) && (
                      <div className="mb-4  md:pl-[44px] max-md:px-2 mx-1 xl:mx-2">
                <SmartTruncateText
                  text={post.content || post.description}
                  className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-semibold"
                />
              </div>
            )}

            {/* Media Content - Using the same patterns as MyProfile.jsx */}
            {post.media && post.media.length > 0 && (
              <div className="relative mb-4 xl:w-[84%] md:w-[90%] mx-auto w-full">                {/* Single media item - full width for both mobile and desktop */}
                {post.media.length === 1 ? (                  <div className="relative mb-4">
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
                        </div>                      ) : (                        <img 
                          src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                          alt="Post media" 
                          loading="lazy"
                          className="max-md:w-[100%] max-md:mx-auto max-md:rounded-lg w-full h-auto object-cover md:rounded-lg cursor-pointer max-h-[550px]"
                          onClick={(e) => handleImageClick(e, post.media[0], 0)}
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

          {/* Post Actions */}        <div className="flex items-center md:w-[84%] xl:w-[78%] md:pl-[1px] md:mx-auto max-md:mr-[8px] max-md:ml-2 max-md:px-2 mb-3 mt-2 max-md:mb-0">
          {/* Like Button */}
          <button 
            className={`flex items-center gap-1 px-3 py-[4px] rounded-full border transition-all duration-200 transform hover:scale-105 ${
              interactions.liked 
                   ? ' border-gray-500 bg-white/05 text-gray-200' 
                              : 'border-gray-500 bg-white/05 text-gray-300 '
            }`}
            onClick={handleLikeToggle}
          >
            <BiUpvote 
              className="h-4 w-4" 
              style={{display: interactions.liked ? 'none' : 'block'}} 
            />
            <BiSolidUpvote 
              className="h-4 w-4 text-gray-300" 
              style={{display: interactions.liked ? 'block' : 'none'}} 
            />
            <span className="text-sm font-medium">
              {interactions.likesCount?.toLocaleString() || '0'}
            </span>
          </button>

            {/* Comment Button */}
            <button 
              className="flex items-center gap-2 text-gray-300 ml-6 group"
              onClick={handleCommentClick}
            >
              <div className="p-1.2 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                <TfiCommentAlt className="mt-[1px] h-[18px] w-[18px] group-hover:text-gray-100 transition-colors duration-200" />
              </div>
              <span className="text-[14px] mt-[-1px] group-hover:text-gray-100 transition-colors duration-200">
                {(post.comments > 0) ? post.comments : '0'}
              </span>
            </button>

            {/* Share Button */}
            <button 
              className="flex items-center text-gray-300 ml-auto group"
              onClick={handleShare}
            >
              <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                <BsSend className="h-[18px] w-[18px] group-hover:text-gray-100 transition-colors duration-200" />
              </div>
            </button>

            {/* Save Button */}
            <button 
              className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
              onClick={handleSaveToggle}
            >
              <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                {interactions.saved ? (
                  <BsBookmarkFill className="h-[18px] w-[18px] text-white group-hover:text-gray-200 transition-colors duration-200" />
                ) : (
                  <BsBookmark className="h-[18px] w-[18px] group-hover:text-gray-100 transition-colors duration-200" />
                )}
              </div>
            </button>
          </div>
        </article>
      </div>
      
      {/* Image Viewer */}
      {viewingImage && (
        <div 
          className="fixed inset-0 bg-black/90 z-50 flex items-center justify-center"
          onClick={closeImageViewer}
        >
          <div className="relative max-h-[85vh] min-w-[98vw]">
          <img 
              src={viewingImage.url.includes('://') 
                ? viewingImage.url 
                : `${cloud}/cloudofscubiee/postImages/${viewingImage.url}`}
              alt="Enlarged view"
              className="max-h-[85vh] min-w-[98vw] object-cover"
            />
            
            {/* Navigation arrows */}
            {viewingImage.postMedia && viewingImage.postMedia.filter(media => media.type !== 'video').length > 1 && (
              <>
                <button 
                  className="absolute md:left-[-50px] left-0 top-1/2 transform -translate-y-1/2 bg-white/10 md:p-2 p-1 rounded-full z-10"
                  onClick={(e) => navigateImages(e, -1, viewingImage.postMedia)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="md:h-6 md:w-6 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <button 
                  className="absolute md:right-[-50px] right-0 top-1/2 transform -translate-y-1/2 bg-white/10 md:p-2 p-1 rounded-full z-10"
                  onClick={(e) => navigateImages(e, 1, viewingImage.postMedia)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="md:h-6 md:w-6 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </>
            )}
            
          
          </div>
        </div>
      )}
      
      {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
        </div>
      )}

      {/* Comment Widget */}
      {isCommentOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div onClick={(e) => e.stopPropagation()}>
            <CommentWidget
              postId={id}
              isOpen={isCommentOpen}
              onClose={() => dispatch(setIsCommentOpen(false))}
              userId={userData?.id}
              notificationData={notificationData} // Pass the notification data
            />
          </div>
        </div>
      )}

      {/* Share Widget */}
      {showShareWidget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div onClick={(e) => e.stopPropagation()}>
            <ShareDialog 
              postId={id} 
              onClose={() => setShowShareWidget(false)} 
            />
          </div>
        </div>
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

      {/* Deleting Overlay */}
      {isLoading && (
        <div className="fixed inset-0 z-[60] bg-black bg-opacity-60 flex items-center justify-center">
          <div className="bg-black bg-opacity-80 rounded-lg px-4 py-2 flex items-center">
            <span className="text-white mr-2">Deleting</span>
            <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
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
    </div>
  );
}

export default ViewPost;