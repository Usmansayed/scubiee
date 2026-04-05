import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { IoChevronBack, IoChevronForward } from 'react-icons/io5';
const cloud = import.meta.env.VITE_CLOUD_URL;
const vcloud = import.meta.env.VITE_VIDEO_CLOUD_URL;

// Track user interaction at the module level
let userHasInteracted = false;
document.addEventListener('click', () => {
  userHasInteracted = true;
}, { once: true });

const ShortMediaCarousel = ({ 
  media = [], 
  postId, 
  currentIndex = 0, 
  isRedux = false, 
  onIndexChange, 
  api,
  isPrefetched = false,
  cachedMedia = null, // Accept cached media with blob URLs from parent
  onMediaLoaded, // <-- add this prop
  autoPlay = true, // Default to true for autoplay
  videoRef, // Added to connect to parent's useVideoAutoplay hook
  videoKey, // Added to identify this video uniquely
  onVideoPlay, // Added to notify parent when video plays
  onVideoPause, // Added to notify parent when video pauses
  isMuted = false, // Default to unmuted
  onVolumeChange, // Added to notify parent of volume changes
}) => {
  // Fallback UI for missing media
  if (!media || !Array.isArray(media) || media.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-900 md:rounded-t-2xl">
        <p className="text-gray-500">No media available</p>
      </div>
    );
  }

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  const [currentSlide, setCurrentSlide] = useState(currentIndex);
  const [isLoading, setIsLoading] = useState(!isPrefetched);
  const [isLargeScreen, setIsLargeScreen] = useState(window.innerWidth >= 1280);
  const internalVideoRef = useRef(null);
  const containerRef = useRef(null);
  const lastMediaKey = useRef(''); // Track last media key to detect changes
  const touchStartX = useRef(null);
  const loadingTimeoutRef = useRef(null); // Reference for loading timeout
  
  // Add state for video overlay (play/pause icons)
  const [videoOverlay, setVideoOverlay] = useState(null);

  // We keep a persistent video element reference to avoid remounting
  const videoElementRef = useRef(null);
  
  // Add a ref to track if we've attempted unmuted autoplay
  const unmutedAutoplayAttempted = useRef(false);

  // Check screen size for responsive navigation buttons
  useEffect(() => {
    const handleResize = () => {
      setIsLargeScreen(window.innerWidth >= 1280);
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Use cached media items if provided, otherwise process media array
  const mediaItems = useMemo(() => {
    if (cachedMedia) return cachedMedia;
    
    return media.map(item => {
      const mediaUrl = item.type === 'video'
        ? `${cloud}/cloudofscubiee/shortVideos/${item.url}`
        : `${cloud}/cloudofscubiee/shortImages/${item.url}`;
      
      return {
        ...item,
        cachedUrl: mediaUrl,
        blobUrl: null,        
        loaded: false
      };
    });
  }, [media, api, cachedMedia]);

  // Generate a unique key for the current media
  const currentMediaKey = useMemo(() => {
    if (!mediaItems || mediaItems.length === 0) return '';
    const item = mediaItems[currentSlide];
    return `${postId}-${currentSlide}-${item?.url || ''}`;
  }, [postId, currentSlide, mediaItems]);

  // Detect media changes to trigger loading states - fixed to prevent loops
  useEffect(() => {
    if (currentMediaKey !== lastMediaKey.current) {
      if (!isPrefetched) {
        setIsLoading(true); // Reset loading state when media changes
        
        // Set a timeout to hide the loader after 3 seconds even if load events don't fire
        if (loadingTimeoutRef.current) {
          clearTimeout(loadingTimeoutRef.current);
        }
        
        loadingTimeoutRef.current = setTimeout(() => {
          setIsLoading(false);
        }, 3000); // 3 seconds safety timeout
      }
      lastMediaKey.current = currentMediaKey;
    }
    
    return () => {
      // Clean up timeout when component or media changes
      if (loadingTimeoutRef.current) {
        clearTimeout(loadingTimeoutRef.current);
      }
    };
  }, [currentMediaKey, isPrefetched]);
  

  // Handle media index changes from parent - fixed to prevent unnecessary state updates
  useEffect(() => {
    if (currentIndex >= 0 && currentIndex < mediaItems.length && currentIndex !== currentSlide) {
      setCurrentSlide(currentIndex);
    }
  }, [currentIndex, mediaItems.length, currentSlide]);

  // Add this new effect to try to enable unmuted autoplay
  useEffect(() => {
    // Store original volume to restore later
    const originalVolume = localStorage.getItem('userVolume') || 1;
    
    // Helper function to attempt unmuted autoplay
    const attemptUnmutedAutoplay = async () => {
      try {
        if (!internalVideoRef.current || unmutedAutoplayAttempted.current) return;
        
        unmutedAutoplayAttempted.current = true;
        internalVideoRef.current.muted = false;
        internalVideoRef.current.volume = parseFloat(originalVolume);
        
        // Create a short audio context to unlock audio
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) {
          const audioCtx = new AudioContext();
          const source = audioCtx.createBufferSource();
          source.buffer = audioCtx.createBuffer(1, 1, 22050);
          source.connect(audioCtx.destination);
          source.start(0);
          if (audioCtx.state === 'suspended') {
            await audioCtx.resume();
          }
        }
        
        // Attempt to play the video unmuted
        if (internalVideoRef.current && internalVideoRef.current.paused) {
          await internalVideoRef.current.play();
          
          if (onVideoPlay) {
            onVideoPlay(internalVideoRef.current);
          }
        }
      } catch (error) {
        console.log("Unmuted autoplay still blocked by browser:", error);
        
        // Fall back to muted if necessary
        if (internalVideoRef.current) {
          internalVideoRef.current.muted = true;
          internalVideoRef.current.play().catch(e => {
            console.error("Failed to play even with mute:", e);
          });
        }
      }
    };
    
    // Try to enable unmuted autoplay on any user interaction
    const enableUnmutedOnInteraction = () => {
      if (userHasInteracted && internalVideoRef.current) {
        attemptUnmutedAutoplay();
      }
    };
    
    // Try to enable unmuted autoplay whenever the video reference changes or on user interaction
    if (internalVideoRef.current) {
      // Try unmuted autoplay when component mounts or video changes
      attemptUnmutedAutoplay();
      
      // Add listener for user interactions
      document.addEventListener('click', enableUnmutedOnInteraction);
      document.addEventListener('touchstart', enableUnmutedOnInteraction);
    }
    
    return () => {
      // Clean up listeners
      document.removeEventListener('click', enableUnmutedOnInteraction);
      document.removeEventListener('touchstart', enableUnmutedOnInteraction);
    };
  }, [internalVideoRef.current, onVideoPlay]);

  // Handle video playback for current slide - with enhanced logic for autoplay coordination
  useEffect(() => {
    const currentItem = mediaItems[currentSlide];
    if (!currentItem) return;

    if (currentItem.type === 'video') {
      // Use the internal reference if external not provided
      const videoElement = internalVideoRef.current;
      if (!videoElement) return;

      // For videos, immediately hide our custom loading spinner
      setIsLoading(false);
      
      // Use blob URL if available, otherwise use original URL
      const videoSrc = currentItem.blobUrl || currentItem.cachedUrl;
      
      // Only update src if it's different to prevent unnecessary reloads
      if (videoElement.src !== videoSrc) {
        videoElement.src = videoSrc;
      }

      // ALWAYS try to play unmuted first
      videoElement.muted = false;
      
      // Remove controls to use our custom overlays
      videoElement.controls = false;
      
      // Setup video events with callback handling for parent coordination
      const handleLoadedData = () => {
        if (onMediaLoaded) onMediaLoaded();
        
        // Try to force unmuted playback when data is loaded
        if (!videoElement.paused) return;
        
        videoElement.muted = false;
        videoElement.play().catch(err => {
          console.log("Unmuted autoplay prevented on data load:", err);
          if (!videoElement.muted) {
            videoElement.muted = true;
            videoElement.play().catch(e => console.error("Failed to play even with mute:", e));
          }
        });
      };
      
      const handleCanPlay = () => {
        // Only attempt to play if autoPlay is enabled
        if (autoPlay) {
          // Always try to play unmuted first
          videoElement.muted = false;
          
          const playPromise = videoElement.play();
          if (playPromise !== undefined) {
            playPromise
              .then(() => {
                // Video played successfully unmuted - notify parent
                if (onVideoPlay) onVideoPlay(videoElement);
                
                // Show play overlay briefly
                setVideoOverlay('play');
                setTimeout(() => {
                  setVideoOverlay(null);
                }, 800);
              })
              .catch(error => {
                console.log("Unmuted autoplay prevented:", error);
                // Only try with muted if autoplay was prevented and we weren't already muted
                if (!videoElement.muted) {
                  console.log("Falling back to muted autoplay");
                  videoElement.muted = true;
                  videoElement.play()
                    .then(() => {
                      // Show muted notification or UI cue to user that they need to unmute
                      if (onVideoPlay) onVideoPlay(videoElement);
                    })
                    .catch(e => console.error("Failed to play even with mute:", e));
                }
              });
          }
        }
      };

      const handlePlay = () => {
        if (onVideoPlay) onVideoPlay(videoElement);
      };

      const handlePause = () => {
        if (onVideoPause) onVideoPause(videoElement);
      };
      
      const handleVolumeChange = (e) => {
        if (onVolumeChange) onVolumeChange(e);
      };
      
      const handleError = (e) => {
        console.error("Video error:", e);
      };

      // Add additional event to try unmuting video after playback starts
      const handlePlaying = () => {
        // Try to unmute if muted
        if (videoElement.muted && userHasInteracted) {
          videoElement.muted = false;
        }
      };
      
      // Add event listeners
      videoElement.onloadeddata = handleLoadedData;
      videoElement.oncanplay = handleCanPlay;
      videoElement.onplaying = handlePlaying;
      videoElement.onplay = handlePlay;
      videoElement.onpause = handlePause;
      videoElement.onvolumechange = handleVolumeChange;
      videoElement.onerror = handleError;
      
      // Create the video element reference if it doesn't exist
      if (!videoElementRef.current) {
        videoElementRef.current = videoElement;
      }

      // Connect to parent's video registration if provided
      if (videoRef && typeof videoRef === 'function') {
        videoRef(videoElement);
      }
      
      // Clean up event listeners
      return () => {
        if (videoElement) {
          videoElement.onloadeddata = null;
          videoElement.oncanplay = null;
          videoElement.onplaying = null;
          videoElement.onplay = null;
          videoElement.onpause = null;
          videoElement.onvolumechange = null;
          videoElement.onerror = null;
        }
      };
    }
  }, [currentSlide, mediaItems, isPrefetched, isLoading, autoPlay, onMediaLoaded, 
       videoRef, onVideoPlay, onVideoPause, onVolumeChange, isMuted]);

  // Navigation handlers
  const handlePrevSlide = useCallback(() => {
    const newIndex = (currentSlide - 1 + mediaItems.length) % mediaItems.length;
    setCurrentSlide(newIndex);
    if (onIndexChange) onIndexChange(postId, newIndex);
  }, [currentSlide, mediaItems.length, onIndexChange, postId]);

  const handleNextSlide = useCallback(() => {
    const newIndex = (currentSlide + 1) % mediaItems.length;
    setCurrentSlide(newIndex);
    if (onIndexChange) onIndexChange(postId, newIndex);
  }, [currentSlide, mediaItems.length, onIndexChange, postId]);

  // Touch event handlers for swipe navigation
  const handleTouchStart = useCallback((e) => {
    touchStartX.current = e.touches[0].clientX;
  }, []);

  const handleTouchEnd = useCallback((e) => {
    if (touchStartX.current === null) return;
    
    const touchEndX = e.changedTouches[0].clientX;
    const diffX = touchStartX.current - touchEndX;
    
    // Swipe threshold - adjust as needed for sensitivity
    if (Math.abs(diffX) > 50) {
      if (diffX > 0) {
        // Swipe left, go to next slide
        handleNextSlide();
      } else {
        // Swipe right, go to previous slide
        handlePrevSlide();
      }
    }
    
    touchStartX.current = null;
  }, [handleNextSlide, handlePrevSlide]);

  // Get current media item
  const currentItem = mediaItems[currentSlide];
  if (!currentItem) return null;
  
  const isCurrentMediaVideo = currentItem.type === 'video';
  
  // Use blob URL if available, otherwise use original URL
  const mediaUrl = currentItem.blobUrl || currentItem.cachedUrl;
  
  // Handle image loading - Improved to be more reliable
  const handleImageLoad = () => {
    setIsLoading(false);
    
    // Clear loading timeout since image is loaded
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
    
    if (onMediaLoaded) onMediaLoaded();
  };

  const handleImageError = (e) => {
    console.error("Image error:", e);
    setIsLoading(false);
    
    // Clear loading timeout on error
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
    
    e.target.src = '/logos/DefaultPicture.png'; // Fallback image
  };

  const handleError = (e) => {
    console.error("Video error:", e);
    setIsLoading(false);
    
    // Clear loading timeout on error
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }
  };

  // Modified handleVideoClick to force unmute
  const handleVideoClick = (e) => {
    e.stopPropagation();
    const videoElement = internalVideoRef.current;
    if (!videoElement) return;
    
    // Mark user interaction at module level for other videos
    userHasInteracted = true;
    
    // Toggle play/pause with overlay feedback
    if (videoElement.paused) {
      // ALWAYS unmute on user interaction
      videoElement.muted = false;
      
      const playPromise = videoElement.play();
      if (playPromise !== undefined) {
        playPromise.then(() => {
          // Show play icon briefly
          setVideoOverlay('play');
          setTimeout(() => {
            setVideoOverlay(null);
          }, 800);
          
          // Notify parent
          if (onVideoPlay) onVideoPlay(videoElement);
        }).catch(err => {
          console.error('Error playing video:', err);
          
          // Fall back to muted only as last resort
          if (!videoElement.muted) {
            videoElement.muted = true;
            videoElement.play().catch(e => console.error("Failed to play even with mute:", e));
          }
        });
      }
    } else {
      videoElement.pause();
      
      // Show pause icon briefly
      setVideoOverlay('pause');
      setTimeout(() => {
        setVideoOverlay(null);
      }, 800);
      
      // Notify parent
      if (onVideoPause) onVideoPause(videoElement);
    }
  };

  return (
    <div 
      ref={containerRef}
      className="relative w-full h-full md:rounded-t-2xl overflow-hidden"
      onTouchStart={mediaItems.length > 1 ? handleTouchStart : undefined}
      onTouchEnd={mediaItems.length > 1 ? handleTouchEnd : undefined}
    >
      {/* Loading spinner - only show for images that are still loading, not videos */}
      {isLoading && !isCurrentMediaVideo && (
        <div className="absolute inset-0 bg-gray-800 animate-pulse flex items-center justify-center z-10">
          <div className="w-12 h-12 border-4 border-t-primary border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin"></div>
        </div>
      )}
      
      {/* Media display */}
      <div className="w-full h-full">
        {isCurrentMediaVideo ? (
          <div className="relative w-full h-full video-container" data-video-id={videoKey}>
            <video
              ref={internalVideoRef}
              key={`video-${postId}`}
              src={mediaUrl}
              className={`w-full h-full object-cover transition-opacity duration-200 ${isLoading ? 'opacity-30' : 'opacity-100'}`}
              playsInline
              preload="auto"
              loop
              muted={isMuted} // Set initial muted state from props (default false)
              controlsList="nodownload"
              onClick={handleVideoClick}
              onLoadedData={() => {
                setIsLoading(false);
                // Clear the loading timeout
                if (loadingTimeoutRef.current) {
                  clearTimeout(loadingTimeoutRef.current);
                  loadingTimeoutRef.current = null;
                }
                if (onMediaLoaded) onMediaLoaded();
              }}
              onError={handleError}
            />
            
            {/* Play/Pause Icons Overlay */}
            {videoOverlay === 'play' && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/20 animate-fadeOut">
                <div className="rounded-full bg-black/50 p-3">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 scale-110 text-white" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M8 5v14l11-7z"/>
                  </svg>
                </div>
              </div>
            )}
            
            {videoOverlay === 'pause' && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                <div className="rounded-full bg-black/50 p-3">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-12 w-12 scale-110 text-white" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
                  </svg>
                </div>
              </div>
            )}
            
            {/* Add unmute icon if video is muted */}
            {internalVideoRef.current && internalVideoRef.current.muted && (
              <div className="absolute bottom-4 right-4 bg-black/60 p-2 rounded-full text-white cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (internalVideoRef.current) {
                      internalVideoRef.current.muted = false;
                      if (onVolumeChange) onVolumeChange({ target: internalVideoRef.current });
                    }
                  }}>
                <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                </svg>
              </div>
            )}
          </div>
        ) : (
          <img
            key={currentMediaKey}
            src={mediaUrl}
            alt="Short content"
            className={`w-full h-full object-cover transition-opacity duration-300 ${isLoading ? 'opacity-30' : 'opacity-100'}`}
            onLoad={handleImageLoad}
            onError={handleImageError}
          />
        )}
      </div>

      {/* Navigation dots */}
      {mediaItems.length > 1 && (
        <div className="absolute bottom-0 left-0 right-0 flex justify-center pb-3 z-10">
          <div className="flex space-x-1">
            {mediaItems.map((_, index) => (
              <div
                key={index}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${
                  index === currentSlide ? 'bg-white' : 'bg-gray-400'
                }`}
              />
            ))}
          </div>
        </div>
      )}

      {/* Navigation arrows - only show on large screens (≥1280px) */}
      {mediaItems.length > 1 && isLargeScreen && (
        <>
          <button
            className="absolute left-2 top-1/2 transform -translate-y-1/2 text-white bg-black bg-opacity-50 p-2 rounded-full z-10"
            onClick={handlePrevSlide}
          >
            <IoChevronBack size={20} />
          </button>
          <button
            className="absolute right-2 top-1/2 transform -translate-y-1/2 text-white bg-black bg-opacity-50 p-2 rounded-full z-10"
            onClick={handleNextSlide}
          >
            <IoChevronForward size={20} />
          </button>
        </>
      )}
    </div>
  );
};

// Use React.memo to prevent unnecessary re-renders
export default React.memo(ShortMediaCarousel);
