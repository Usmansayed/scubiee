import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import { 
  ArrowLeft, 
  Users, 
  Globe, 
  Lock, 
  Shield,
  Settings,
  UserPlus,
  UserMinus,
  MoreVertical,
  Edit,
  Share2,
  Flag,
  Crown,
  Sparkles,
  Plus,
  Calendar,
  Hash,
  Trash2,
  ChevronDown
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import axios from 'axios';
import { toast } from 'react-toastify';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import { MdOutlineReport, MdOutlineContentCopy } from "react-icons/md";
import { IoCloseSharp } from "react-icons/io5";
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { createPortal } from 'react-dom';
import PostWidget from "../components/PostWidget";
import CommentWidget from "../components/CommentWidget";
import ShareDialog from "../components/shareWidget";
import ReportWidget from "../components/ReportWidget";
import { setIsCommentOpen } from '../Slices/WidgetSlice';

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

  useEffect(() => {
    calculateTruncation();
  }, [text, calculateTruncation]);

  useEffect(() => {
    const handleResize = () => calculateTruncation();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [calculateTruncation]);
  return (
    <div>
      <p
        ref={textRef}
        className={`${className} ${isExpanded ? 'whitespace-pre-line' : ''} ${!isCalculated ? 'opacity-0' : 'opacity-100'}`}
        style={{
          display: isExpanded ? 'block' : '-webkit-box',
          WebkitLineClamp: isExpanded ? 'unset' : needsTruncate ? '4' : 'unset',
          WebkitBoxOrient: 'vertical',
          overflow: isExpanded ? 'visible' : 'hidden',
          transition: 'opacity 0.2s ease-in-out'
        }}
      >
        {text}
      </p>
      {needsTruncate && (
        <button
          onClick={toggleExpand}
          className="text-gray-400 hover:text-white mt-2 text-sm font-medium transition-colors"
        >
          {isExpanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
};

const CommunityDetail = () => {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const { id } = useParams();
  const { userData } = useSelector((state) => state.user);
  const { isCommentOpen } = useSelector((state) => state.widget);
  const api = import.meta.env.VITE_API_URL;
  const cloud = import.meta.env.VITE_CLOUD_URL;

  // State management
  const [community, setCommunity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isJoined, setIsJoined] = useState(false);
  const [isJoining, setIsJoining] = useState(false);
  const [userRole, setUserRole] = useState(null); // 'creator', 'contributor', 'member', null
  const [showMenu, setShowMenu] = useState(false);
  const [posts, setPosts] = useState([]);
  const [postsLoading, setPostsLoading] = useState(false);
  const [likedPosts, setLikedPosts] = useState({});
  const [savedPosts, setSavedPosts] = useState({});
  const [selectedPost, setSelectedPost] = useState(null);
  const [activeMenu, setActiveMenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [CommentPostId, setCommentPostId] = useState(null);
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [sharePostId, setSharePostId] = useState(null);
  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportType, setReportType] = useState('');
  const [reportTargetId, setReportTargetId] = useState(null);  const [showCopyNotification, setShowCopyNotification] = useState(false);
  const [showManageDropdown, setShowManageDropdown] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [deleteCountdown, setDeleteCountdown] = useState(5);
  const [isDeleting, setIsDeleting] = useState(false);
  const menuRef = useRef(null);
  const manageDropdownRef = useRef(null);
  // Interaction management refs
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map());
  const visualState = useRef({
    likedPosts: {},
    savedPosts: {}
  });
  const DefaultIcon = "/logos/DefaultPicture.png";
  const DefaultBanner = "/logos/DefualtCover.png";
  const DefaultPicture = "/logos/DefaultPicture.png";

  // Add cleanup effect for pending operations
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

  // Like handler with debouncing
  const handleLikeToggle = (postId, e) => {
    if (e) e.stopPropagation();
    
    const postIdStr = postId.toString();
    const originalLiked = likedPosts[postId] || false;
    const post = posts.find(p => p.id === postId);
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
    setLikedPosts(prev => ({
      ...prev,
      [postId]: newLiked
    }));
    
    // Update the post like count in the posts array
    setPosts(prevPosts => 
      prevPosts.map(post => 
        post.id === postId 
          ? { 
              ...post, 
              likes: Math.max(0, originalCount + visualDelta)
            }
          : post
      )
    );
    
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
          setPosts(prevPosts => 
            prevPosts.map(post => 
              post.id === postId 
                ? { 
                    ...post, 
                    likes: originalCount
                  }
                : post
            )
          );
          
          visualState.current.likedPosts[postIdStr] = originalLiked;
          toast.error("Failed to update like status");
        });
      }
      pendingLikeOperations.current.delete(postIdStr);
    }, 500);
    
    pendingLikeOperations.current.set(postIdStr, timerId);
  };

  // Save handler with debouncing
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

  // Add these new handlers
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

  // Add image click handler for image viewing
  const handleImageClick = (e, media, post, index) => {
    e.stopPropagation();
    // For now, just prevent default behavior
    // You can add image viewer functionality later
    console.log('Image clicked:', media, index);
  };

  const handlePostClick = (post) => {
    setSelectedPost(post);
  };
  // Fetch community data
  useEffect(() => {
    fetchCommunityData();
  }, [id]);
  // Close menus when clicking outside
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

      // Close manage dropdown when clicking outside
      if (showManageDropdown && manageDropdownRef.current && 
          !manageDropdownRef.current.contains(event.target)) {
        setShowManageDropdown(false);
      }
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [activeMenu, showManageDropdown]);

  // Add scroll detection to close menus
  useEffect(() => {
    const handleScroll = () => {
      if (activeMenu !== null) {
        setActiveMenu(null);
      }
    };

    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, [activeMenu]);
  const fetchCommunityData = async () => {
    try {
      setLoading(true);
      setError('');

      const response = await axios.get(`${api}/communities/${id}`, {
        withCredentials: true
      });

      if (response.data) {
        setCommunity(response.data);
        
        // Determine user role based on membership
        const userId = userData?.id;
        if (userId) {
          if (response.data.creator?.id === userId) {
            setUserRole('creator');
            setIsJoined(true);
          } else if (response.data.members?.some(member => member.user_id === userId)) {
            // Find the user's membership to get their role
            const userMembership = response.data.members.find(member => member.user_id === userId);
            if (userMembership) {
              setUserRole(userMembership.role); // 'admin', 'moderator', or 'member'
              setIsJoined(true);
            } else {
              setUserRole('member');
              setIsJoined(true);
            }
          } else {
            setUserRole(null);
            setIsJoined(false);
          }
        }

        // Fetch community posts
        fetchCommunityPosts();
      } else {
        setError('Community not found');
      }
    } catch (error) {
      console.error('Error fetching community:', error);
      setError(error.response?.data?.error || 'Failed to load community');
    } finally {
      setLoading(false);
    }
  };
  const fetchCommunityPosts = async () => {
    try {
      setPostsLoading(true);
      const response = await axios.get(`${api}/communities/${id}/posts`, {
        withCredentials: true
      });

      if (response.data && response.data.posts && response.data.posts.length > 0) {
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
        setPosts(response.data.posts);
      } else {
        setPosts([]);
      }
    } catch (error) {
      console.error('Error fetching community posts:', error);
      setPosts([]);
    } finally {
      setPostsLoading(false);
    }
  };

  // Get visibility info
  const getVisibilityInfo = (visibility) => {
    switch (visibility) {
      case 'public':
        return { icon: Globe, color: 'text-green-500', bg: 'bg-green-500/10', label: 'Public' };
      case 'private':
        return { icon: Lock, color: 'text-red-500', bg: 'bg-red-500/10', label: 'Private' };
      case 'restricted':
        return { icon: Shield, color: 'text-yellow-500', bg: 'bg-yellow-500/10', label: 'Restricted' };
      default:
        return { icon: Globe, color: 'text-gray-500', bg: 'bg-gray-500/10', label: 'Public' };
    }
  };  // Get post access text
  const getPostAccessText = () => {
    if (!community) return '';
    
    // Check the post_access_type field to determine who can post
    switch (community.post_access_type) {
      case 'everyone':
        return 'Everyone can post';
      case 'moderators':
        return 'Moderators can post';
      case 'selected_users':
        return 'Selected users can post';
      case 'creator':
        return 'Creator only';
      default:
        return 'Everyone can post';
    }
  };

  const handleBack = () => {
    navigate(-1);
  };
  const handleJoinCommunity = async () => {
    if (!userData) {
      toast.error('Please log in to join communities');
      return;
    }

    try {
      setIsJoining(true);
      
      if (isJoined) {
        // Leave community
        await axios.delete(`${api}/communities/${id}/leave`, { 
          withCredentials: true 
        });
        setIsJoined(false);
        setUserRole(null);
        setCommunity(prev => ({
          ...prev,
          member_count: prev.member_count - 1
        }));
        toast.success('Left community successfully');
      } else {
        // Join community
        await axios.post(`${api}/communities/${id}/join`, {}, { 
          withCredentials: true 
        });
        setIsJoined(true);
        setUserRole('member');
        setCommunity(prev => ({
          ...prev,
          member_count: prev.member_count + 1
        }));
        toast.success('Joined community successfully');
      }
    } catch (error) {
      console.error('Error joining/leaving community:', error);
      toast.error(error.response?.data?.error || 'Failed to update membership');
    } finally {
      setIsJoining(false);
    }
  };
  const handleCreatePost = () => {
    // Navigate to create post page with community ID as route parameter
    navigate(`/create-post/${id}`);
  };  const handleShare = () => {
    if (navigator.share) {
      navigator.share({
        title: community.name,
        text: community.description,
        url: window.location.href,
      });
    } else {
      navigator.clipboard.writeText(window.location.href);
      toast.success('Link copied to clipboard');
    }  };

  // Handle manage dropdown toggle
  const handleManageClick = (e) => {
    e.stopPropagation();
    setShowManageDropdown(!showManageDropdown);
  };

  // Handle delete community
  const handleDeleteCommunity = () => {
    setShowManageDropdown(false);
    setShowDeleteConfirmation(true);
    setDeleteCountdown(5);
    
    // Start countdown
    const countdownInterval = setInterval(() => {
      setDeleteCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(countdownInterval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  // Confirm delete
  const confirmDeleteCommunity = async () => {
    try {
      setIsDeleting(true);
      
      const response = await axios.delete(`${api}/communities/${id}`, {
        withCredentials: true
      });

      if (response.data.success) {
        toast.success('Community deleted successfully');
        navigate('/communities'); // Navigate to communities list
      }
    } catch (error) {
      console.error('Error deleting community:', error);
      toast.error(error.response?.data?.error || 'Failed to delete community');
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirmation(false);
    }
  };

  // Cancel delete
  const cancelDelete = () => {
    setShowDeleteConfirmation(false);
    setDeleteCountdown(5);
  };  const getUserBadge = () => {
    if (userRole === 'creator' || userRole === 'admin') {
      return (
        <div className="flex flex-row gap-2">
          <div className="inline-flex items-center space-x-1 px-3 py-1 bg-yellow-500/20 rounded-full border border-yellow-500/30">
            <Crown className="w-3 h-3 text-yellow-400" />
            <span className="text-xs font-medium text-yellow-400">Creator</span>
          </div>
          <div className="inline-flex items-center md:hidden space-x-1 px-3 py-1 bg-blue-500/20 rounded-full border border-blue-500/30">
            <span className="text-xs font-medium text-blue-400">{getPostAccessText()}</span>
          </div>
        </div>
      );
    } else if (userRole === 'moderator') {
      return (
        <div className="flex flex-row gap-2">
          <div className="inline-flex items-center space-x-1 px-3 py-1 bg-purple-500/20 rounded-full border border-purple-500/30">
            <Edit className="w-3 h-3 text-purple-400" />
            <span className="text-xs font-medium text-purple-400">Moderator</span>
          </div>
          {/* Show post access beside the tag, matching creator UI */}
          <div className="inline-flex items-center md:hidden space-x-1 px-3 py-1 bg-blue-500/20 rounded-full border border-blue-500/30">
            <span className="text-xs font-medium text-blue-400">{getPostAccessText()}</span>
          </div>
        </div>
      );
    } else if (userRole === 'member') {
      return (
        <div className="flex flex-row gap-2">
          <div className="inline-flex items-center space-x-1 px-3 py-1 bg-blue-500/20 rounded-full border border-blue-500/30">
            <Users className="w-3 h-3 text-blue-400" />
            <span className="text-xs font-medium text-blue-400">Member</span>
          </div>
          {/* Show post access beside the tag, matching creator UI */}
          <div className="inline-flex items-center md:hidden space-x-1 px-3 py-1 bg-blue-500/20 rounded-full border border-blue-500/30">
            <span className="text-xs font-medium text-blue-400">{getPostAccessText()}</span>
          </div>
        </div>
      );
    }
    return null;
  };
  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white">
        <div className="w-full max-w-[700px] mx-auto">
          <div className="animate-pulse">
            {/* Banner skeleton */}
            <div className="h-48 bg-gray-800 rounded-b-lg mb-4"></div>
            {/* Profile info skeleton */}
            <div className="px-4 space-y-3">
              <div className="h-6 bg-gray-800 rounded w-3/4"></div>
              <div className="h-4 bg-gray-800 rounded w-full"></div>
              <div className="h-4 bg-gray-800 rounded w-2/3"></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-bold text-red-400 mb-2">Error</h2>
          <p className="text-gray-400 mb-4">{error}</p>
          <button
            onClick={handleBack}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }  const visibilityInfo = getVisibilityInfo(community.visibility);
  const VisibilityIcon = visibilityInfo.icon;
  const isCreator = userRole === 'creator' || userRole === 'admin';

  // Debug logging
  console.log('=== CREATE POST DEBUG ===');
  console.log('userRole:', userRole);
  console.log('userData.id:', userData?.id);
  console.log('community.creator.id:', community.creator?.id);
  console.log('community.post_access_type:', community.post_access_type);
  console.log('community.post_access_users:', community.post_access_users);
  console.log('========================');// Determine if user can create posts based on community settings and user role
  const canCreatePost = (() => {
    if (!userData?.id || !community) {
      console.log('No userData.id or community, denying post creation');
      return false;
    }
    
    // Creator and admin can ALWAYS post, regardless of post_access_type
    const isCreatorOrAdmin = community.creator?.id === userData.id || userRole === 'admin';
    if (isCreatorOrAdmin) {
      console.log('User is creator/admin, allowing post creation');
      return true;
    }
    
    console.log('Checking post access for non-creator/admin user...');
    console.log('post_access_type:', community.post_access_type);
      switch (community.post_access_type) {
      case 'everyone':
        console.log('Everyone can post, checking if user is member:', userRole);
        return userRole === 'moderator' || userRole === 'member';
      case 'creator':
        console.log('Creator only can post');
        return false; // Only creator can post, and we already checked that above
      case 'moderators':
      case 'selected_users':
        console.log('Selected users/moderators only can post, checking conditions...');
        console.log('userRole:', userRole);
        console.log('post_access_users:', community.post_access_users);
        console.log('userData.id:', userData.id);
        
        // Check if user is in the post_access_users list (this is the primary check for selected users)
        const isInModeratorList = community.post_access_users?.some(user => {
          console.log('Comparing user.id:', user.id, 'with userData.id:', userData.id);
          return user.id === userData.id;
        });
        
        console.log('Is user in selected users list:', isInModeratorList);
        
        // Also check if user has moderator role (fallback)
        const hasModeratorRole = userRole === 'moderator';
        console.log('Has moderator role:', hasModeratorRole);
        
        const canPost = isInModeratorList || hasModeratorRole;
        console.log('Final selected users post decision:', canPost);
        
        return canPost;
      default:
        console.log('Unknown post_access_type:', community.post_access_type, ', denying post creation');
        return false;
    }
  })();

  return (
    <div className="min-h-screen text-white font-sans mb-10">
      <section id="thecommunityinfo">
        <div className="w-full max-w-[700px] mx-auto">
          {/* Banner Image */}
          <div className="relative h-48 max-md:h-36 w-full">
            <img
              src={
                community.banner_url 
                  ? `${cloud}/cloudofscubiee/communityBanner/${community.banner_url}`
                  : DefaultBanner
              }
              className="object-cover h-48 max-md:h-36 w-full rounded-b-lg"
              loading="lazy"
              alt={`${community.name} banner`}
            />
          </div>

          <div className="flex">
            {/* Left Half */}
            <div className="w-[50%] max-xl:w-[60%] max-md:w-[100%]">
              {/* Community Information */}
              <div className="relative px-4 sm:px-6 lg:px-8">                {/* Community Icon */}
                <div className="absolute rounded-2xl -top-20 max-md:-top-[60px] left-4 sm:left-6 lg:left-8">
                  <div className="w-40 h-40 max-md:h-32 max-md:w-32 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center border-4 border-[#0a0a0a]">
                    {community.profile_icon ? (
                      <img
                        src={`${cloud}/cloudofscubiee/communityProfile/${community.profile_icon}`}
                        alt={community.name}
                        className="w-full h-full rounded-2xl object-cover"
                        loading="lazy"
                      />
                    ) : (
                      <Users className="w-20 h-20 max-md:w-16 max-md:h-16 text-white" />
                    )}
                  </div>                  {/* Mobile community name */}
                  <div className="mt-[-60px] ml-36 w-full md:hidden">
                    <h1 className="text-3xl max-md:text-xl font-bold flex items-center gap-2">
                      {community.name}
                    </h1>
                    <div className="flex items-center space-x-2 mt-1">
                      <span className="text-gray-300 text-sm">
                        {community.member_count.toLocaleString()} members
                      </span>
                      <span className="text-gray-500">•</span>
                      <div className="flex items-center space-x-1">
                        <VisibilityIcon className={`w-4 h-4 ${visibilityInfo.color}`} />
                        <span className={`text-sm ${visibilityInfo.color}`}>
                          {visibilityInfo.label}
                        </span>
                      </div>
                      <span className="text-gray-500 max-md:hidden">•</span>
                      <span className="text-blue-400 text-sm font-medium max-md:hidden">
                        {getPostAccessText()}
                      </span>
                    </div>
                  </div>
                </div>                {/* Community Info and Actions */}
                <div className="pt-[74px]  max-md:mt-0 pb-6">
                  <div className="flex justify-between items-center">
                    {/* Desktop community name - positioned like mobile */}
                    <div className="max-md:hidden">
                      <div className="mt-[-60px] ml-[184px] w-full">
                        <h1 className="text-3xl max-md:text-xl font-bold flex items-center gap-2">
                          {community.name}
                        </h1>
                        <div className="flex items-center space-x-2 mt-1">
                          <span className="text-gray-300 text-sm">
                            {community.member_count.toLocaleString()} members
                          </span>
                          <span className="text-gray-500">•</span>
                          <div className="flex items-center space-x-1">
                            <VisibilityIcon className={`w-4 h-4 ${visibilityInfo.color}`} />
                            <span className={`text-sm ${visibilityInfo.color}`}>
                              {visibilityInfo.label}
                            </span>
                          </div>
                          <span className="text-gray-500">•</span>
                          <span className="text-blue-400 text-sm font-medium">
                            {getPostAccessText()}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>{/* User Badge */}
                  {getUserBadge() && (
                    <div className=" mb-3 md:mt-3 inline-block">
                      {getUserBadge()}
                    </div>
                  )}
                  
                  {/* Description */}
                  {community.description && (
                    <p className=" w-[200%] md:text-[16px] text-[15px] font-medium max-md:mr-4 max-md:w-[140%] max-500:w-[110%] max-md:pr-8 text-gray-300 font-sans">
                      {community.description}
                    </p>
                  )}                  {/* Hot Topics */}
                  {community.hot_topics && community.hot_topics.length > 0 && (
                    <div className="mt-4 max-md:mt-2 w-[200%] max-md:w-[160%] max-md:pr-8">
                      {/* Desktop: flex-wrap layout */}
                      <div className="hidden md:flex flex-wrap gap-2">
                        {community.hot_topics.slice(0, 5).map((topic, index) => (
                          <span
                            key={index}
                            className="flex items-center space-x-1 px-2 py-1 bg-blue-500/10 text-blue-400 text-xs rounded-lg"
                          >
                            <Hash className="w-3 h-3" />
                            <span>{topic}</span>
                          </span>
                        ))}
                        {community.hot_topics.length > 5 && (
                          <span className="px-2 py-1 bg-gray-800 text-gray-400 text-xs rounded-lg">
                            +{community.hot_topics.length - 5} more
                          </span>
                        )}
                      </div>                      {/* Mobile: show 3 tags */}
                      <div className="md:hidden flex flex-wrap gap-2">
                        {community.hot_topics.slice(0, 3).map((topic, index) => (
                          <span
                            key={index}
                            className="flex items-center space-x-1 px-2 py-1 bg-blue-500/10 text-blue-400 text-xs rounded-lg"
                          >
                            <Hash className="w-3 h-3" />
                            <span>{topic}</span>
                          </span>
                        ))}
                        {community.hot_topics.length > 3 && (
                          <span className="px-2 py-1 bg-gray-800 text-gray-400 text-xs rounded-lg">
                            +{community.hot_topics.length - 3} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}{/* Created date and creator */}
                  <div className="flex items-center space-x-4 mt-6 max-md:mt-3 w-[200%] max-md:w-[160%] max-md:pr-8">
                    <div className="flex items-center space-x-1 text-gray-400">
                      <Calendar className="w-4 h-4" />                      <span className="text-sm">
                        Created {community.createdAt ? new Date(community.createdAt).toLocaleDateString('en-US', {
                          year: 'numeric',
                          month: 'long',
                          day: 'numeric'
                        }) : 'Unknown'}
                      </span>
                    </div>
                  </div>

                  {/* Creator Info */}
                  {community.creator && (
                    <div className="flex items-center space-x-2 mt-3 pt-3 border-t border-gray-800 w-[200%] max-md:w-[160%] max-md:pr-8">
                      <div className="w-6 h-6 bg-gradient-to-br from-gray-600 to-gray-700 rounded-full flex items-center justify-center">
                        {community.creator.profilePicture ? (
                          <img
                            src={`${cloud}/cloudofscubiee/profilePic/${community.creator.profilePicture}`}
                            alt={community.creator.username}
                            className="w-full h-full rounded-full object-cover"
                          />
                        ) : (
                          <span className="text-xs font-medium text-white">
                            {community.creator.username.charAt(0).toUpperCase()}
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-gray-400">
                        Created by @{community.creator.username}
                      </span>
                    </div>
                  )}                  {/* Action Buttons */}
                  <div className="flex flex-wrap gap-3 mt-6 max-md:mt-4 w-[200%] max-md:w-[190%] max-md:pr-8">                    {!isCreator && (
                      <motion.button
                        whileTap={{ scale: 0.95 }}
                        onClick={handleJoinCommunity}
                        disabled={isJoining}
                        className={`px-6 max-md:px-4 max-md:py-1.5 max-md:text-sm py-2.5 rounded-full font-semibold flex items-center justify-center space-x-2 transition-all duration-200 ${
                          isJoined
                            ? 'bg-gray-800 hover:bg-gray-700 text-gray-300 border border-gray-700'
                            : 'bg-blue-500 hover:bg-blue-600 text-white shadow-lg hover:shadow-blue-500/25'
                        }`}
                      >
                        {isJoining ? (
                          <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        ) : isJoined ? (
                          <>
                            <UserMinus className="w-4 h-4" />
                            <span>Leave</span>
                          </>
                        ) : (
                          <>
                            <UserPlus className="w-4 h-4" />
                            <span>Join</span>
                          </>
                        )}
                      </motion.button>
                    )}
                      {isCreator && (
                      <div className="relative" ref={manageDropdownRef}>
                        <motion.button
                          whileTap={{ scale: 0.95 }}
                          onClick={handleManageClick}
                          className="px-6 max-md:px-4 max-md:py-1.5 max-md:text-sm py-2.5 bg-gray-800 hover:bg-gray-700 text-white rounded-full font-semibold flex items-center justify-center space-x-2 transition-all duration-200 border border-gray-700 hover:border-gray-600"
                        >
                          <Settings className="w-4 h-4" />
                          <span>Manage</span>
                          <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${showManageDropdown ? 'rotate-180' : ''}`} />
                        </motion.button>

                        {/* Dropdown Menu */}
                        {showManageDropdown && (
                          <motion.div
                            initial={{ opacity: 0, y: -10, scale: 0.95 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, y: -10, scale: 0.95 }}
                            transition={{ duration: 0.15 }}
                            className="absolute top-full mt-2 left-0 w-[220px] bg-[#1a1a1a] border border-gray-700 rounded-xl shadow-2xl z-50 overflow-hidden"
                          >
                            <div className="py-2">
                              <button
                                onClick={() => {
                                  setShowManageDropdown(false);
                                  navigate(`/edit-community/${id}`);
                                }}
                                className="w-full px-4 py-3 text-left text-gray-200 hover:bg-gray-800 transition-colors duration-150 flex items-center space-x-3"
                              >
                                <Edit className="w-4 h-4 text-blue-400" />
                                <span className="font-medium">Edit Community</span>
                              </button>
                              
                              <div className="h-px bg-gray-700 mx-2"></div>
                              
                              <button
                                onClick={handleDeleteCommunity}
                                className="w-full px-4 py-3 text-left text-red-400 hover:bg-red-500/10 transition-colors duration-150 flex items-center space-x-3"
                              >
                                <Trash2 className="w-4 h-4" />
                                <span className="font-medium">Delete Community</span>
                              </button>
                            </div>
                          </motion.div>
                        )}
                      </div>
                    )}                       <motion.button
                      whileTap={{ scale: 0.95 }}
                      onClick={handleShare}
                      className="px-6 max-md:px-4 max-md:py-1.5 max-md:text-sm py-2.5 bg-gray-800 hover:bg-gray-700 text-white rounded-full font-semibold flex items-center justify-center space-x-2 transition-all duration-200 border border-gray-700 hover:border-gray-600"
                    >
                      <Share2 className="w-4 h-4" />
                      {/* Show text only on desktop, hide on mobile for both creators and members */}
                      <span className="max-md:hidden">Share</span>
                    </motion.button>
                    
                     {canCreatePost && (
                      <motion.button
                        whileTap={{ scale: 0.95 }}
                        onClick={handleCreatePost}
                        className="px-6 max-md:px-4 max-md:py-1.5 max-md:text-sm py-2.5 bg-white hover:bg-gray-100 text-black rounded-full font-semibold flex items-center justify-center space-x-2 transition-all duration-200 shadow-lg hover:shadow-xl"
                      >
                        <Plus className="w-4 h-4" />
                        <span>Create Post</span>
                      </motion.button>
                    )}
                  </div>
                </div>
              </div>
            </div>            {/* Right Half - Stats */}
         
          </div>
        </div>
      </section>      {/* Posts Section */}
      <div className=" w-full flex flex-col items-center">
        <div className="w-full max-w-[640px] space-y-2 max-md:px-2 md:space-y-3 my-4 mb-16">
          {postsLoading ? (
            <div className="text-center py-10">
              <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent">
                <span className="sr-only">Loading...</span>
              </div>
            </div>
          ) : posts.length > 0 ? (
            posts.map((post) => (
              <article
                key={post.id}
                className="overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818] bg-[#0a0a0a] md:bg-[#0c0c0c] backdrop-blur-sm py-2 max-md:py-2 max-md:px-[0px] text-gray-300"
              >
                {/* Post Header */}
                <div className="flex items-center justify-between mb-3 px-3 max-md:px-2">
                  <div className="flex items-center gap-3 max-md:ml-[6px] pt-1 md:pt-2">
                    <div className="relative h-10 w-10 max-md:h-[36px] max-md:w-[36px] rounded-full overflow-hidden group cursor-pointer">
                      {post.author?.profilePicture ? (
                        <img
                          src={`${cloud}/cloudofscubiee/profilePic/${post.author.profilePicture}`}
                          alt={post.author.username}
                          className="w-full h-full bg-gray-300 object-cover transition-transform duration-200 group-hover:scale-110"
                        />
                      ) : (
                        <div className="w-full h-full bg-gradient-to-br from-gray-600 to-gray-700 flex items-center justify-center">
                          <span className="text-sm font-medium text-white">
                            {post.author?.username?.charAt(0).toUpperCase()}
                          </span>
                        </div>
                      )}
                      <div className="absolute inset-0 bg-black/10 group-hover:bg-black/0 transition-colors duration-200"></div>
                    </div>
                    <div>
                      <div className="flex items-center gap-1">
                        <h3 className="mt-[-4px] text-[15px] max-md:text-[14px] font-semibold font-sans">
                          {post.author?.username}
                        </h3>
                        {post.author?.verified && (
                          <RiVerifiedBadgeFill className="text-blue-500 h-[14px] w-[14px]" />
                        )}
                        {/* Show badge if user is creator/contributor */}
                        {post.author?.id === community.creator?.id && (
                          <div className="inline-flex items-center space-x-1 px-1.5 py-0.5 bg-yellow-500/20 rounded-full border border-yellow-500/30 ml-1">
                            <Crown className="w-2 h-2 text-yellow-400" />
                            <span className="text-[10px] text-yellow-400 font-medium">Creator</span>
                          </div>
                        )}
                        {community.post_access_users?.some(user => user.id === post.author?.id) && 
                         post.author?.id !== community.creator?.id && (
                          <div className="inline-flex items-center space-x-1 px-1.5 py-0.5 bg-purple-500/20 rounded-full border border-purple-500/30 ml-1">
                            <Edit className="w-2 h-2 text-purple-400" />
                            <span className="text-[10px] text-purple-400 font-medium">Contributor</span>
                          </div>
                        )}
                      </div>
                      <h3 className="text-xs max-md:text-[11px] text-gray-400">
                        {new Date(post.date_created || post.createdAt).toLocaleDateString('en-US', {
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
                              onClick={(e) => handleReportUser(post.author?.id, e)}
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
                  onClick={() => handlePostClick && handlePostClick(post)}
                >                  {/* Text Content */}
                  {(post.title || post.content || post.description) && (
                    <div className="mb-[10px] max-md:ml-2 md:pl-[40px] max-md:px-2 mx-1 xl:mx-2">
                      <SmartTruncateText
                        text={post.title || post.content || post.description}
                        className="text-[15.4px] lg:text-[16.2px] font-sans text-gray-200 max-md:font-medium"
                      />
                    </div>
                  )}

                  {/* Media Content - Updated to match Profile.jsx */}
                  {post.media && post.media.length > 0 && (
                    <div className="relative mb-4 xl:w-[84%] md:w-[90%] mx-auto w-full">                      {/* Single media item - full width for both mobile and desktop */}
                      {post.media.length === 1 ? (
                        <div className="relative mb-4">
                          <div className="max-md:w-[93%] max-md:mx-auto w-[98%] mx-auto" style={{ maxHeight: '550px' }}>
                            {post.media[0].type === 'video' ? (
                              <div 
                                className="max-md:rounded-lg max-md:w-[96%] md:w-full mx-auto rounded-lg h-full video-container bg-black cursor-pointer overflow-hidden relative"
                                data-video-id={`${post.id}-${post.media[0].url}`}
                              >
                                <video 
                                  src={`${cloud}/cloudofscubiee/postVideos/${post.media[0].url}`}
                                  className="w-full h-full object-contain max-h-[550px]" 
                                  muted
                                  loop
                                  playsInline
                                  preload="metadata"
                                  controls
                                />
                              </div>                            ) : (
                              <img 
                                src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                                alt="Post image" 
                                loading="lazy"
                                className="max-md:w-[100%] max-md:mx-auto max-md:rounded-lg w-full h-auto object-cover md:rounded-lg cursor-pointer max-h-[550px]"
                                onClick={(e) => handleImageClick && handleImageClick(e, post.media[0], post, 0)}
                              />
                            )}
                          </div>
                        </div>
                      ) : (
                        /* Multiple media - show first image */
                        <div className="relative mb-4">
                          <div className="max-md:w-[94%] max-md:mx-auto w-[98%] mx-auto" style={{ maxHeight: '550px' }}>
                            <img 
                              src={`${cloud}/cloudofscubiee/postImages/${post.media[0].url}`}
                              alt="Post image" 
                              loading="lazy"
                              className="max-md:w-[94%] max-md:mx-auto max-md:rounded-lg w-full h-auto object-cover md:rounded-lg cursor-pointer max-h-[550px]"
                              onClick={(e) => handleImageClick && handleImageClick(e, post.media[0], post, 0)}
                            />
                            {post.media.length > 1 && (
                              <div className="absolute bottom-4 right-4 bg-black/60 px-2 py-1 rounded-full text-xs text-white">
                                <span>{`1/${post.media.length}`}</span>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Post Actions - Match Profile.jsx exactly */}
                <div className="flex items-center md:w-[84%] xl:w-[78%] md:pl-[1px] md:mx-auto max-md:mr-[8px] max-md:ml-2 max-md:px-2 mb-3 max-md:mb-1 mt-1">
                  {/* Upvote Button - Reddit/Daily.dev style */}
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
                      style={{
                        display: (() => {
                          const postIdStr = post.id?.toString();
                          
                          if (postIdStr && postIdStr in visualState.current.likedPosts) {
                            return visualState.current.likedPosts[postIdStr] ? 'none' : 'block';
                          }
                          
                          return likedPosts[post.id] ? 'none' : 'block';
                        })()
                      }} 
                    />
                    <BiSolidUpvote 
                      className="h-4 w-4 text-gray-300 filled-heart" 
                      style={{
                        display: (() => {
                          const postIdStr = post.id?.toString();
                          
                          if (postIdStr && postIdStr in visualState.current.likedPosts) {
                            return visualState.current.likedPosts[postIdStr] ? 'block' : 'none';
                          }
                          
                          return likedPosts[post.id] ? 'block' : 'none';
                        })()
                      }} 
                    />
                    <span className='text-sm font-medium'>
                      {(() => {
                        const postIdStr = post.id?.toString();
                        const originalCount = post?.likes || 0;
                          
                        if (postIdStr && postIdStr in visualState.current.likedPosts) {
                          const originalLiked = likedPosts[post.id] || false;
                          
                          const visualDelta = visualState.current.likedPosts[postIdStr] !== originalLiked
                            ? (visualState.current.likedPosts[postIdStr] ? 1 : -1)
                            : 0;
                          
                          return Math.max(0, originalCount + visualDelta).toString();
                        }
                        
                        return (originalCount || 0).toString();
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
                    className="flex items-center text-gray-300 ml-6 group transform transition-transform duration-200"
                    onClick={(e) => handleSaveToggle(post.id, e)}
                  >
                    <div className="p-1.5 rounded-full group-hover:bg-gray-100/10 transition-colors duration-200">
                      {(() => {
                        const postIdStr = post.id?.toString();
                        
                        if (postIdStr && postIdStr in visualState.current.savedPosts) {
                          return visualState.current.savedPosts[postIdStr] ? (
                            <BsBookmarkFill className="h-[18px] w-[18px] text-white group-hover:text-gray-200 transition-colors duration-200" />
                          ) : (
                            <BsBookmark className="h-[18px] w-[18px] transition-colors duration-200" />
                          );
                        }
                        
                        return savedPosts[post.id] ? (
                          <BsBookmarkFill className="h-[18px] w-[18px] text-white group-hover:text-gray-200 transition-colors duration-200" />
                        ) : (
                          <BsBookmark className="h-[18px] w-[18px] transition-colors duration-200" />
                        );
                      })()}
                    </div>
                  </button>
                </div>
              </article>
            ))
          ) : (
            <div className="text-center py-20">
              <div className="w-16 h-16 bg-gray-800 rounded-full flex items-center justify-center mx-auto mb-4">
                <Users className="w-8 h-8 text-gray-400" />
              </div>
              <h4 className="text-lg font-semibold text-white mb-2">No Posts Yet</h4>
              <p className="text-gray-400 text-sm mb-6">
                {canCreatePost 
                  ? "Be the first to share something in this community!" 
                  : "No posts have been shared in this community yet."
                }
              </p>
              {canCreatePost && (
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={handleCreatePost}
                  className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold flex items-center justify-center space-x-2 mx-auto"
                >
                  <Plus className="w-5 h-5" />
                  <span>Create First Post</span>
                </motion.button>
              )}
            </div>
          )}
        </div>
      </div>      {/* Post Detail Widget */}
      {selectedPost && (
        <PostWidget
          post={selectedPost}
          onClose={() => setSelectedPost(null)}
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

      {/* Report Widget */}
      {showReportWidget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div 
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
      )}      {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirmation && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className="bg-[#1a1a1a] border border-red-500/30 rounded-2xl p-8 max-w-md mx-4 text-center shadow-2xl"
          >
            <div className="w-16 h-16 bg-red-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
              <Trash2 className="w-8 h-8 text-red-500" />
            </div>
            
            <h3 className="text-2xl font-bold text-white mb-3">Delete Community</h3>
            <p className="text-gray-300 mb-2">
              Are you sure you want to delete <span className="font-semibold text-white">"{community?.name}"</span>?
            </p>
            <p className="text-red-400 text-sm mb-6 font-medium">
              This action cannot be undone. All posts, members, and data will be permanently deleted.
            </p>
            
            <div className="flex gap-3">
              <button
                onClick={cancelDelete}
                disabled={isDeleting}
                className="flex-1 px-4 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-xl font-semibold transition-colors duration-200 disabled:opacity-50"
              >
                Cancel
              </button>
              
              <button
                onClick={confirmDeleteCommunity}
                disabled={deleteCountdown > 0 || isDeleting}
                className={`flex-1 px-4 py-3 rounded-xl font-semibold transition-all duration-200 ${
                  deleteCountdown > 0 
                    ? 'bg-red-500/20 text-red-300 cursor-not-allowed' 
                    : 'bg-red-600 hover:bg-red-700 text-white'
                } ${isDeleting ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                {isDeleting ? (
                  <div className="flex items-center justify-center">
                    <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin mr-2" />
                    Deleting...
                  </div>
                ) : deleteCountdown > 0 ? (
                  `Delete (${deleteCountdown})`
                ) : (
                  'Delete Forever'
                )}
              </button>
            </div>
          </motion.div>
        </div>
      )}

      {/* Click outside to close menu */}
      {(showMenu || activeMenu) && (
        <div
          className="fixed inset-0 z-10"
          onClick={() => {
            setShowMenu(false);
            setActiveMenu(null);
          }}
        />
      )}
    </div>
  );
};

export default CommunityDetail;
