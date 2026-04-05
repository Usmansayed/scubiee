import React, { useState, useRef, useEffect } from 'react';
import { X, Heart, MessageCircle, ChevronDown } from 'lucide-react';
import { BiLike, BiDotsVerticalRounded, BiSolidLike } from 'react-icons/bi';
import Picker from 'emoji-picker-react';
import { FaRegFaceSmile } from "react-icons/fa6";
import { BsSend } from "react-icons/bs";
import { IoCloseSharp } from "react-icons/io5";
import axios from 'axios';
import moment from 'moment';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { useCallback } from 'react';
import ReportWidget from './ReportWidget';
import { IoMdHeartEmpty, IoMdHeart} from 'react-icons/io';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import { useInteractionManager } from '../hooks';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;


// Instagram-style like handler - implements a debounce system per comment
const useLikeSystem = () => {
  // Track pending operations and timers
  const operationTimers = useRef(new Map());
  const pendingStates = useRef(new Map());
  const DEBOUNCE_TIME = 500;
  const navigate = useNavigate();

  // Send a like/unlike request to the API
  const sendLikeRequest = async (commentId, shouldLike) => {
    const action = shouldLike ? 'like' : 'remove-like';
    const commentIdStr = commentId.toString();
    
    try {
      await axios.post(`${api}/user-interactions/comment/${commentId}/action`, 
        { action },
        { 
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") }
        }
      );
      console.log(`Successfully ${action} comment ${commentIdStr}`);
      return true;
    } catch (error) {
      console.error(`Error ${action} comment ${commentIdStr}:`, error);
      return false;
    } finally {
      // Clear the operation from pending map
      pendingStates.current.delete(commentIdStr);
    }
  };

  // Clean up any pending timers
  const cleanupTimers = () => {
    operationTimers.current.forEach((timer) => clearTimeout(timer));
    operationTimers.current.clear();
    pendingStates.current.clear();
  };

  // The actual like handler function that will be used in the component
  const handleLike = (commentId, currentLikedState, updateUICallback) => {
    const commentIdStr = commentId.toString();
    const newLikedState = !currentLikedState;
    
    // Immediately update UI (optimistic update)
    updateUICallback(commentId, newLikedState);
    
    // If there's already a timer for this comment, clear it
    if (operationTimers.current.has(commentIdStr)) {
      clearTimeout(operationTimers.current.get(commentIdStr));
    }
    
    // Store the latest desired state
    pendingStates.current.set(commentIdStr, newLikedState);
    
    // Set a new timer
    const timerId = setTimeout(async () => {
      // Get the final state after all rapid clicks
      const finalState = pendingStates.current.get(commentIdStr);
      
      // Make the API call with the final state
      const success = await sendLikeRequest(commentId, finalState);
      
      // If the API call failed, revert the UI
      if (!success) {
        updateUICallback(commentId, currentLikedState);
      }
      
      // Clear the timer reference
      operationTimers.current.delete(commentIdStr);
    }, DEBOUNCE_TIME);
    
    // Store the timer ID
    operationTimers.current.set(commentIdStr, timerId);
  };

  return { handleLike, cleanupTimers };
};

const CommentWidget = ({ postId, isOpen, onClose, isHomePage, notificationData }) => {
  const navigate = useNavigate();

  const [comments, setComments] = useState([]);
  const [showPicker, setShowPicker] = useState(false);
  const [parentId, setParentId] = useState(null);
  const [replyingTo, setReplyingTo] = useState(null);
  const [comment, setComment] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [startY, setStartY] = useState(0);
  const [currentY, setCurrentY] = useState(0);
  const containerRef = useRef(null);
  const commentsListRef = useRef(null);
  const [isLargeScreen, setIsLargeScreen] = useState(window.innerWidth >= 1024);
  // Replace single expandedCommentId with a Set of expanded comment IDs
  const [expandedCommentIds, setExpandedCommentIds] = useState(new Set());
  const [slideIn, setSlideIn] = useState(false);
  const [replies, setReplies] = useState({});
  const [highlightedReplyId, setHighlightedReplyId] = useState(null);
  const [openMenuId, setOpenMenuId] = useState(null);
  const [likedComments, setLikedComments] = useState([]);
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);
  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportWidgetId, setReportWidgetId] = useState(null);
  const reportWidgetRef = useRef(null);
  const [isNotificationView, setIsNotificationView] = useState(false);
  // Pagination state
  const [page, setPage] = useState(1);
  const [hasMoreComments, setHasMoreComments] = useState(true);
  const [loadingComments, setLoadingComments] = useState(false);
  const [replyPagination, setReplyPagination] = useState({});
  const [loadingMoreReplies, setLoadingMoreReplies] = useState({});
  const [expectedReplies, setExpectedReplies] = useState({});
  const scrollThrottling = useRef(false);
  const [fetchError, setFetchError] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Add a state to track newly added comments count
  const [newCommentCount, setNewCommentCount] = useState(0);

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  const navigateToUserProfile = (username) => {
    if (username) {
      // Get the Domain from environment variables - adding proper prefix and logging
      const Domain = import.meta.env.VITE_DOMAIN || import.meta.env.DOMAIN;
      
      // Debug to console
      console.log('Navigating to profile:', username, 'Domain:', Domain);
      
      // Check if Domain is defined and has http/https
      if (Domain && (Domain.startsWith('http://') || Domain.startsWith('https://'))) {
        console.log(`Redirecting to: ${Domain}/${username}`);
        window.location.href = `${Domain}/${username}`;
      } else {
        console.log(`Using router navigation to: /${username}`);
        navigate(`/${username}`);
      }
    }
  };

  useEffect(() => {
    if (!isOpen) return;
  
    // Push a new state to the history stack when the widget opens
    window.history.pushState({ commentWidgetOpen: true }, "");
  
    // Listen for back/forward navigation
    const handlePopState = (event) => {
      // If the widget is open, close it on back
      if (isOpen) {
        handleClose();
      }
    };
  
    window.addEventListener("popstate", handlePopState);
  
    return () => {
      window.removeEventListener("popstate", handlePopState);
      // Optionally, go back one step if the widget is being closed by other means
      if (window.history.state && window.history.state.commentWidgetOpen) {
        window.history.back();
      }
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    // Handler to close widget on window/document scroll
    const handleWindowScroll = () => {
      handleClose();
    };

    window.addEventListener('scroll', handleWindowScroll, true);
    return () => {
      window.removeEventListener('scroll', handleWindowScroll, true);
    };
  }, [isOpen]);

  const { userData, error } = useSelector((state) => state.user);
  const menuRef = useRef(null);
  const dispatch = useDispatch();

  // Add isLastPage state to track if the current notification comment is on the last page
  const [isLastPage, setIsLastPage] = useState(false);

  // Modified handleClose function to pass the new comment count
  const handleClose = () => {
    // Pass the newCommentCount to the parent component's onClose handler
    onClose(newCommentCount);
    
    // Reset the internal count for next time
    setNewCommentCount(0);
    
    // Reset the comment widget state
    dispatch(setIsCommentOpen(false));
  };

  const handleScroll = useCallback(() => {
    // Skip if we're at the last page with a notification view
    if (!commentsListRef.current || loadingComments || !hasMoreComments || (isNotificationView && isLastPage)) return;
  
    const { scrollTop, scrollHeight, clientHeight } = commentsListRef.current;
    
    // Trigger loading when user is within 150px of the bottom
    const scrollThreshold = 150;
    const isNearBottom = scrollTop + clientHeight >= scrollHeight - scrollThreshold;
    
    if (isNearBottom && !scrollThrottling.current) {
      scrollThrottling.current = true;
      console.log("Near bottom, loading more comments...");
      fetchMoreComments();
      
      // Reset throttle after a short delay
      setTimeout(() => {
        scrollThrottling.current = false;
      }, 300);
    }
  }, [loadingComments, hasMoreComments, isNotificationView, isLastPage]);

  useEffect(() => {
    const currentRef = commentsListRef.current;
    if (currentRef) {
      currentRef.addEventListener('scroll', handleScroll);
      return () => currentRef.removeEventListener('scroll', handleScroll);
    }
  }, [handleScroll]);

  const handleMenuClick = (commentId) => {
    setOpenMenuId(openMenuId === commentId ? null : commentId);
  };

  useEffect(() => {
    if (comments.length > 0) {
      const initialLikedComments = comments
        .filter(comment => comment.userLiked)
        .map(comment => comment.id);
      setLikedComments(initialLikedComments);
    }
  }, [comments]);

  if (!isOpen) return null;

  const handleContainerClick = (e) => {
    e.stopPropagation();
  };

  const { createCommentLikeHandler } = useInteractionManager();
  
  // Use our custom like system hook
  const { handleLike, cleanupTimers } = useLikeSystem();
  
  // Simple helper function to update UI state
  const updateCommentLikeUI = (commentId, newLikedState) => {
    // Update liked comments array for consistent UI rendering
    if (newLikedState) {
      setLikedComments(prev => [...prev.filter(id => id !== commentId), commentId]);
    } else {
      setLikedComments(prev => prev.filter(id => id !== commentId));
    }

    // Update either top-level comment or reply based on where it exists
    const isTopLevelComment = comments.some(c => c.id === commentId);
    
    if (isTopLevelComment) {
      setComments(prev => prev.map(c => {
        if (c.id === commentId) {
          const likeDelta = newLikedState ? (c.userLiked ? 0 : 1) : (c.userLiked ? -1 : 0);
          return { 
            ...c, 
            likes: c.likes + likeDelta,
            userLiked: newLikedState 
          };
        }
        return c;
      }));
    } else {
      // Search through replies to find and update the right one
      for (const [parentId, repliesList] of Object.entries(replies)) {
        const replyIndex = repliesList.findIndex(r => r.id === commentId);
        
        if (replyIndex !== -1) {
          setReplies(prev => {
            const updatedReplies = { ...prev };
            const updatedRepliesList = [...updatedReplies[parentId]];
            
            const reply = updatedRepliesList[replyIndex];
            const likeDelta = newLikedState ? (reply.userLiked ? 0 : 1) : (reply.userLiked ? -1 : 0);
            
            updatedRepliesList[replyIndex] = {
              ...reply,
              likes: reply.likes + likeDelta,
              userLiked: newLikedState
            };
            
            updatedReplies[parentId] = updatedRepliesList;
            return updatedReplies;
          });
          break;
        }
      }
    }
  };

  // Simplified like handler that delegates to our hook
  const handleLikeClick = (commentId, isCurrentlyLiked, e) => {
    // Visual feedback for button animation
    if (e && e.currentTarget) {
      requestAnimationFrame(() => {
        e.currentTarget.classList.add('scale-90');
        setTimeout(() => e.currentTarget.classList.remove('scale-90'), 150);
      });
    }
    
    // Handle the like action with our hook
    handleLike(commentId, isCurrentlyLiked, updateCommentLikeUI);
  };
  
  // Clean up any pending like operations on unmount
  useEffect(() => {
    return () => {
      cleanupTimers();
    };
  }, []);

  const handleDelete = async (commentId, e) => {
    // Stop propagation first to prevent the menu from closing
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    
    // Find if the deleted comment is a top-level comment or a reply
    const isTopLevel = comments.some(c => c.id === commentId);
    
    // Find the parent ID for a reply
    let parentId = null;
    if (!isTopLevel) {
      for (const [pId, repliesList] of Object.entries(replies)) {
        if (repliesList.some(r => r.id === commentId)) {
          parentId = parseInt(pId);
          break;
        }
      }
    }
    
    // Close the menu immediately to prevent any race conditions
    setOpenMenuId(null);
    
    // Immediately update UI by removing the comment (optimistic update)
    if (isTopLevel) {
      // Remove from comments list
      setComments(prev => prev.filter(c => c.id !== commentId));
      
      // Also remove any replies to this comment from the replies object
      setReplies(prev => {
        const updated = { ...prev };
        delete updated[commentId];
        return updated;
      });
    } else if (parentId) {
      // Remove from replies
      setReplies(prev => {
        const updated = { ...prev };
        updated[parentId] = updated[parentId].filter(r => r.id !== commentId);
        return updated;
      });
      
      // Decrement the reply count on the parent comment
      setComments(prev => prev.map(c => 
        c.id === parentId ? { ...c, replies: Math.max(0, c.replies - 1) } : c
      ));
    }
    
    // If expanded comment was deleted, remove it from the expandedCommentIds
    if (expandedCommentIds.has(commentId.toString())) {
      const newExpandedIds = new Set(expandedCommentIds);
      newExpandedIds.delete(commentId.toString());
      setExpandedCommentIds(newExpandedIds);
    }
    
    // Decrement the new comment count - only for top-level comments
    if (isTopLevel) {
      setNewCommentCount(prev => Math.max(0, prev - 1));
    }
    
    try {
      // Now send the delete request to the server
      const response = await axios.delete(`${api}/user-interactions/comment/${commentId}`, {
        withCredentials: true,
        headers: { accessToken: localStorage.getItem("accessToken") }
      });
      
      console.log('Comment deleted successfully:', response.data);
    } catch (error) {
      console.error('Error deleting comment:', error);
      // Error handling remains the same...
    }
  };

  const handleReport = (commentId, e) => {
    e.preventDefault();
    e.stopPropagation();
    setShowReportWidget(true);
    setReportWidgetId(commentId);
    setOpenMenuId(null);
  };

  useEffect(() => {
    if (isOpen) {
      setSlideIn(true);
      fetchComments(1, true); // Reset and fetch first page
    } else {
      setSlideIn(false);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
  
    setSlideIn(true);
    setLoadingComments(true);
    
    if (notificationData) {
      const refId = notificationData.reference_id;
      const isReply = notificationData.reference_type === 'reply' || notificationData.type === 'reply' || notificationData.type === 'reply_like';
      const isComment = notificationData.reference_type === 'comment' || notificationData.type === 'comment' || notificationData.type === 'comment_like';
      
      console.log("Processing notification:", notificationData, "isReply:", isReply, "isComment:", isComment);
      
      // Clear any previous state
      setComments([]);
      setReplies({});
      setExpandedCommentIds(new Set());
      setHighlightedReplyId(null);
      setFetchError(false);
      setIsLastPage(false); // Reset the last page flag
      
      // Check for both isReply OR isComment
      if (isReply || isComment) {
        console.log(`Fetching comment context for notification type: ${notificationData.type}`);
        
        setIsNotificationView(true);
        
        axios.get(`${api}/user-interactions/c/${postId}`, {
          params: {
            targetCommentId: refId,
            fromNotification: 'true',
            limit: 12
          },
          withCredentials: true,
          headers: {
            accessToken: localStorage.getItem("accessToken")
          }
        })
        .then(({ data }) => {
          console.log("Received notification response:", data);
          setLoadingComments(false);
          
          // Store the isLastPage flag
          if (data.isLastPage !== undefined) {
            setIsLastPage(data.isLastPage);
            console.log(`Comment is on the last page: ${data.isLastPage}`);
          }
          
          // Check if we got full page of comments
          if (data.comments) {
            setComments(data.comments);
            
            // Set hasMoreComments based on both the pagination info AND isLastPage flag
            if (data.pagination) {
              setPage(data.pagination.page || 1);
              const hasMore = data.pagination.hasMore && !data.isLastPage;
              setHasMoreComments(hasMore);
              console.log(`Setting hasMoreComments to ${hasMore} based on pagination and last page status`);
            }
          }
          
          // If we have a target comment ID, ensure it's expanded
          if (data.targetCommentId) {
            setExpandedCommentIds(new Set([data.targetCommentId.toString()]));
          }
          
          // Store replies if they were included
          if (data.replies) {
            setReplies(prev => ({
              ...prev,
              ...data.replies
            }));
          }
          
          // IMPORTANT FIX: Also store reply pagination info from the server
          if (data.replyPagination) {
            setReplyPagination(prev => ({
              ...prev,
              ...data.replyPagination
            }));
            console.log("Stored reply pagination info:", data.replyPagination);
          }
          
          // If we have a highlighted reply ID, set it
          if (data.replyTargetId) {
            setHighlightedReplyId(data.replyTargetId);
          }
          
          // Scroll to the highlighted comment or reply after rendering
          setTimeout(() => {
            if (data.replyTargetId) {
              const replyElement = document.getElementById(`reply-${data.replyTargetId}`);
              if (replyElement) {
                replyElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                replyElement.classList.add('highlight-pulse');
                
                setTimeout(() => {
                  replyElement.classList.remove('highlight-pulse');
                }, 4000);
              }
            } 
            else if (data.targetCommentId) {
              const commentElement = document.querySelector(`[data-comment-id="${data.targetCommentId}"]`);
              if (commentElement) {
                commentElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                commentElement.classList.add('highlight-pulse');
                
                setTimeout(() => {
                  commentElement.classList.remove('highlight-pulse');
                }, 4000);
              }
            }
          }, 600);
        })
        .catch((err) => {
          console.error('Error fetching notification comments:', err);
          setLoadingComments(false);
          setFetchError(true);
        });
      } else {
        // For other notification types (not comment/reply-related)
        setIsNotificationView(false);
        setIsLastPage(false);
        fetchComments(1, true);
      }
    } else {
      // No notification - do regular comment fetching
      setIsNotificationView(false);
      setIsLastPage(false);
      fetchComments(1, true);
    }
  }, [isOpen, notificationData, postId]);


  console.log('Comment:', comments);
  console.log("Extended replies:", expectedReplies);
  console.log("Expanded comments:", expandedCommentIds);

  const fetchComments = async (pageNum = 1, reset = false) => {
    if (loadingComments) return; // Prevent multiple simultaneous requests
    
    try {
      setLoadingComments(true);
      
      // Build params based on whether we're doing the initial load or continuing pagination
      const params = {
        limit: reset ? 20 : 12 // More comments on first load
      };
      
      // Only use page parameter for the first load
      if (reset) {
        params.page = pageNum;
      } 
      // For subsequent loads, use timestamp-based pagination
      else if (comments.length > 0) {
        const oldestComment = comments[comments.length - 1];
        params.beforeTimestamp = oldestComment.createdAt;
        params.fetchDirection = 'older';
        // Log the timestamp we're using for pagination
        console.log(`Using timestamp pagination with ${oldestComment.createdAt}`);
      }
      
      const { data } = await axios.get(`${api}/user-interactions/c/${postId}`, {
        params,
        withCredentials: true,
        headers: {
          accessToken: localStorage.getItem("accessToken")
        }
      });
      
      // Only update comments array if we got valid data
      if (data && data.comments && data.comments.length > 0) {
        // Log received timestamps to help with debugging
        console.log('Received initial comment timestamps:', data.comments.map(c => c.createdAt).join(', '));
        
        // For reset, just use the new comments
        if (reset) {
          setComments(data.comments);
        } else {
          // Add new comments, avoiding duplicates by checking IDs
          setComments(prev => {
            const existingIds = new Set(prev.map(c => c.id));
            const uniqueNewComments = data.comments.filter(c => !existingIds.has(c.id));
            
            if (uniqueNewComments.length === 0) {
              console.log('No new unique comments to add');
              return prev;
            }
            
            return [...prev, ...uniqueNewComments];
          });
        }
        
        setHasMoreComments(data.pagination.hasMore);
      } else {
        console.error('Invalid or empty response from comments API');
        setHasMoreComments(false);
      }
    } catch (error) {
      console.error('Error fetching comments:', error.message);
      setHasMoreComments(false);
    } finally {
      setLoadingComments(false);
    }
  };
  const fetchMoreComments = () => {
    if (loadingComments || !hasMoreComments) {
      return;
    }
    
    // Special handling for notification view
    if (isNotificationView && isLastPage) {
      console.log("Skipping fetch - notification comment is on the last page");
      return;
    }
    
    // Get the oldest comment from current comments list
    let oldestCommentTimestamp = null;
    if (comments.length > 0) {
      // IMPORTANT: Find the actual oldest comment by timestamp, don't rely on array position
      // Sort comments by timestamp to find the oldest one
      const sortedByDate = [...comments].sort((a, b) => 
        new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      );
      const oldestComment = sortedByDate[0];
      oldestCommentTimestamp = oldestComment.createdAt;
      console.log(`Determined oldest comment has timestamp: ${oldestCommentTimestamp}`);
    }
    
    console.log(`Loading more comments using timestamp: ${oldestCommentTimestamp}`);
    
    setLoadingComments(true);
    
    // Always use timestamp-based pagination for consistent behavior
    axios.get(`${api}/user-interactions/c/${postId}`, {
      params: {
        beforeTimestamp: oldestCommentTimestamp, // Key parameter for timestamp-based pagination
        fetchDirection: 'older',
        limit: 12,
        isNotificationView: isNotificationView ? 'true' : 'false',
      },
      withCredentials: true,
      headers: {
        accessToken: localStorage.getItem("accessToken")
      }
    })
    .then(({ data }) => {
      if (data && data.comments) {
        // Check if we actually got any new comments
        if (data.comments.length === 0) {
          setHasMoreComments(false);
          console.log('No more comments to load (empty response)');
          setLoadingComments(false);
          return;
        }
        
        // Log received timestamps for debugging
        console.log('Received comment timestamps:', 
          data.comments.map(c => ({id: c.id, created: c.createdAt})));
        
        // Verify received comments are all older than our current oldest
        if (oldestCommentTimestamp) {
          const oldestTimestampMs = new Date(oldestCommentTimestamp).getTime();
          const allCommentsAreOlder = data.comments.every(comment => {
            const commentTime = new Date(comment.createdAt).getTime();
            const isOlder = commentTime < oldestTimestampMs;
            if (!isOlder) {
              console.warn(`Comment ${comment.id} is NOT older: ${comment.createdAt} compared to ${oldestCommentTimestamp}`);
            }
            return isOlder;
          });
          
          if (!allCommentsAreOlder) {
            console.warn('Some comments are newer than our oldest comment - filtering them out');
            data.comments = data.comments.filter(comment => {
              return new Date(comment.createdAt).getTime() < oldestTimestampMs;
            });
            
            if (data.comments.length === 0) {
              setHasMoreComments(false);
              console.log('No older comments found after filtering');
              setLoadingComments(false);
              return;
            }
          }
        }
        
        // Ensure comments are sorted by createdAt in descending order (newest first)
        data.comments.sort((a, b) => 
          new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
        );
        
        // Update state, avoiding duplicates by ID
        setComments(prev => {
          const existingIds = new Set(prev.map(c => c.id));
          const uniqueNewComments = data.comments.filter(c => !existingIds.has(c.id));
          
          if (uniqueNewComments.length === 0) {
            setHasMoreComments(false);
            console.log('No new unique comments, reached the end');
            return prev;
          }
          
          console.log(`Adding ${uniqueNewComments.length} new comments to the list`);
          
          // Create new array with all comments, then sort by createdAt
          const allComments = [...prev, ...uniqueNewComments];
          allComments.sort((a, b) => 
            new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
          );
          
          return allComments;
        });
        
        // Use server's hasMore flag
        setHasMoreComments(data.pagination.hasMore);
      } else {
        console.error('Invalid response format from comments API');
        setHasMoreComments(false);
      }
    })
    .catch(error => {
      console.error('Error fetching more comments:', error.message);
    })
    .finally(() => {
      setLoadingComments(false);
    });
  };
  
  const fetchReplies = async (commentId, pageNum = 1, append = false, skipIds = [], timestamp = null, fetchDirection = 'older') => {
    // Always convert commentId to string for consistent storage
    const commentIdStr = commentId.toString();
    
    // Don't fetch if already loading for this comment
    if (loadingMoreReplies[commentIdStr]) {
      console.log(`Already loading replies for ${commentIdStr}, skipping request`);
      return;
    }
    
    try {
      console.log(`Fetching ${fetchDirection} replies for comment ${commentIdStr}, page ${pageNum}, append=${append}`);
      setLoadingMoreReplies(prev => ({ ...prev, [commentIdStr]: true }));
      
      // Prepare request params
      const params = {
        commentId: commentIdStr,
        page: pageNum,
        limit: 8,
        fetchDirection // Important: Tell server if we want newer or older replies
      };
      
      // Only add skipIds if we have any to skip
      if (skipIds && skipIds.length > 0) {
        params.skipIds = skipIds.join(',');
      }
      
      // For replies, use afterTimestamp for newer replies, beforeTimestamp for older
      if (timestamp) {
        if (fetchDirection === 'newer') {
          params.afterTimestamp = timestamp; // Add this parameter for newer replies
        } else {
          params.beforeTimestamp = timestamp;
        }
      }
      
      const { data } = await axios.get(`${api}/user-interactions/c/${postId}`, {
        params,
        withCredentials: true,
        headers: {
          accessToken: localStorage.getItem("accessToken")
        }
      });
      
      console.log(`Received ${data?.comments?.length || 0} replies for comment ${commentIdStr}`);
      
      if (data && data.comments && data.comments.length > 0) {
        // Update the replies state
        setReplies((prevReplies) => {
          const existingReplies = prevReplies[commentIdStr] || [];
          
          // Deduplicate replies by ID
          const existingIds = new Set(existingReplies.map(r => r.id));
          const uniqueNewReplies = data.comments.filter(r => !existingIds.has(r.id));
          
          return { 
            ...prevReplies, 
            [commentIdStr]: append ? [...existingReplies, ...uniqueNewReplies] : data.comments 
          };
        });
        
        // Update pagination info - store the timestamp of the newest reply for next pagination
        setReplyPagination(prev => ({
          ...prev,
          [commentIdStr]: {
            page: pageNum,
            limit: data.pagination.limit,
            total: data.pagination.total || (data.comments.length + skipIds.length),
            hasMore: data.pagination.hasMore,
            newestTimestamp: data.comments.length > 0 
              ? new Date(data.comments[data.comments.length - 1].createdAt).toISOString()
              : timestamp,
            loadedIds: append 
              ? [...(skipIds || []), ...data.comments.map(r => r.id.toString())]
              : data.comments.map(r => r.id.toString())
          }
        }));
      } else {
        // No replies returned, mark hasMore as false
        setReplyPagination(prev => ({
          ...prev,
          [commentIdStr]: {
            ...prev[commentIdStr],
            hasMore: false
          }
        }));
      }
    } catch (error) {
      console.error(`Error fetching replies for comment ${commentIdStr}:`, error);
    } finally {
      setLoadingMoreReplies(prev => ({ ...prev, [commentIdStr]: false }));
    }
  };
  const loadMoreReplies = (commentId) => {
    // First convert to string for consistency
    const commentIdStr = commentId.toString();
    
    // Get pagination info
    const pagination = replyPagination[commentIdStr];
    
    console.log(`Attempting to load more replies for comment ${commentIdStr}`, { 
      pagination,
      hasMore: pagination?.hasMore
    });
    
    if (pagination && pagination.hasMore) {
      // Get existing replies for this comment
      const existingReplies = replies[commentIdStr] || [];
      
      // Extract IDs to avoid duplication
      const existingReplyIds = existingReplies.map(reply => reply.id.toString());
      
      console.log(`Loading more replies for comment ${commentIdStr}`);
      console.log(`Currently loaded ${existingReplyIds.length} replies, total is ${pagination.total || 'unknown'}`);
      
      // For replies, which are sorted ASC (oldest first), when we click "show more replies",
      // we want to load NEWER replies (those with timestamps > our newest reply)
      // This is opposite of parent comments pagination!
      
      // Get the NEWEST reply we currently have (last in the array since sorted ASC)
      const newestReply = existingReplies.length > 0 ? new Date(existingReplies[existingReplies.length - 1].createdAt).toISOString() : null;
      
      // IMPORTANT: Tell the server we're loading NEWER replies, not older ones
      fetchReplies(
        commentIdStr, 
        pagination.page + 1, 
        true, 
        existingReplyIds, 
        newestReply, 
        'newer' // Add this parameter to indicate direction
      );
    } else {
      console.log(`Cannot load more replies for ${commentIdStr}: pagination info missing or no more pages`);
    }
  };
  useEffect(() => {
    function handleClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpenMenuId(null);
      }
    }
  
    function handleScroll() {
      setOpenMenuId(null);
    }
  
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('scroll', handleScroll, true);
  
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('scroll', handleScroll, true);
    };
  }, []);
  
  useEffect(() => {
    function handleClickOutside(e) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target) &&
        reportWidgetRef.current &&
        !reportWidgetRef.current.contains(e.target)
      ) {
        handleClose();
        setShowReportWidget(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
     
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      
      };
    }
  }, [isOpen, handleClose, showReportWidget]);

  const handleSubmitComment = async () => {
    if (!comment.trim()) return;
    
    // Store current comment text and then clear input
    const commentText = comment;
    setComment('');
    
    // Store these values before clearing them
    const tempParentId = parentId;
    const tempReplyingTo = replyingTo;
    const tempHighlightedReplyId = highlightedReplyId;
    
    // Create a unique temporary ID to identify this specific comment
    const tempId = `temp-${Date.now()}`;
  
    const finalReplyingTo =
      tempHighlightedReplyId && tempHighlightedReplyId !== tempParentId ? tempReplyingTo : null;
  
    // Set submitting state to true to show loading overlay
    setIsSubmitting(true);
  
    // Create optimistic comment for UI update
    const optimisticComment = {
      id: tempId,
      content: commentText,
      user: userData,
      likes: 0,
      userLiked: false,
      createdAt: new Date().toISOString(),
      replies: 0,
      parentId: tempParentId,
      replyingto: finalReplyingTo,
      isPending: true
    };
    
    // Apply optimistic UI update with the temporary comment
    if (tempParentId) {
      setExpandedCommentIds(prev => new Set([...prev, tempParentId]));
      setReplies(prev => {
        const currentReplies = prev[tempParentId] || [];
        return {
          ...prev,
          [tempParentId]: [...currentReplies, optimisticComment]
        };
      });
      setComments(prev => prev.map(c => 
        c.id === tempParentId ? { ...c, replies: c.replies + 1 } : c
      ));
    } else {
      setComments(prev => [optimisticComment, ...prev]);
    }
    
    // Clear reply state
    setParentId(null);
    setReplyingTo(null);
    setHighlightedReplyId(null);
  
    try {
      const { data } = await axios.post(`${api}/user-interactions/comment`, {
        postId,
        content: commentText,
        parentId: tempParentId,
        replyingto: finalReplyingTo,
      }, {
        withCredentials: true,
        headers: {
          accessToken: localStorage.getItem("accessToken")
        }
      });

      if (data.success && data.comment) {
        // Process the server response - handle different user property names
        const serverComment = {
          ...data.comment,
          // If data.comment.user is undefined, use data.comment.User or fall back to optimistic comment's user data
          user: data.comment.user || data.comment.User || userData
        };
        
        // Increment the new comment count when a successful comment is added
        setNewCommentCount(prev => prev + 1);
        
        // Replace the temporary comment with the real one
        if (tempParentId) {
          setReplies(prev => {
            const updatedReplies = { ...prev };
            const parentReplies = updatedReplies[tempParentId] || [];
            updatedReplies[tempParentId] = parentReplies.map(reply =>
              reply.id === tempId ? serverComment : reply
            );
            return updatedReplies;
          });
        } else {
          setComments(prev => prev.map(comment =>
            comment.id === tempId ? serverComment : comment
          ));
        }
      } else {
        console.error('Server did not return a complete comment object:', data);
        removeOptimisticComment(tempId, tempParentId);
      }
    } catch (error) {
      console.error('Error submitting comment:', error.message);
      removeOptimisticComment(tempId, tempParentId);
      toast.error('Failed to add comment. Please try again.');
    } finally {
      // Always set submitting to false when done, whether successful or not
      setIsSubmitting(false);
    }
  };
  
  // Helper function to remove optimistic comment in case of error
  const removeOptimisticComment = (tempId, parentId) => {
    if (parentId) {
      // Remove from replies
      setReplies(prev => {
        const updatedReplies = { ...prev };
        const parentReplies = updatedReplies[parentId] || [];
        updatedReplies[parentId] = parentReplies.filter(r => r.id !== tempId);
        return updatedReplies;
      });
      
      // Decrement the reply count
      setComments(prev => prev.map(c => 
        c.id === parentId ? { ...c, replies: Math.max(0, c.replies - 1) } : c
      ));
    } else {
      // Remove from top-level comments
      setComments(prev => prev.filter(c => c.id !== tempId));
    }
  };
  const handleKeyDown = (e) => {
    // Check if the Enter key was pressed without Shift (Shift+Enter allows for line breaks)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault(); // Prevent default to avoid adding a newline
      handleSubmitComment();
    }
  };

  const handleSecondLevelReplyClick = (topCommentId, replyId, username) => {
    setParentId(topCommentId);
    setReplyingTo(username);
    setHighlightedReplyId(replyId);
  };

  useEffect(() => {
    const handleResize = () => {
      setIsLargeScreen(window.innerWidth >= 1024);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const pickerRef = useRef(null);

  // Add click outside handler for emoji picker
  useEffect(() => {
    function handleClickOutside(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target) && 
          !e.target.closest('.emoji-trigger')) {
        setShowPicker(false);
      }
    }
    
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  const togglePicker = () => setShowPicker((prev) => !prev);

  const onEmojiClick = (emojiData) => {
    setComment((prev) => prev + (emojiData?.emoji || ''));
  };

  const handleTouchStart = (e) => {
    setIsDragging(true);
    setStartY(e.touches[0].clientY);
  };

  const handleTouchMove = (e) => {
    if (!isDragging) return;
    const touchY = e.touches[0].clientY;
    setCurrentY(touchY - startY);
  };

  const handleTouchEnd = () => {
    setIsDragging(false);
    setStartY(0);
    setCurrentY(0);
  };

  if (!isOpen) return null;

  // Filter top-level comments
  const topLevelComments = comments;

  const handleToggleReplies = (commentId) => {
    // Always convert to string for consistent comparison
    const stringId = commentId.toString();
    
    // Create a new Set from the current expandedCommentIds
    const newExpandedIds = new Set(expandedCommentIds);
    
    // If this commentId is already in the set, remove it (collapse)
    // Otherwise, add it to the set (expand)
    if (newExpandedIds.has(stringId)) {
      console.log(`Collapsing comment ${stringId}`);
      newExpandedIds.delete(stringId);
    } else {
      console.log(`Expanding comment ${stringId}`);
      newExpandedIds.add(stringId);
      
      // Check if we have expected replies for this comment from notification data
      if (expectedReplies[stringId]) {
        console.log(`Using ${expectedReplies[stringId].length} expected replies from notification data`);
        
        // Use the expected replies we already received from the notification
        setReplies(prev => ({
          ...prev,
          [stringId]: expectedReplies[stringId]
        }));
        
        // Set pagination info accordingly to enable "load more"
        setReplyPagination(prev => ({
          ...prev,
          [stringId]: {
            page: 1,
            limit: expectedReplies[stringId].length,
            hasMore: true // Set to true to allow loading more beyond initial set
          }
        }));
        
        // Clear expected replies after using them to prevent duplicates in future
        setExpectedReplies(prev => {
          const newExpected = { ...prev };
          delete newExpected[stringId];
          return newExpected;
        });
      } 
      // Only fetch if we don't already have the replies and no expected replies
      else if (!replies[stringId]) {
        console.log(`No cached replies for ${stringId}, fetching from server`);
        fetchReplies(stringId);
      } else {
        console.log(`Using ${replies[stringId].length} existing replies from cache`);
      }
    }
    
    // Update the state with the new Set
    setExpandedCommentIds(newExpandedIds);
  };
  const getRepliesForComment = (commentId) => {
    return replies[commentId] || [];
  };

  const handleReplyClick = (commentId, username) => {
    setParentId(commentId);
    setHighlightedReplyId(commentId);
    setReplyingTo(username);
  };

  const formatTime = (time) => {
    const now = moment();
    const commentTime = moment(time);
    const diff = now.diff(commentTime, 'days');

    if (diff < 1) {
      return commentTime.fromNow();
    } else if (diff < 7) {
      return commentTime.fromNow(true);
    } else {
      return commentTime.format('MM/DD/YY');
    }
  };

  useEffect(() => {
    if (expandedCommentIds.size > 0) {
      console.log("Currently expanded comments:", Array.from(expandedCommentIds));
      console.log("Available replies:", Object.keys(replies).map(key => parseInt(key)));
    }
  }, [expandedCommentIds, replies]);

  // Add this effect outside the render function to handle force-expanding comments
  useEffect(() => {
    if (highlightedReplyId && replies) {
      // Find which comment contains the highlighted reply
      for (const [commentId, commentReplies] of Object.entries(replies)) {
        // Check if this comment's replies contain the highlighted reply
        if (commentReplies.some(r => r.id === highlightedReplyId)) {
          const parentId = parseInt(commentId);
          console.log(`Found highlighted reply ${highlightedReplyId} in parent comment ${parentId}`);
          
          // Expand this comment if it's not already expanded
          if (!expandedCommentIds.has(parentId)) {
            console.log(`Force expanding comment ${parentId} to show highlighted reply`);
            setExpandedCommentIds(prev => new Set([...prev, parentId]));
          }
          break;
        }
      }
    }
  }, [highlightedReplyId, replies, expandedCommentIds]);

  // Skeleton loader components
  const CommentSkeleton = () => (
    <div className="space-y-2 gap-3 animate-pulse">
      <div className="space-y-2 gap-4">
        <div className="flex items-start gap-2">
          <div className="w-9 h-9 max-md:w-8 max-md:h-8 rounded-full bg-gray-700 flex-shrink-0 mt-1"></div>
          <div className="flex flex-col flex-grow w-full">
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-3">
                <div className="h-4 bg-gray-700 rounded w-24"></div>
                <div className="h-3 bg-gray-700 rounded w-12"></div>
              </div>
            </div>
            <div className="mt-2 space-y-2">
              <div className="h-3 bg-gray-700 rounded w-full"></div>
              <div className="h-3 bg-gray-700 rounded w-3/4"></div>
            </div>
          </div>
        </div>
        
        <div className="flex items-center gap-4 w-full mt-1 pl-10">
          <div className="h-4 bg-gray-700 rounded w-14"></div>
          <div className="h-4 bg-gray-700 rounded w-14"></div>
        </div>
      </div>
    </div>
  );

  const ReplySkeleton = () => (
    <div className="relative space-y-[3px] animate-pulse">
      <div className="flex items-start gap-1">
        <div className="w-7 h-7 max-md:h-6 max-md:w-6 rounded-full bg-gray-700 flex-shrink-0 mt-2"></div>
        <div className="flex flex-col flex-grow">
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
              <div className="h-3 bg-gray-700 rounded w-20 ml-1"></div>
              <div className="h-2 bg-gray-700 rounded w-10"></div>
            </div>
          </div>
          <div className="mt-2 ml-1">
            <div className="h-3 bg-gray-700 rounded w-full"></div>
            <div className="h-3 bg-gray-700 rounded w-2/3 mt-1"></div>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-4 w-full pl-10 mt-1">
        <div className="h-3 bg-gray-700 rounded w-10"></div>
        <div className="h-3 bg-gray-700 rounded w-10"></div>
      </div>
    </div>
  );

const renderTopLevelComment = (c) => {
  const commentReplies = getRepliesForComment(c.id);
  const hasReplies = c.replies > 0;
  const replyPaginationInfo = replyPagination[c.id] || { hasMore: false };
  const isLoadingReplies = loadingMoreReplies[c.id] || false;
  // Check if this comment's replies are expanded
  const isExpanded = expandedCommentIds.has(c.id);
  
  // Check if this comment has the highlighted reply
  const hasHighlightedReply = commentReplies.some(r => r.id === highlightedReplyId);
  
  // Check if this comment is the target of a comment_like or comment notification,
  // or if it's specifically marked as the target
  const isTargetComment = 
  c.isTargetComment ||
  (notificationData?.reference_id == c.id && 
   (notificationData.type === 'comment_like' || notificationData.type === 'comment'));

  // Determine CSS classes for highlighting - add specific style for target comments
  const commentClasses = isTargetComment
    ? 'bg-opacity-20 bg-blue-900 p-2 rounded-lg border-l-4 border-blue-500 highlight-pulse'
    : '';

  const renderRepliesContent = () => {
    if (isLoadingReplies) {
      return (
        <>
          <ReplySkeleton />
          <ReplySkeleton />
          <ReplySkeleton />
        </>
      );
    }
    
    return commentReplies.map((r) => (
      <div
        key={r.id}
        id={`reply-${r.id}`} // Add ID for scroll targeting
        className={`relative space-y-[3px] ${highlightedReplyId === r.id ? 'p-2 bg-[#222222]' : ''}`}
      >
        <div className="flex items-start gap-1">
          <div className="w-7 h-7 max-md:h-6 max-md:w-6 rounded-full overflow-hidden flex-shrink-0 mt-2">
            <img
              src={
                r.user.profilePicture ?
                `${cloud}/cloudofscubiee/profilePic/${r.user.profilePicture}` : "/logos/DefaultPicture.png"}
              alt={r.user.username}
              className="w-full bg-gray-300 h-full object-cover"
            />
          </div>
          <div className="flex flex-col flex-grow">
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm text-gray-200 pl-[6px] cursor-pointer" onClick={() => navigateToUserProfile(r.user.username)}>{r.user.username}</span>
                <span className="text-xs text-gray-500">{formatTime(r.createdAt)}</span>
              </div>
              <div className="relative">
                <button onClick={() => handleMenuClick(r.id)}>
                  <BiDotsVerticalRounded className="w-5 h-5 text-gray-400" />
                </button>
                {openMenuId === r.id && (
                  <div className="absolute right-0 top-5 mr-2 mb-2 py-1 w-24 bg-[#0f0f0f] rounded-md shadow-lg z-10">
                    {r.user.id === userData.id ? (
                      <button 
                        onClick={(e) => {
                          // Call handleDelete directly without setting timeout
                          handleDelete(r.id, e);
                        }} 
                        className="block w-full px-0 py-1 text-[16px] text-red-500 font-open-sans hover:bg-[#303030]"
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        Delete
                      </button>
                    ) : (
                      <button onClick={(e) => handleReport(r.id, e)} 
                        className="block w-full px-0 py-1 text-[16px] text-red-500 font-open-sans hover:bg-[#303030]"
                        onMouseDown={(e) => e.stopPropagation()}>
                        Report
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>

            <p className="text-md text-gray-300 ml-[6px]">
              {r.replyingto && <span className="text-blue-300 font-semibold pt-1 cursor-pointer" onClick={() => {
                if (r.replyingto === userData.username) {
                  window.location.reload();
                } else {
                  navigateToUserProfile(r.replyingto);
                }
              }}>@{r.replyingto} </span>}
              {r.content}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4 w-full pl-10 font-sans font-semibold">
          <button 
            className="text-gray-500 hover:text-gray-300 mt-1 flex items-center text-[13px] transform transition-transform duration-200"
            onClick={(e) => handleLikeClick(r.id, r.userLiked, e)}
          >
            {r.userLiked || likedComments.includes(r.id) ? (
              <IoMdHeart className="w-4 h-4 ml-[-4px] mr-[6px] text-red-500" />
            ) : (
              <IoMdHeartEmpty className="w-[17px] h-[17px] ml-[-4px] mr-[6px]" />
            )}
            <span className='text-[14px]'>{r.likes || 0}</span>
          </button>
          <button
            className="text-gray-500 hover:text-gray-300 mt-1 flex items-center text-sm"
            onClick={() => handleSecondLevelReplyClick(c.id, r.id, r.user.username)}
          >
            <MessageCircle className="w-[13px] h-[14px] mr-1" />
            Reply
          </button>
        </div>
      </div>
    ));
  };

  return (
    <div 
      key={c.id} 
      data-comment-id={c.id} 
      className={`space-y-2 gap-3 ${commentClasses}`}
    >
      <div className={`space-y-2 gap-4 ${highlightedReplyId === c.id ? 'p-1 bg-[#222222] rounded-lg' : ''}`}>
        <div className={`flex items-start gap-2`}>
          <div className="w-9 h-9 max-md:w-8 max-md:h-8 rounded-full overflow-hidden flex-shrink-0 mt-1">
            <img
              src={
                c.user.profilePicture ?
                `${cloud}/cloudofscubiee/profilePic/${c.user.profilePicture}` : "/logos/DefaultPicture.png"}
              alt={c.user.username} 
              className="w-full bg-gray-300 h-full object-cover"
            />
          </div>
          <div className="flex flex-col flex-grow">
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-3">
                <span 
                  className="font-medium text-sm text-gray-200 cursor-pointer" 
                  onClick={() => navigateToUserProfile(c.user.username)}>
                  {c.user.username}
                </span>
                <span className="text-xs text-gray-500">{formatTime(c.createdAt)}</span>
              </div>
              <div className="relative" ref={menuRef}>
                <button onClick={() => handleMenuClick(c.id)}>
                  <BiDotsVerticalRounded className="w-5 h-5 text-gray-400" />
                </button>
                {openMenuId === c.id && (
                  <div className="absolute right-0 mt-1 py-1 w-24 bg-[#0f0f0f] rounded-md shadow-lg z-10">
                    {c.user.id === userData.id ? (
                      <button 
                        onClick={(e) => {
                          // Call handleDelete directly without setting timeout
                          handleDelete(c.id, e);
                        }} 
                        className="block w-full px-0 py-1 text-[16px] font-open-sans text-red-500 hover:bg-[#303030]"
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        Delete
                      </button>
                    ) : (
                      <button 
                        onClick={(e) => handleReport(c.id, e)}
                        className="block w-full px-0 py-1 text-[16px] font-open-sans text-red-500 hover:bg-[#303030]"
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        Report
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
            <p className="text-[15px] text-gray-300 pt-1">{c.content}</p>
          </div>
        </div>
        
        <div className={`flex font-sans font-semibold items-center gap-4 w-full mt-[-6px] pl-10 ${highlightedReplyId === c.id ? 'p-2 bg-[#222222]' : ''}`}>
          <button 
            className="text-gray-500 hover:text-gray-300 flex items-center text-sm transform transition-transform duration-200"
            onClick={(e) => handleLikeClick(c.id, c.userLiked, e)}
          >
            {c.userLiked ? (
              <IoMdHeart className="w-[18px] h-[18px] mr-1 text-red-500" />
            ) : (
              <IoMdHeartEmpty className="w-[18px] h-[18px] mr-1" />
            )}
            {c.likes}
          </button>
          <button
            className={`text-gray-500 hover:text-gray-300 flex items-center text-sm ${highlightedReplyId === c.id ? 'text-md hover:text-red-600 text-red-500' : ''}`}
            onClick={
              highlightedReplyId === c.id
                ? () => {
                    setParentId(null);
                    setReplyingTo(null);
                    setHighlightedReplyId(null);
                  }
                : () => handleReplyClick(c.id, c.user.username)
            }
          >
            {highlightedReplyId === c.id ? null : <MessageCircle className="w-4 h-4 mr-1" />}
            {highlightedReplyId === c.id ? "Cancel" : "Reply"}
          </button>
          {c.replies > 0 && (
            <button
              className="text-gray-500 hover:text-gray-300 flex items-center text-sm"
              onClick={() => handleToggleReplies(c.id)}
            >
              <ChevronDown className={`w-4 h-4 mr-1 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
              {isExpanded ? 'Hide Replies' : `View Replies (${c.replies})`}
            </button>
          )}
        </div>
        <div></div>
      </div>
      
      {isExpanded && (
        <div className="ml-12 pt-2 border-l-2 border-gray-700 pl-4 space-y-4 bg">
          {renderRepliesContent()}
          
          {/* Load More Replies button */}
          {isExpanded && replyPaginationInfo && replyPaginationInfo.hasMore && (
            <div className="flex justify-center py-2">
              <button 
                onClick={() => loadMoreReplies(c.id)}
                className="text-blue-400 hover:text-blue-300 text-sm font-medium flex items-center"
                disabled={isLoadingReplies}
              >
                {isLoadingReplies ? (
                  <div className="animate-spin rounded-full h-4 w-4 border-t-2 border-b-2 border-white mr-2"></div>
                ) : null}
                {isLoadingReplies ? "Loading..." : "Show more replies"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

  return (
    <div className="fixed inset-0 backdrop-blur-sm bg-opacity-30 z-50 flex items-end justify-center"    
      onClick={(e) => {
        e.stopPropagation();
        handleClose(); // Use the modified close handler
      }}
    >
      <div
        ref={containerRef}
        onClick={(e) => e.stopPropagation()}
        className={`bg-[#131313] w-full md:w-[70%] ${isHomePage ? 'lg:w-[43%] lg:mr-60' : 'lg:w-[43%]'}
          rounded-t-xl h-[90vh] flex flex-col transition-transform duration-300 ease-in-out
          ${slideIn ? 'translate-y-0' : 'translate-y-full'}
        `}
      >
        {/* Header */}
        <div
          className="p-4 flex items-center justify-between border-b border-gray-800"
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
          <div className="hover:cursor-pointer h-6 flex items-center justify-between w-full"> 
            <h1 className='font-lato font-semibold text-lg'>Comments</h1>
            <IoCloseSharp className='w-7 h-6' onClick={handleClose}/> {/* Use the modified close handler */}
          </div>
        </div>

        <div ref={commentsListRef} className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Show skeletons while loading initial comments */}
          {loadingComments && comments.length === 0 ? (
            <>
              <CommentSkeleton />
              <CommentSkeleton />
              <CommentSkeleton />
              <CommentSkeleton />
            </>
          ) : (
            topLevelComments.map(renderTopLevelComment)
          )}
          
          {/* Show skeleton loaders when loading more comments */}
          {loadingComments && comments.length > 0 && (
            <>
              <CommentSkeleton />
              <CommentSkeleton />
            </>
          )}
          
          {/* Rest of the UI for end messages */}
          {(!hasMoreComments || (isNotificationView && isLastPage)) && 
           !loadingComments && !fetchError && comments.length > 0 && (
            <div className="text-center text-gray-500 py-3 text-sm">
              You've reached the end
            </div>
          )}
          
          {/* Empty state when no comments */}
          {!loadingComments && !fetchError && comments.length === 0 && (
            <div className="text-center text-gray-400 py-8">
              Be the first to comment
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="p-3 border-t border-[#202010]">
          <div className=" mb-1 relative">
            {replyingTo && (
              <div className="flex items-center mb-2 ml-2 md:ml-9 bg-[#1d1d1d] w-fit border-l-2 pl-2 rounded-md">
                <span className="text-[16px] text-gray-300 b">Replying to <span className='text-blue-500'>@{replyingTo}</span></span>
                <button
                  className="ml-2 text-gray-400 hover:text-gray-300"
                  onClick={() => {
                    setParentId(null);
                    setReplyingTo(null);
                    setHighlightedReplyId(null);
                  }}
                >
                  <X className="text-red-800 w-5 h-5" />
                </button>
              </div>
            )}
            <div className="flex items-center space-x-3">
              {isLargeScreen && (
                <FaRegFaceSmile
                  onClick={togglePicker}
                  style={{ cursor: 'pointer' }}
                  className="w-6 h-6 mt-1 emoji-trigger" // Added emoji-trigger class for click handler
                />
              )}
              <input
                type="text"
                placeholder="Write a comment..."
                className="w-full rounded-md border-b-2 bg-[#0f0f0f] border-gray-400 p-2 text-sm text-gray-100 placeholder-gray-400 focus:outline-none"
                autoFocus={isLargeScreen}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                onKeyDown={handleKeyDown} // Add this line to handle Enter key press

              />
              <BsSend className=' h-6 w-7 hover:cursor-pointer' onClick={handleSubmitComment}/>
            </div>
            {isLargeScreen && showPicker && (
              <div 
                ref={pickerRef} 
                className="absolute bottom-full left-0 mb-2 z-[100]" // Changed position to bottom-full and increased z-index
              >
                <Picker theme="dark" onEmojiClick={onEmojiClick} />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Conditionally render ReportWidget */}
      {showReportWidget && (
        <div
          className="fixed inset-0 flex items-center justify-center"
          onClick={(e) => e.stopPropagation()}
        >
          <div
            ref={reportWidgetRef}
            className="bg-[#1a1a1a] p-4 rounded-md w-[90%] sm:w-[400px] text-white"
          >
            <ReportWidget 
              onClose={() => setShowReportWidget(false)}
              type="comment"
              targetId={reportWidgetId} // Pass the reportWidgetId here
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
       {isSubmitting && (
    <div className="fixed inset-0 bg-black bg-opacity-30 z-[60] flex items-center justify-center">
      <div className="bg-[#1a1a1a] rounded-lg p-4 flex items-center space-x-3">
        <div className="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-white"></div>
        <span className="text-white font-medium">Posting comment...</span>
      </div>
    </div>
  )}
    </div>
  );
}

export default CommentWidget;





