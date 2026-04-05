import React, { useState, useRef, useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { IoMdHeartEmpty, IoMdHeart } from "react-icons/io";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import { MdOutlineContentCopy, MdOutlineReport, MdOutlineDeleteOutline } from "react-icons/md";
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { IoCloseSharp } from "react-icons/io5";
import { toast } from 'react-toastify';
import { createPortal } from 'react-dom';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import { toggleLikePost, toggleSavePost, setVideoPlaying } from '../Slices/HomeSlice';

// Smart Truncate Text component
const SmartTruncateText = ({ text, className = '' }) => {
  const textRef = useRef(null);
  const [needsTruncate, setNeedsTruncate] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isCalculated, setIsCalculated] = useState(false);

  // Calculate if text needs truncation
  const calculateTruncation = () => {
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
  };

  // Toggle expanded state
  const toggleExpand = () => {
    setIsExpanded(!isExpanded);
  };

  // Calculate truncation on mount and window resize
  useEffect(() => {
    calculateTruncation();
    
    // Recalculate on window resize
    const handleResize = () => {
      calculateTruncation();
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <>
      <p
        ref={textRef}
        className={`${className} ${isExpanded ? '' : needsTruncate ? 'truncated-text' : ''}`}
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

// Updated component for horizontal scrolling of all media (images and videos)
const HorizontalImageScroll = ({ imageFiles, post, handleImageClick, cloud, registerVideo, handleVideoClick }) => {
  const [scrollRef, scrollIndex] = useHorizontalScrollIndex(imageFiles.length);
  const isLargeScreen = window.innerWidth >= 768;
  
  // Add new state to track which videos have been clicked (to show controls)
  const [clickedVideos, setClickedVideos] = useState({});

  // New function to handle video clicks within the carousel
  const handleVideoContainerClick = (e, mediaUrl) => {
    e.stopPropagation();
    const videoElement = e.currentTarget.querySelector('video');
    if (!videoElement) return;
    
    // Toggle video controls visibility
    const videoId = `${post.id}-${mediaUrl}`;
    setClickedVideos(prev => ({
      ...prev,
      [videoId]: true
    }));
    
    // Show controls when clicked
    videoElement.controls = true;
    
    // Toggle play/pause
    if (videoElement.paused) {
      videoElement.play().catch(err => {
        console.error('Error playing video:', err);
      });
    } else {
      videoElement.pause();
    }
    
    // Also call the parent handler to update Redux state
    handleVideoClick(e, post.id, mediaUrl);
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
          >
            <div className="[aspect-ratio:1/1] w-full">
              {media.type === 'video' ? (
                <div 
                  className="w-full h-full video-container bg-black md:rounded-lg cursor-pointer overflow-hidden" 
                  data-video-id={`${post.id}-${media.url}`}
                  onClick={(e) => handleVideoContainerClick(e, media.url)}
                >
                  <video 
                    ref={(el) => el && registerVideo(`${post.id}-${media.url}`, el)}
                    src={`${cloud}/cloudofscubiee/${media.type === 'video' ? 'postVideos' : 'postImages'}/${media.url}`}
                    className="w-full h-full object-contain max-h-[550px]" 
                    controls={clickedVideos[`${post.id}-${media.url}`]}
                    muted
                    loop
                    playsInline
                    preload="metadata"
                  />
                </div>
              ) : (
                <img 
                  src={`${cloud}/cloudofscubiee/postImages/${media.url}`}
                  alt={`Media ${i}`} 
                  loading="lazy"
                  className="w-full h-full object-cover md:rounded-lg cursor-pointer"
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

// Portal component for modal-like UI elements
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted ? createPortal(children, document.body) : null;
};

const Post = ({ 
  post, 
  isLastPost = false, 
  lastPostRef = null,
  cloud,
  registerVideo,
  handleVideoClick,
  handleImageClick,
  showCopyNotification,
  setShowCopyNotification,
  setSharePostId,
  setShowShareWidget,
  setCommentPostId,
  setReportType,
  setReportTargetId,
  setShowReportWidget,
  setDeleteConfirmation,
  isOnline
}) => {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const userData = useSelector((state) => state.user.userData);
  const likedPosts = useSelector((state) => state.home.likedPosts);
  const savedPosts = useSelector((state) => state.home.savedPosts);
  
  // Local state
  const [activeMenu, setActiveMenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const menuRef = useRef(null);
  
  // Track visual state (for optimistic updates)
  const visualState = useRef({
    likedPosts: {},
    savedPosts: {}
  });
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map());
  
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
      window.removeEventListener('scroll', handleScroll);
    };
  }, [activeMenu]);
  
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
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
      });
    }
  
    const postIdStr = postId.toString();
    
    // Remember the ORIGINAL backend state (from Redux)
    const originalBackendState = likedPosts[postId] || false;
    
    // TOGGLE the local visual state
    const hasVisualState = postIdStr in visualState.current.likedPosts;
    const currentVisualState = hasVisualState 
      ? visualState.current.likedPosts[postIdStr] 
      : originalBackendState;
    
    const newVisualState = !currentVisualState;
    visualState.current.likedPosts[postIdStr] = newVisualState;
    
    // If this is a like action (not unlike), show a heart animation
    if (newVisualState) {
      try {
        // Create and animate a heart element
        const heartAnimation = document.createElement('div');
        heartAnimation.innerHTML = '❤️';
        heartAnimation.className = 'absolute z-10 text-red-500 transition-all duration-700 opacity-0';
        heartAnimation.style.fontSize = '2.5rem';
        
        // Position the heart near the like button
        let buttonElement = null;
        
        if (e && e.currentTarget) {
          buttonElement = e.currentTarget;
        }
        
        // If we have a valid button element, proceed with the animation
        if (buttonElement) {
          const rect = buttonElement.getBoundingClientRect();
          document.body.appendChild(heartAnimation);
          
          heartAnimation.style.position = 'fixed';
          heartAnimation.style.left = `${rect.left + rect.width / 2}px`;
          heartAnimation.style.top = `${rect.top}px`;
          
          // Animate the heart
          setTimeout(() => {
            heartAnimation.style.transform = 'translateY(-120px) scale(1.5)';
            heartAnimation.style.opacity = '1';
          }, 0);
          
          // Remove the heart element after animation completes
          setTimeout(() => {
            if (document.body.contains(heartAnimation)) {
              document.body.removeChild(heartAnimation);
            }
          }, 700);
        }
      } catch (error) {
        // Fail silently - animation is non-critical
        console.log("Animation error:", error);
      }
    }
    
    // Update UI immediately for better UX
    const likeButtons = document.querySelectorAll(`[data-like-button="${postId}"]`);
    likeButtons.forEach(button => {
      // Update icon
      const emptyHeart = button.querySelector('.empty-heart');
      const filledHeart = button.querySelector('.filled-heart');
      
      if (emptyHeart && filledHeart) {
        emptyHeart.style.display = newVisualState ? 'none' : 'block';
        filledHeart.style.display = newVisualState ? 'block' : 'none';
      }
      
      // Update count
      const originalCount = post?.likes || 0;
      const visualDelta = newVisualState !== originalBackendState ? (newVisualState ? 1 : -1) : 0;
      const newCount = Math.max(0, originalCount + visualDelta);
      
      const countSpan = button.querySelector('span');
      if (countSpan) countSpan.textContent = newCount.toLocaleString() || '0';
    });
    
    // Debounce the API call
    if (pendingLikeOperations.current.has(postIdStr)) {
      clearTimeout(pendingLikeOperations.current.get(postIdStr));
    }
    
    const timerId = setTimeout(() => {
      // Only make the API call if the final visual state differs from backend state
      if (visualState.current.likedPosts[postIdStr] !== originalBackendState) {
        // Include explicit action parameter based on target state
        dispatch(toggleLikePost({
          postId, 
          finalState: visualState.current.likedPosts[postIdStr],
          action: visualState.current.likedPosts[postIdStr] ? 'like' : 'unlike'
        }));
      }
      pendingLikeOperations.current.delete(postIdStr);
    }, 500);
    
    pendingLikeOperations.current.set(postIdStr, timerId);
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
  
  // Handle comment click
  const handleCommentClick = (postId, e) => {
    if (e) e.stopPropagation();
    dispatch(setIsCommentOpen(true));
    setCommentPostId(postId);
  };
  
  // Handle share post
  const handleSharePost = (postId, e) => {
    if (e) e.stopPropagation();
    setSharePostId(postId);
    setShowShareWidget(true);
  };
  
  // Handle copy link
  const handleCopyLink = (postId, e) => {
    e.stopPropagation();
    const postUrl = `${window.location.origin}/viewpost/${postId}`;
    
    navigator.clipboard.writeText(postUrl)
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
  
  // Handle delete post
  const handleDeletePost = (postId, e) => {
    e.stopPropagation();
    console.log("Delete post clicked", postId);
    
    if (!isOnline) {
      toast.warning("You're offline. Please try again when connected.");
      return;
    }
    
    // If it's user's own post, allow deletion
    if (!post) {
      console.log("Post not found");
      return;
    }
    
    // Check if user is the author
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
  
  // Handle reporting
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

  // Updated wrapper function for single video clicks with consistent toggle behavior
  const handleSingleVideoClick = (e, postId, videoUrl) => {
    e.stopPropagation();
    
    const videoElement = e.currentTarget.querySelector('video');
    if (!videoElement) return;
    
    // Always show controls on click
    videoElement.controls = true;
    
    // Toggle play/pause directly
    if (videoElement.paused) {
      videoElement.play().catch(err => {
        console.error('Error playing video:', err);
      });
    } else {
      videoElement.pause();
    }
    
    // Call the main video click handler from parent
    handleVideoClick(e, postId, videoUrl);
  };

  return (
    <article
      ref={isLastPost ? lastPostRef : null}
      className="overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818] bg-[#0a0a0a] md:bg-[#0c0c0c] backdrop-blur-sm py-2 max-md:py-2 text-gray-300"
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
            <div className="absolute inset-0 bg-black/10 group-hover:bg-black/0"></div>
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
            className="text-gray-400 hover:text-white p-1 rounded-full hover:bg-gray-800/30" 
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
      <div className="pr-4 pl-4 max-md:px-0 cursor-pointer">
        {/* Text Content */}
        {(post.title || post.content || post.description) && (
          <div className="mb-4 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2 whitespace-pre-line">
            <SmartTruncateText
              text={post.title || post.content || post.description}
              className="text-[16px] lg:text-[16.2px] font-sans text-gray-300 max-md:font-medium"
            />
          </div>
        )}

        {/* Media Content */}
        {post.media && post.media.length > 0 && (
          <div className="relative mb-4 max-md:mb-0 xl:w-[84%] md:w-[90%] mx-auto w-full">
            {/* Single media item - full width for both mobile and desktop */}
            {post.media.length === 1 ? (
              <div className="relative mb-4">
                <div className="w-[98%] mx-auto" style={{ maxHeight: '550px' }}>
                  {post.media[0].type === 'video' ? (
                    <div 
                      className="w-full h-full video-container bg-black md:rounded-lg cursor-pointer overflow-hidden" 
                      data-video-id={`${post.id}-${post.media[0].url}`}
                      onClick={(e) => handleSingleVideoClick(e, post.id, post.media[0].url)}
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
                    </div>
                  ) : (
                    <img 
                      src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                      alt="Post media" 
                      loading="lazy"
                      className="w-full h-auto object-cover md:rounded-lg cursor-pointer max-h-[550px]"
                      onClick={(e) => handleImageClick(e, post.media[0], post, 0)}
                    />
                  )}
                </div>
              </div>
            ) : (
              /* Multiple media - carousel with updated component */
              <HorizontalImageScroll 
                imageFiles={post.media}
                post={post}
                handleImageClick={handleImageClick}
                cloud={cloud}
                registerVideo={registerVideo}
                handleVideoClick={handleVideoClick}  // Pass the parent handler
              />
            )}
          </div>
        )}
      </div>

      {/* Post Actions */}
      <div className="flex items-center md:w-[84%] xl:w-[78%] md:pl-[1px] md:mx-auto max-md:mr-[8px] max-md:ml-2 max-md:px-2 mb-3 max-md:mb-0 mt-2">
        {/* Like Button */}
        <button 
          className="flex items-center gap-2 text-gray-300 group transform transition-transform duration-200"
          onClick={(e) => handleLikeToggle(post.id, e)}
          data-like-button={post.id}
        >
          <div className="p-1.2 rounded-full">
            <IoMdHeartEmpty 
              className="h-[22px] w-[22px] empty-heart" 
              style={{display: likedPosts[post.id] ? 'none' : 'block'}} 
            />
            <IoMdHeart 
              className="h-[22px] w-[22px] text-red-500 group-hover:text-red-400 filled-heart" 
              style={{display: likedPosts[post.id] ? 'block' : 'none'}} 
            />
          </div>
          <span className='text-[14px]'>
            {post.likes?.toLocaleString() || '0'}
          </span>
        </button>

        {/* Comment Button */}
        <button 
          className="flex items-center gap-2 text-gray-300 ml-6 group"
          onClick={(e) => handleCommentClick(post.id, e)}
        >
          <div className="p-1.2 rounded-full">
            <TfiCommentAlt className="mt-[1px] h-[18px] w-[18px]" />
          </div>
          <span className='text-[14px] mt-[-1px]'>
            {(post.comments > 0) ? post.comments : '0'}
          </span>
        </button>

        {/* Share Button */}
        <button 
          className="flex items-center text-gray-300 ml-auto group"
          onClick={(e) => handleSharePost(post.id, e)}
        >
          <div className="p-1.5 rounded-full">
            <BsSend className="h-[18px] w-[18px]" />
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
  );
};

export default Post;
