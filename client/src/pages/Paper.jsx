import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';
import { createPortal } from 'react-dom';
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";

const api = import.meta.env.VITE_API_URL;
const cloud = import.meta.env.VITE_CLOUD_URL;

// Portal component for modals
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted && typeof document !== 'undefined' ? createPortal(children, document.body) : null;
};

// Cool rotating loading animation component
const PaperLoadingAnimation = () => {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-[#0a0a0a]">
      <div className="relative">
        {/* Main rotating circle */}
        <div className="w-20 h-20 border-4 border-gray-700 border-t-blue-500 rounded-full animate-spin"></div>
        
        {/* Inner rotating circle */}
        <div className="absolute inset-2 w-16 h-16 border-3 border-gray-600 border-r-purple-500 rounded-full animate-spin" style={{ animationDirection: 'reverse', animationDuration: '1.5s' }}></div>
        
        {/* Center dot */}
        <div className="absolute inset-1/2 w-2 h-2 bg-blue-400 rounded-full transform -translate-x-1/2 -translate-y-1/2"></div>
        
        {/* Orbiting dots */}
        <div className="absolute inset-0 w-20 h-20">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="absolute w-3 h-3 bg-gradient-to-r from-blue-400 to-purple-500 rounded-full animate-spin"
              style={{
                top: '50%',
                left: '50%',
                transformOrigin: '50% 50%',
                transform: `translate(-50%, -50%) rotate(${i * 120}deg) translateY(-35px)`,
                animationDuration: '2s',
                animationDelay: `${i * 0.2}s`
              }}
            />
          ))}
        </div>
      </div>

      {/* Loading text */}
      <div className="mt-8 text-center">
        <h2 className="text-2xl font-bold text-white mb-2">
          Preparing Your Paper
        </h2>
        <div className="flex items-center justify-center space-x-1">
          <div className="text-gray-400">Curating personalized content</div>
          <div className="flex space-x-1">
            {[...Array(3)].map((_, i) => (
              <div
                key={i}
                className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"
                style={{
                  animationDelay: `${i * 0.2}s`,
                  animationDuration: '1s'
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

// Custom hook to measure text height and determine if it needs truncation
const useSmartTruncate = () => {
  const textRef = useRef(null);
  const [needsTruncate, setNeedsTruncate] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isCalculated, setIsCalculated] = useState(false);

  const calculateTruncation = useCallback(() => {
    if (textRef.current && !isExpanded) {
      const element = textRef.current;
      const lineHeight = parseInt(window.getComputedStyle(element).lineHeight);
      const maxHeight = lineHeight * 3; // 3 lines
      
      if (element.scrollHeight > maxHeight) {
        setNeedsTruncate(true);
      } else {
        setNeedsTruncate(false);
      }
      setIsCalculated(true);
    }
  }, [isExpanded]);

  const toggleExpand = () => {
    setIsExpanded(!isExpanded);
    if (!isExpanded) {
      setNeedsTruncate(false);
    }
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

  useEffect(() => {
    const timer = setTimeout(calculateTruncation, 100);
    const handleResize = () => calculateTruncation();
    window.addEventListener('resize', handleResize);
    
    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', handleResize);
    };
  }, [calculateTruncation]);
  return (
    <>
      <p
        ref={textRef}
        className={`${className} ${isExpanded ? 'whitespace-pre-line' : ''} ${isExpanded ? '' : needsTruncate ? 'line-clamp-3' : ''}`}
        style={{
          transition: 'max-height 0.3s ease-out'
        }}
      >
        {text}
      </p>
      
      {needsTruncate && isCalculated && (
        <button
          onClick={(e) => {
            e.preventDefault();
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
    if (!containerRef.current) return;

    const container = containerRef.current;
    const handleScroll = () => {
      const scrollLeft = container.scrollLeft;
      const itemWidth = container.scrollWidth / imageCount;
      const newIndex = Math.round(scrollLeft / itemWidth);
      setCurrentIndex(newIndex);
    };

    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, [imageCount]);

  useEffect(() => {
    setCurrentIndex(0);
  }, [imageCount]);

  return [containerRef, currentIndex];
}

// Horizontal Image Scroll component
const HorizontalImageScroll = ({ imageFiles, post, handleImageClick, handleVideoClick, videoOverlays, registerVideo }) => {
  const [scrollRef, scrollIndex] = useHorizontalScrollIndex(imageFiles.length);
  const isLargeScreen = window.innerWidth >= 768;

  const handleVideoClickInGrid = (e, postId, videoUrl) => {
    e.preventDefault();
    e.stopPropagation();
    handleVideoClick(postId, videoUrl);
  };
  return (
    <div className="relative mb-2">
      <div
        ref={scrollRef}
        className="flex overflow-x-auto snap-x snap-mandatory scrollbar-hide w-[100%] mx-auto py-1 space-x-0"
      >
        {imageFiles.map((media, i) => (
          <div 
            key={`media-${i}`} 
            className="flex-shrink-0 snap-start snap-always w-[100%] first:pl-0"
          >            <div className="aspect-square w-full">              {media.type === 'video' ? (
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
      
      <div className="absolute bottom-4 right-4 bg-black/60 px-2 py-1 rounded-full text-xs text-white">
        {imageFiles.length > 1 && (
          <span>{`${scrollIndex + 1}/${imageFiles.length}`}</span>
        )}
      </div>
      
      {isLargeScreen && imageFiles.length > 1 && (
        <>
          <button 
            className="absolute left-2 top-1/2 transform -translate-y-1/2 bg-black/60 p-2 rounded-full z-10 hover:bg-black/80 transition-all"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              scrollRef.current.scrollBy({ left: -scrollRef.current.clientWidth, behavior: 'smooth' });
            }}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button 
            className="absolute right-2 top-1/2 transform -translate-y-1/2 bg-black/60 p-2 rounded-full z-10 hover:bg-black/80 transition-all"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              scrollRef.current.scrollBy({ left: scrollRef.current.clientWidth, behavior: 'smooth' });
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
  const manuallyPaused = useRef({});
  const firstClickHandled = useRef({});

  const registerVideo = useCallback((id, element) => {
    if (!element) return;
    
    videoRefs.current[id] = element;
    
    if (observers.current[id]) {
      observers.current[id].disconnect();
    }
    
    const observer = new IntersectionObserver(
      ([entry]) => {
        visibilityRatios.current[id] = entry.intersectionRatio;
        
        const mostVisible = Object.keys(visibilityRatios.current).reduce((max, videoId) => {
          return visibilityRatios.current[videoId] > visibilityRatios.current[max] ? videoId : max;
        }, id);
        
        if (visibilityRatios.current[mostVisible] > 0.5) {
          setMostVisibleVideo(mostVisible);
        }
      },
      { threshold: [0, 0.25, 0.5, 0.75, 1] }
    );
    
    observer.observe(element);
    observers.current[id] = observer;
  }, [mostVisibleVideo]);
  
  const handleUserInteraction = useCallback((id) => {
    userInteracted.current[id] = true;
  }, []);
  
  const setManuallyPaused = useCallback((id, isPaused) => {
    manuallyPaused.current[id] = isPaused;
  }, []);
  
  const isManuallyPaused = useCallback((id) => {
    return manuallyPaused.current[id] || false;
  }, []);
  
  const hasUserInteracted = useCallback((id) => {
    return userInteracted.current[id] || false;
  }, []);
  
  const isFirstClickHandled = useCallback((id) => {
    return firstClickHandled.current[id] || false;
  }, []);
  
  const setFirstClickHandled = useCallback((id, handled) => {
    firstClickHandled.current[id] = handled;
  }, []);
  
  useEffect(() => {
    return () => {
      Object.values(observers.current).forEach(observer => observer.disconnect());
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

const Paper = () => {
  const { id: paperId } = useParams();
  const navigate = useNavigate();
  const { userData } = useSelector((state) => state.user);
  // Paper and post states
  const [paper, setPaper] = useState(null);
  const [posts, setPosts] = useState([]);
  const [hasMore, setHasMore] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  // UI states (similar to UsersPosts)
  const [likedPosts, setLikedPosts] = useState({});
  const [savedPosts, setSavedPosts] = useState({});
  const [playingVideos, setPlayingVideos] = useState({});
  const [videoOverlays, setVideoOverlays] = useState({});
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);
  const [activeMenu, setActiveMenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [sharePostId, setSharePostId] = useState(null);
  const [showCopyNotification, setShowCopyNotification] = useState(false);

  // Refs
  const observerRef = useRef(null);
  const menuRef = useRef(null);
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map());
  const visualState = useRef({
    likedPosts: {},
    savedPosts: {}
  });
  // Video autoplay hook
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
    const DefaultPicture = "/logos/DefaultPicture.png";
  // Fetch paper details and posts directly from PaperPosts table  const fetchPaperData = async () => {
    const fetchPaperData = async () => {
    try {
      setInitialLoading(true);
      
      console.log(`🔍 [FRONTEND DEBUG] Fetching paper data:`, {
        paperId,
        endpoint: `${api}/papers/simple-posts/${paperId}`,
        timestamp: new Date().toISOString()
      });
      
      // Fetch posts directly from PaperPosts table using simple endpoint
      const response = await axios.get(`${api}/papers/simple-posts/${paperId}`, {
        withCredentials: true
      });

      console.log(`📡 [FRONTEND DEBUG] API Response:`, {
        success: response.data.success,
        paperData: response.data.paper,
        postsCount: response.data.posts?.length || 0,
        paperReadStatus: response.data.paper?.isRead,
        fullResponse: response.data
      });

      if (response.data.success) {
        setPaper(response.data.paper);
        
        console.log(`📄 [FRONTEND DEBUG] Paper set:`, {
          paperTitle: response.data.paper?.title,
          isRead: response.data.paper?.isRead,
          paperDate: response.data.paper?.paperDate
        });
        
        // Use posts directly from the PaperPosts table
        const posts = response.data.posts || [];

        // Transform the data to match frontend expectations
        const transformedPosts = posts.map(post => ({
          ...post,
          // Map user interaction states
          isLiked: post.userInteraction?.liked || false,
          isSaved: post.userInteraction?.saved || false
        }));

        // Set posts directly from the posts column
        setPosts(transformedPosts);
        
        console.log(`📝 [FRONTEND DEBUG] Posts processed:`, {
          totalPosts: transformedPosts.length,
          firstPostTitle: transformedPosts[0]?.title || 'No posts'
        });
        
        // Set up liked and saved states
        const likedState = {};
        const savedState = {};
        
        transformedPosts.forEach(post => {
          likedState[post.id] = post.isLiked;
          savedState[post.id] = post.isSaved;
        });
        
        setLikedPosts(likedState);
        setSavedPosts(savedState);
        visualState.current.likedPosts = likedState;
        visualState.current.savedPosts = savedState;        // No need for pagination with papers - they provide a curated set
        setHasMore(false);

        // Paper is automatically marked as read by the backend when fetched
        console.log(`✅ [FRONTEND DEBUG] Paper loading completed successfully`);
      }
    } catch (error) {
      console.error('❌ [FRONTEND ERROR] Error fetching paper data:', {
        paperId,
        error: error.message,
        response: error.response?.data,
        status: error.response?.status
      });
      setError('Failed to load paper. Please try again.');
    } finally {
      setInitialLoading(false);
    }  };
  // Debounced like handler
  const handleLike = useCallback(async (postId, e) => {
    if (pendingLikeOperations.current.has(postId)) return;
    
    const currentLikedState = visualState.current.likedPosts[postId];
    const newLikedState = !currentLikedState;
    
    // If this is a like action (not unlike), show a simple upvote animation
    if (newLikedState) {
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
    
    // Optimistic update
    visualState.current.likedPosts[postId] = newLikedState;
    setLikedPosts(prev => ({ ...prev, [postId]: newLikedState }));
      pendingLikeOperations.current.set(postId, true);
    
    try {
      await axios.post(`${api}/post/like`, 
        { postId },
        {
          withCredentials: true
        }
      );
    } catch (error) {
      console.error('Error toggling like:', error);
      // Revert on error
      visualState.current.likedPosts[postId] = currentLikedState;
      setLikedPosts(prev => ({ ...prev, [postId]: currentLikedState }));
    } finally {
      pendingLikeOperations.current.delete(postId);
    }
  }, []);

  // Debounced save handler
  const handleSave = useCallback(async (postId) => {
    if (pendingSaveOperations.current.has(postId)) return;
    
    const currentSavedState = visualState.current.savedPosts[postId];
    const newSavedState = !currentSavedState;
    
    // Optimistic update
    visualState.current.savedPosts[postId] = newSavedState;
    setSavedPosts(prev => ({ ...prev, [postId]: newSavedState }));
    
    pendingSaveOperations.current.set(postId, true);
    
    try {      await axios.post(`${api}/post/save`, 
        { postId },
        {
          withCredentials: true
        }
      );
    } catch (error) {
      console.error('Error toggling save:', error);
      // Revert on error
      visualState.current.savedPosts[postId] = currentSavedState;
      setSavedPosts(prev => ({ ...prev, [postId]: currentSavedState }));
    } finally {
      pendingSaveOperations.current.delete(postId);
    }
  }, []);

  // Video handlers
  const handleVideoClick = useCallback((postId, videoUrl) => {
    const videoId = `${postId}-${videoUrl}`;
    const video = videoRefs.current[videoId];
    
    if (!video) return;

    if (!isFirstClickHandled(videoId)) {
      setFirstClickHandled(videoId, true);
      handleUserInteraction(videoId);
    }

    if (video.paused) {
      video.play();
      setManuallyPaused(videoId, false);
      setVideoOverlays(prev => ({ ...prev, [videoId]: 'play' }));
      setTimeout(() => {
        setVideoOverlays(prev => ({ ...prev, [videoId]: null }));
      }, 1000);
    } else {
      video.pause();
      setManuallyPaused(videoId, true);
      setVideoOverlays(prev => ({ ...prev, [videoId]: 'pause' }));
      setTimeout(() => {
        setVideoOverlays(prev => ({ ...prev, [videoId]: null }));
      }, 1000);
    }
  }, [videoRefs, isFirstClickHandled, setFirstClickHandled, handleUserInteraction, setManuallyPaused]);

  // Image viewer handlers
  const handleImageClick = useCallback((e, media, post, index) => {
    e.preventDefault();
    e.stopPropagation();
    
    const imageFiles = post.media.filter(m => m.type === 'image');
    setViewingImage({
      images: imageFiles,
      post: post
    });
    setImageIndex(index);
  }, []);

  const closeImageViewer = () => {
    setViewingImage(null);
    setImageIndex(0);
  };

  // Initialize paper data
  useEffect(() => {
    if (paperId) {
      fetchPaperData();
    }
  }, [paperId]);

  // Auto-play most visible video
  useEffect(() => {
    Object.keys(videoRefs.current).forEach(videoId => {
      const video = videoRefs.current[videoId];
      if (!video) return;

      if (videoId === mostVisibleVideo && !isManuallyPaused(videoId) && hasUserInteracted(videoId)) {
        video.play().catch(console.error);
      } else if (videoId !== mostVisibleVideo) {
        video.pause();
      }
    });
  }, [mostVisibleVideo, isManuallyPaused, hasUserInteracted]);

  // Handle menu clicks outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setActiveMenu(null);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Show loading animation
  if (initialLoading) {
    return <PaperLoadingAnimation />;
  }

  // Show error state
  if (error) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-center">          <div className="text-red-500 text-6xl mb-2">⚠️</div>
          <h2 className="text-2xl font-bold text-white mb-1">Oops! Something went wrong</h2>
          <p className="text-gray-400 mb-2">{error}</p>
          <button 
            onClick={() => window.location.reload()}
            className="bg-blue-500 hover:bg-blue-600 text-white px-6 py-2 rounded-lg transition-colors"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  // Show no paper found
  if (!paper) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-center">          <div className="text-gray-500 text-6xl mb-2">📄</div>
          <h2 className="text-2xl font-bold text-white mb-1">Paper Not Found</h2>
          <p className="text-gray-400 mb-2">The paper you're looking for doesn't exist or has been removed.</p>
          <button 
            onClick={() => navigate('/my-papers')}
            className="bg-blue-500 hover:bg-blue-600 text-white px-6 py-2 rounded-lg transition-colors"
          >
            Back to Papers
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#0a0a0a] min-h-screen">      {/* Header - simplified for Paper view */}
      <div className="sticky top-0 z-10 bg-[#0a0a0a] max-md:border-b border-gray-800 px-4 py-3">
        <div className="flex items-center justify-between max-w-[640px] mx-auto">
          <button 
            onClick={() => navigate('/my-papers')}
            className="text-white hover:text-gray-300 transition-colors"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h1 className="text-white font-semibold text-lg truncate mx-4">
            {paper.title || 'Your Paper'}
          </h1>
          <div className="w-6"></div>
        </div>
      </div>      {/* Posts Container - matching UsersPosts.jsx layout */}
      <div className="space-y-2 md:space-y-2 w-full my-2 mb-16 max-w-[640px] mx-auto">
        {posts.length === 0 && !initialLoading ? (
          <div className="flex flex-col items-center justify-center py-20 px-4">
            <div className="text-gray-500 text-6xl mb-2">📰</div>
            <h3 className="text-xl font-semibold text-white mb-2">No Posts Yet</h3>
            <p className="text-gray-400 text-center">
              We're still curating content for your paper. Check back later for personalized recommendations!
            </p>
          </div>
        ) : (
          posts.map((post, index) => (
            <article
              key={post.id}
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
                    onClick={(e) => {
                      e.stopPropagation();
                      const rect = e.currentTarget.getBoundingClientRect();
                      setMenuPosition({
                        top: rect.bottom + window.scrollY,
                        left: rect.left + window.scrollX - 150
                      });
                      setActiveMenu(activeMenu === post.id ? null : post.id);
                    }}
                    data-more-button="true"
                  >
                    <FiMoreVertical className="h-[19px] w-[19px]" />
                  </button>
                </div>
              </div>

              {/* Post Content */}
              <div 
                className="pr-4 pl-4 max-md:px-2 cursor-pointer"
                onClick={() => navigate(`/viewpost/${post.id}`)}
              >                {/* Text Content */}
                {(post.title || post.content || post.description) && (
                       <div className="mb-[10px] max-md:ml-2 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2">
                    <SmartTruncateText
                      text={post.title || post.content || post.description}
                      className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-semibold"
                    />
                  </div>
                )}

                {/* Media Content */}
                {post.media && post.media.length > 0 && (
                  <div className="relative mb-4 xl:w-[84%] md:w-[90%] mx-auto w-full">                    {/* Single media item - full width for both mobile and desktop */}
                    {post.media.length === 1 ? (                      <div className="relative mb-4">
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
                            </div>                          ) : (                            <img 
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
              </div>              {/* Post Actions */}
                    <div className="flex items-center md:w-[84%] xl:w-[78%] md:pl-[1px] md:mx-auto max-md:mr-[8px] max-md:ml-2 max-md:px-2 mb-3 max-md:mb-1 mt-1">                      {/* Upvote Button - Reddit/Daily.dev style */}
                <button 
                  className={`flex items-center gap-1 px-3 py-[4px] rounded-full border transition-all duration-200 transform hover:scale-105 ${
                    likedPosts[post.id] 
                      ? ' border-gray-500 bg-white/05 text-gray-200' 
                      : 'border-gray-500 bg-white/05 text-gray-300 '
                  }`}                  onClick={(e) => {
                    e.stopPropagation();
                    handleLike(post.id, e);
                  }}
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
                  onClick={(e) => {
                    e.stopPropagation();
                    // Handle comment click
                  }}
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
                  onClick={(e) => {
                    e.stopPropagation();
                    // Handle share
                  }}
                >
                  <div className="p-1.5 rounded-full transition-colors duration-200">
                    <BsSend className="h-[18px] w-[18px]  transition-colors duration-200" />
                  </div>
                </button>

                {/* Save Button */}
                <button 
                  className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSave(post.id);
                  }}
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
        )}
        {/* Loading More Indicator */}
        {loadingMore && (
          <div className="py-8 w-full text-center">
            <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent align-[-0.125em] motion-reduce:animate-[spin_1.5s_linear_infinite]">
              <span className="!absolute !-m-px !h-px !w-px !overflow-hidden !whitespace-nowrap !border-0 !p-0 ![clip:rect(0,0,0,0)]">
                Loading more...
              </span>
            </div>
          </div>
        )}

        {/* End of Posts Message */}
        {!hasMore && posts.length > 0 && (
          <div className="text-center py-6 text-gray-400">
            <p>You've reached the end of your paper!</p>
          </div>
        )}
      </div>

      {/* Image Viewer Modal */}
      {viewingImage && (
        <Portal>
          <div className="fixed inset-0 bg-black bg-opacity-90 z-50 flex items-center justify-center">
            <button 
              onClick={closeImageViewer}
              className="absolute top-4 right-4 text-white hover:text-gray-300 z-10"
            >
              <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
            
            <div className="relative w-full h-full flex items-center justify-center p-4">
              <img 
                src={`${cloud}/cloudofscubiee/postImages/${viewingImage.images[imageIndex]?.url}`}
                alt="Viewing" 
                className="max-w-full max-h-full object-contain"
              />
              
              {viewingImage.images.length > 1 && (
                <>
                  <button 
                    onClick={() => setImageIndex(prev => 
                      prev > 0 ? prev - 1 : viewingImage.images.length - 1
                    )}
                    className="absolute left-4 top-1/2 transform -translate-y-1/2 bg-black bg-opacity-50 p-2 rounded-full text-white hover:bg-opacity-75"
                  >
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                  </button>
                  <button 
                    onClick={() => setImageIndex(prev => 
                      prev < viewingImage.images.length - 1 ? prev + 1 : 0
                    )}
                    className="absolute right-4 top-1/2 transform -translate-y-1/2 bg-black bg-opacity-50 p-2 rounded-full text-white hover:bg-opacity-75"
                  >
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                  
                  <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 bg-black bg-opacity-50 px-3 py-1 rounded-full text-white text-sm">
                    {imageIndex + 1} / {viewingImage.images.length}
                  </div>
                </>
              )}
            </div>
          </div>
        </Portal>
      )}
    </div>
  );
};

export default Paper;