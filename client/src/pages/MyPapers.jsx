import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, Plus, Clock, FileText, RefreshCw, Calendar, ChevronDown, X, Newspaper, Filter } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { createPortal } from 'react-dom';
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { BsBookmark, BsBookmarkFill, BsSend } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { TfiCommentAlt } from "react-icons/tfi";
import { FiMoreVertical } from "react-icons/fi";
import axios from 'axios';
import { IoNewspaperOutline } from 'react-icons/io5';

// Portal component for modals
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted && typeof document !== 'undefined' ? createPortal(children, document.body) : null;
};

// Smart Truncate Text component (copied from Paper.jsx)
const SmartTruncateText = ({ text, className = '' }) => {
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
        className={`${className} ${isExpanded ? '' : needsTruncate ? 'line-clamp-3' : ''}`}
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

const MyPaper = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;
  const cloud = import.meta.env.VITE_CLOUD_URL;
  
  // Check if we're on the "the-paper" route
  const isThePaperRoute = location.pathname === '/the-paper';
  // State for papers and UI
  const [papers, setPapers] = useState([]);
  const [allPapersData, setAllPapersData] = useState(null); // Store all fetched data
  const [posts, setPosts] = useState([]); // For displaying posts in feed format
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [paperData, setPaperData] = useState(null); // For "the-paper" route
  const [hasAnyPapers, setHasAnyPapers] = useState(false); // Track if user has any papers in database
    // Filter states - Updated options (removed 'all-today', added direct navigation)
  const [activeFilter, setActiveFilter] = useState('today'); // 'today', 'unread', 'read', 'yesterday'
  const [showFilterDropdown, setShowFilterDropdown] = useState(false);
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [selectedDate, setSelectedDate] = useState('');
  const [availableDates, setAvailableDates] = useState([]);
  
  // Post interaction states (similar to Paper.jsx)
  const [likedPosts, setLikedPosts] = useState({});
  const [savedPosts, setSavedPosts] = useState({});
  const [viewingImage, setViewingImage] = useState(null);
  const [imageIndex, setImageIndex] = useState(0);
  const [activeMenu, setActiveMenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
  const [showShareWidget, setShowShareWidget] = useState(false);
  const [sharePostId, setSharePostId] = useState(null);
  const [showCopyNotification, setShowCopyNotification] = useState(false);
  
  // Refs
  const menuRef = useRef(null);
  const pendingLikeOperations = useRef(new Map());
  const pendingSaveOperations = useRef(new Map());
  const visualState = useRef({
    likedPosts: {},
    savedPosts: {}  });  // Apply frontend filtering function for the-paper route
  const applyFilter = (allData, filterType) => {
    if (!allData) return [];
    
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    
    const formatDate = (date) => date.toISOString().split('T')[0];
    const todayStr = formatDate(today);
    const yesterdayStr = formatDate(yesterday);
    
    switch (filterType) {
      case 'today':
        // Only unread papers from today
        return allData.todayPapers?.filter(paper => !paper.isRead) || [];
      
      case 'unread':
        // All unread papers (today and yesterday)
        const unreadToday = allData.todayPapers?.filter(paper => !paper.isRead) || [];
        const unreadYesterday = allData.yesterdayPapers?.filter(paper => !paper.isRead) || [];
        return [...unreadToday, ...unreadYesterday];
      
      case 'read':
        // All read papers (today and yesterday)
        const readToday = allData.todayPapers?.filter(paper => paper.isRead) || [];
        const readYesterday = allData.yesterdayPapers?.filter(paper => paper.isRead) || [];
        return [...readToday, ...readYesterday];
      
      case 'yesterday':
        // Yesterday's papers (all)
        return allData.yesterdayPapers || [];
      
      default:
        return allData.todayPapers?.filter(paper => !paper.isRead) || [];
    }
  };

  // Apply frontend filtering function for my-papers route
  const applyFilterForMyPapers = (allPapers, filterType) => {
    if (!allPapers || allPapers.length === 0) return [];
    
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    
    const formatDate = (date) => date.toISOString().split('T')[0];
    const todayStr = formatDate(today);
    const yesterdayStr = formatDate(yesterday);
    
    switch (filterType) {
      case 'today':
        // Only unread papers from today
        return allPapers.filter(paper => {
          const paperDate = new Date(paper.paperDate).toISOString().split('T')[0];
          return paperDate === todayStr && !paper.isRead;
        });
      
      case 'unread':
        // All unread papers
        return allPapers.filter(paper => !paper.isRead);
      
      case 'read':
        // All read papers
        return allPapers.filter(paper => paper.isRead);
      
      case 'yesterday':
        // Yesterday's papers (all)
        return allPapers.filter(paper => {
          const paperDate = new Date(paper.paperDate).toISOString().split('T')[0];
          return paperDate === yesterdayStr;
        });
      
      default:
        // Default to today's unread papers
        return allPapers.filter(paper => {
          const paperDate = new Date(paper.paperDate).toISOString().split('T')[0];
          return paperDate === todayStr && !paper.isRead;
        });
    }
  };
  const fetchPapers = async (filterToApply = null) => {
    try {
      setError('');
      setLoading(true);

      if (isThePaperRoute) {
        // Comprehensive fetch for "the-paper" route - fetch all data once
        const [todayResponse, yesterdayResponse] = await Promise.allSettled([
          axios.get(`${api}/papers/the-paper`, { withCredentials: true }),
          axios.get(`${api}/papers/the-paper?date=yesterday`, { withCredentials: true })
        ]);

        const allData = {
          todayPapers: [],
          yesterdayPapers: []
        };

        // Process today's paper
        if (todayResponse.status === 'fulfilled' && todayResponse.value.data.success) {
          const paperData = todayResponse.value.data;
          setPaperData(paperData);
          
          // Transform posts for feed display
          if (paperData.posts && paperData.posts.length > 0) {
            const transformedPosts = paperData.posts.map(post => ({
              ...post,
              // Map user interaction states
              isLiked: post.userInteraction?.liked || false,
              isSaved: post.userInteraction?.saved || false,
              paper: {
                title: paperData.paper.title,
                description: paperData.paper.description,
                id: paperData.paper.id
              }
            }));
            setPosts(transformedPosts);
            
            // Set up interaction states
            const likedState = {};
            const savedState = {};
            transformedPosts.forEach(post => {
              likedState[post.id] = post.isLiked;
              savedState[post.id] = post.isSaved;
            });
            setLikedPosts(likedState);
            setSavedPosts(savedState);
          }

          allData.todayPapers = [{
            id: paperData.paper.id,
            paperId: paperData.paper.paperId,
            paperDate: paperData.paper.paperDate,
            deliveryTime: paperData.paper.deliveryTime,
            status: paperData.paper.status || 'delivered',
            isRead: paperData.paper.userReadStatus || false,
            readAt: paperData.paper.readAt,
            postCount: paperData.posts?.length || 0,
            paper: {
              title: paperData.paper.title,
              description: paperData.paper.description
            }
          }];
        }

        // Process yesterday's paper
        if (yesterdayResponse.status === 'fulfilled' && yesterdayResponse.value.data.success) {
          const yesterdayData = yesterdayResponse.value.data;
          allData.yesterdayPapers = [{
            id: yesterdayData.paper.id,
            paperId: yesterdayData.paper.paperId,
            paperDate: yesterdayData.paper.paperDate,
            deliveryTime: yesterdayData.paper.deliveryTime,
            status: yesterdayData.paper.status || 'delivered',
            isRead: yesterdayData.paper.userReadStatus || false,
            readAt: yesterdayData.paper.readAt,
            postCount: yesterdayData.posts?.length || 0,
            paper: {
              title: yesterdayData.paper.title,
              description: yesterdayData.paper.description
            }
          }];
        }        setAllPapersData(allData);
        
        // Apply the current filter (use passed filter or current activeFilter)
        const currentFilter = filterToApply || activeFilter;
        const filteredPapers = applyFilter(allData, currentFilter);
        setPapers(filteredPapers);

        if (filteredPapers.length === 0) {
          setError('No papers available for the selected filter');
        }      } else {
        // For my-papers route, fetch ALL papers at once and then filter on frontend
        const response = await axios.get(`${api}/papers/my-papers-list`, {
          params: {
            filter: 'all', // Get all papers
            limit: 100     // Increase limit to get all papers
          },
          withCredentials: true
        });
        
        if (response.data.success) {
          // Store all papers data
          const allPapers = response.data.papers || [];
          setAllPapersData({ allPapers });
          
          // Track if user has any papers at all
          setHasAnyPapers(allPapers.length > 0);
          
          // Apply current filter to the fetched data
          const currentFilter = filterToApply || activeFilter;
          const filteredPapers = applyFilterForMyPapers(allPapers, currentFilter);
          setPapers(filteredPapers);
        } else {
          setError('Failed to fetch papers');
          setHasAnyPapers(false);
        }
      }
    } catch (error) {
      console.error('Error fetching papers:', error);
      if (isThePaperRoute && error.response?.status === 404) {
        setError('No active paper found. Please create a paper first.');
      } else {
        setError(error.response?.data?.message || 'Failed to fetch papers');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };  useEffect(() => {
    fetchPapers();
  }, [isThePaperRoute]); // Only re-fetch when route changes, not filter changes

  // Helper functions
  const handleBack = () => {
    navigate(-1);
  };

  const handleRefresh = () => {
    setRefreshing(true);
    fetchPapers();
  };

  const handleCreatePaper = () => {
    navigate('/create-paper');
  };
  const handlePaperClick = async (paper) => {
    try {
      // Update read status when paper is clicked if it's unread
      if (!paper.isRead && paper.id) {
        await axios.post(`${api}/papers/update-read-status/${paper.id}`, {}, { withCredentials: true });
      }
    } catch (error) {
      console.error('Error updating read status:', error);
    }
    
    // Navigate to the Paper.js component using /paper/:id route for both routes
    navigate(`/paper/${paper.id}`);
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  // Post interaction handlers (similar to Paper.jsx)
  const handleLike = useCallback(async (postId) => {
    if (pendingLikeOperations.current.has(postId)) return;
    
    const currentLikedState = visualState.current.likedPosts[postId] ?? likedPosts[postId];
    const newLikedState = !currentLikedState;
    
    // Optimistic update
    visualState.current.likedPosts[postId] = newLikedState;
    setLikedPosts(prev => ({ ...prev, [postId]: newLikedState }));
    
    pendingLikeOperations.current.set(postId, true);
    
    try {
      await axios.post(`${api}/user-interactions/like/${postId}`, {}, {
        withCredentials: true
      });
    } catch (error) {
      console.error('Error toggling like:', error);
      // Revert on error
      visualState.current.likedPosts[postId] = currentLikedState;
      setLikedPosts(prev => ({ ...prev, [postId]: currentLikedState }));
    } finally {
      pendingLikeOperations.current.delete(postId);
    }
  }, [likedPosts]);

  const handleSave = useCallback(async (postId) => {
    if (pendingSaveOperations.current.has(postId)) return;
    
    const currentSavedState = visualState.current.savedPosts[postId] ?? savedPosts[postId];
    const newSavedState = !currentSavedState;
    
    // Optimistic update
    visualState.current.savedPosts[postId] = newSavedState;
    setSavedPosts(prev => ({ ...prev, [postId]: newSavedState }));
    
    pendingSaveOperations.current.set(postId, true);
    
    try {
      await axios.post(`${api}/user-interactions/save/${postId}`, 
        { action: newSavedState ? 'save' : 'unsave' },
        { withCredentials: true }
      );
    } catch (error) {
      console.error('Error toggling save:', error);
      // Revert on error
      visualState.current.savedPosts[postId] = currentSavedState;
      setSavedPosts(prev => ({ ...prev, [postId]: currentSavedState }));
    } finally {
      pendingSaveOperations.current.delete(postId);
    }
  }, [savedPosts]);

  const handleCommentClick = (postId, e) => {
    if (e) e.stopPropagation();
    // Navigate to the post view to see comments
    navigate(`/viewpost/${postId}`);
  };

  const handleSharePost = (postId, e) => {
    if (e) e.stopPropagation();
    setSharePostId(postId);
    setShowShareWidget(true);
  };

  const handleImageClick = (e, imageUrl, post, index) => {
    e.stopPropagation();
    setViewingImage(imageUrl);
    setImageIndex(index);
  };

  const handleMoreClick = (postId, e) => {
    e.stopPropagation();
    
    if (activeMenu === postId) {
      setActiveMenu(null);
      return;
    }
    
    // Get the position of the clicked button
    const buttonRect = e.currentTarget.getBoundingClientRect();
    setMenuPosition({
      top: buttonRect.bottom + 8,
      left: buttonRect.left - 100
    });
    setActiveMenu(postId);
  };

  const handleCopyLink = (postId, e) => {
    e.stopPropagation();
    const postUrl = `${window.location.origin}/viewpost/${postId}`;
    
    navigator.clipboard.writeText(postUrl)
      .then(() => {
        setShowCopyNotification(true);
        setTimeout(() => setShowCopyNotification(false), 2000);
        setActiveMenu(null);
      })
      .catch((err) => {
        console.error('Failed to copy text: ', err);
      });
  };

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (activeMenu && !event.target.closest('[data-more-button="true"]')) {
        setActiveMenu(null);
      }
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [activeMenu]);

  // Cleanup pending operations
  useEffect(() => {
    return () => {
      if (pendingLikeOperations.current.size > 0) {
        pendingLikeOperations.current.forEach(timerId => clearTimeout(timerId));
        pendingLikeOperations.current.clear();
      }
      if (pendingSaveOperations.current.size > 0) {
        pendingSaveOperations.current.forEach(timerId => clearTimeout(timerId));
        pendingSaveOperations.current.clear();
      }
    };
  }, []);  // Handle filter change for both routes - Pure frontend filtering
  const handleFilterChange = (filter) => {
    setActiveFilter(filter);
    
    if (!allPapersData) {
      // If no data is loaded yet, return early
      return;
    }
    
    if (isThePaperRoute) {
      // For the-paper route, apply frontend filtering immediately
      const filteredPapers = applyFilter(allPapersData, filter);
      setPapers(filteredPapers);
      
      // Update posts display based on filter
      if (filter === 'today' || filter === 'unread' || filter === 'read') {
        // Keep existing posts for today and combined filters
        // Posts are already set during fetchPapers
      } else if (filter === 'yesterday') {
        // Would need to fetch yesterday's posts if needed
        setPosts([]); // Clear posts for now
      }
    } else {
      // For my-papers route, apply frontend filtering using stored data
      const filteredPapers = applyFilterForMyPapers(allPapersData.allPapers, filter);
      setPapers(filteredPapers);
    }
  };

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1
      }
    }
  };

  const cardVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.3,
        ease: "easeOut"
      }
    }
  };
  return (
    <div className="min-h-screen mb-8 bg-[#0a0a0a] text-white">
      <div className="max-w-[500px]  md:max-w-[500px] mx-auto w-full mt-2 md:w-[95%] max-md:w-[98%]">
        {/* Top Bar */}
        <div className="sticky top-0 z-10 bg-[#0a0a0a]/90 backdrop-blur-md ">
          <div className="flex items-center justify-between px-4 py-3 ">
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleBack}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <ArrowLeft className="w-6 h-6 text-gray-300" />
            </motion.button>
            <h1 className="text-xl font-bold text-white">
              {isThePaperRoute ? 'Today\'s Paper' : 'Digital Papers'}
            </h1>              <div className="flex items-center space-x-2">
              {!isThePaperRoute && (
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={() => navigate('/manage-papers')}
                  className="p-2 hover:bg-gray-800 rounded-full transition-colors"
                  title="Manage Your Papers"
                >
                  <IoNewspaperOutline className="w-5 h-5 text-gray-300" />
                </motion.button>
              )}
              
              {!isThePaperRoute && (
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={handleCreatePaper}
                  className="p-2 bg-blue-500 hover:bg-blue-600 text-white rounded-full transition-colors shadow-lg"
                >
                  <Plus className="w-6 h-6" />
                </motion.button>
              )}
            </div>
          </div>
        </div>        {/* Enhanced Filter Buttons - Show for both routes with simplified options */}
        <div className="px-4 py-3 border-b border-gray-800">
          <div className="flex space-x-2 overflow-x-auto">
            {isThePaperRoute ? (
              // Simplified filters for the-paper route
              [
                { key: 'today', label: 'Today' },
                { key: 'unread', label: 'Unread' },
                { key: 'read', label: 'Read' },
                { key: 'yesterday', label: 'Yesterday' }
              ].map((filter) => (
                <motion.button
                  key={filter.key}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => handleFilterChange(filter.key)}
                  className={`px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors ${
                    activeFilter === filter.key
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {filter.label}
                </motion.button>
              ))
            ) : (
              // Simplified filters for my-papers route (removed "All Papers")
              [
                { key: 'today', label: 'Today' },
                { key: 'unread', label: 'Unread' },
                { key: 'read', label: 'Read' },
                { key: 'yesterday', label: 'Yesterday' }
              ].map((filter) => (
                <motion.button
                  key={filter.key}
                  whileTap={{ scale: 0.95 }}
                  onClick={() => handleFilterChange(filter.key)}
                  className={`px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors ${
                    activeFilter === filter.key
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {filter.label}
                </motion.button>
              ))
            )}
          </div>
        </div>
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="px-4 py-6 space-y-4"
        >        {loading ? (
          // Loading skeleton
          <div className="space-y-4">
            {[1, 2, 3].map((index) => (
              <div key={index} className="bg-[#111111] border border-gray-800 rounded-2xl p-6 py-4 animate-pulse">
                <div className="h-4 bg-gray-700 rounded mb-2"></div>
                <div className="h-3 bg-gray-700 rounded w-3/4"></div>
              </div>
            ))}
          </div>
        ) : error ? (
          // Error state
          <div className="text-center py-12">
            <div className="text-red-400 mb-4">{error}</div>
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleRefresh}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg flex items-center space-x-2 mx-auto"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Try Again</span>
            </motion.button>
          </div>        ) : papers.length === 0 ? (
          // Empty state
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center py-12"
          >
            {isThePaperRoute ? (
              <>
                <Newspaper className="w-16 h-16 text-gray-600 mx-auto mb-4" />
                <h3 className="text-xl font-semibold text-white mb-2">No Paper Available</h3>
                <p className="text-gray-400 mb-6">
                  {error || 'Your paper will be ready after the scheduled delivery time.'}
                </p>
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={() => navigate('/my-papers')}
                  className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold flex items-center space-x-2 mx-auto"
                >
                  <FileText className="w-5 h-5" />
                  <span>View All Papers</span>
                </motion.button>
              </>
            ) : (
              <>
                <FileText className="w-16 h-16 text-gray-600 mx-auto mb-4" />
                {!hasAnyPapers ? (
                  // User has never created any papers
                  <>
                    <h3 className="text-xl font-semibold text-white mb-2">No papers yet</h3>
                    <p className="text-gray-400 mb-6">Create your first digital paper to get started</p>
                    <motion.button
                      whileTap={{ scale: 0.95 }}
                      onClick={handleCreatePaper}
                      className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold flex items-center space-x-2 mx-auto"
                    >
                      <Plus className="w-5 h-5" />
                      <span>Create Paper</span>
                    </motion.button>
                  </>
                ) : (
                  // User has papers but none match current filter
                  <>
                    <h3 className="text-xl font-semibold text-white mb-2">No papers found</h3>
                   
                  </>
                )}
              </>
            )}
          </motion.div>
        ) : isThePaperRoute && posts && posts.length > 0 ? (
          // Feed view for the-paper route when posts are available
          <div className="space-y-6">
            {/* Paper Header */}
            {paperData && (
              <div className="bg-[#111111] border border-gray-800 rounded-2xl p-6">
                <h2 className="text-2xl font-bold text-white mb-2">{paperData.paper.title}</h2>
                <p className="text-gray-400 mb-4">{paperData.paper.description}</p>
                <div className="flex items-center justify-between text-sm text-gray-500">
                  <span>Delivered at {paperData.paper.deliveryTime}</span>
                  <span>{posts.length} articles</span>
                </div>
              </div>
            )}

            {/* Posts Feed */}
            {posts.map((post, index) => (
              <motion.article
                key={post.id}
                variants={cardVariants}
                initial="hidden"
                animate="visible"
                transition={{ delay: index * 0.1 }}
                className="bg-[#111111] border border-gray-800 rounded-2xl p-6 shadow-sm hover:shadow-xl transition-all duration-300"
              >
                {/* Post Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    <div
                      className="relative h-10 w-10 rounded-full overflow-hidden group cursor-pointer"
                      onClick={() => navigate(`/profile/${post.author.username}`)}
                    >
                      <img
                        src={post.author.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${post.author.profilePicture}`
                          : "/logos/DefaultPicture.png"}
                        alt={post.author.username}
                        className="w-full h-full bg-gray-300 object-cover transition-transform duration-200 group-hover:scale-110"
                      />
                    </div>
                    <div>
                      <div className="flex items-center gap-1">
                        <h3 className="text-[15px] font-semibold font-sans text-white">
                          {post.author.username}
                        </h3>
                        {post.author.verified && (
                          <RiVerifiedBadgeFill className="text-blue-500 text-[16px]" />
                        )}
                      </div>
                      <p className="text-xs text-gray-500">
                        {new Date(post.createdAt).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  
                  <button
                    onClick={(e) => handleMoreClick(post.id, e)}
                    className="p-2 hover:bg-gray-800 rounded-full transition-colors"
                    data-more-button="true"
                  >
                    <FiMoreVertical className="h-[19px] w-[19px] text-gray-400" />
                  </button>
                </div>

                {/* Post Content */}
                <div 
                  className="cursor-pointer"
                  onClick={() => navigate(`/viewpost/${post.id}`)}
                >
                  {/* Text Content */}
                  {(post.title || post.content || post.description) && (
                    <div className="mb-4">
                      <SmartTruncateText
                        text={post.title || post.content || post.description}
                        className="text-[16px] font-sans text-gray-300"
                      />
                    </div>
                  )}

                  {/* Media Content */}
                  {post.media && post.media.length > 0 && (
                    <div className="relative mb-4">
                      {post.media.length === 1 ? (
                        <div className="w-full">
                          {post.media[0].endsWith('.mp4') || post.media[0].endsWith('.webm') ? (
                            <video
                              src={`${cloud}/cloudofscubiee/media/${post.media[0]}`}
                              className="w-full h-auto object-cover rounded-lg cursor-pointer max-h-[400px]"
                              controls={false}
                              onClick={(e) => {
                                e.stopPropagation();
                                navigate(`/viewpost/${post.id}`);
                              }}
                            />
                          ) : (
                            <img
                              src={`${cloud}/cloudofscubiee/media/${post.media[0]}`}
                              alt="Post content"
                              className="w-full h-auto object-cover rounded-lg cursor-pointer max-h-[400px]"
                              onClick={(e) => handleImageClick(e, `${cloud}/cloudofscubiee/media/${post.media[0]}`, post, 0)}
                            />
                          )}
                        </div>
                      ) : (
                        <div className="grid grid-cols-2 gap-2">
                          {post.media.slice(0, 4).map((media, mediaIndex) => (
                            <div key={mediaIndex} className="relative">
                              {media.endsWith('.mp4') || media.endsWith('.webm') ? (
                                <video
                                  src={`${cloud}/cloudofscubiee/media/${media}`}
                                  className="w-full h-32 object-cover rounded-lg cursor-pointer"
                                  controls={false}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/viewpost/${post.id}`);
                                  }}
                                />
                              ) : (
                                <img
                                  src={`${cloud}/cloudofscubiee/media/${media}`}
                                  alt={`Post content ${mediaIndex + 1}`}
                                  className="w-full h-32 object-cover rounded-lg cursor-pointer"
                                  onClick={(e) => handleImageClick(e, `${cloud}/cloudofscubiee/media/${media}`, post, mediaIndex)}
                                />
                              )}
                              {mediaIndex === 3 && post.media.length > 4 && (
                                <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center rounded-lg">
                                  <span className="text-white font-semibold">+{post.media.length - 4}</span>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Post Actions */}
                <div className="flex items-center justify-between pt-3 border-t border-gray-800">
                  <div className="flex items-center space-x-6">
                    {/* Like Button */}
                    <button 
                      className="flex items-center gap-2 text-gray-300 group transform transition-transform duration-200"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleLike(post.id);
                      }}
                    >                      <div className="p-1 rounded-full border border-gray-600 hover:border-gray-500 transition-colors">
                        <BiUpvote 
                          className="h-[20px] w-[20px] empty-heart" 
                          style={{display: likedPosts[post.id] ? 'none' : 'block'}} 
                        />
                        <BiSolidUpvote 
                          className="h-[20px] w-[20px] text-blue-500 filled-heart" 
                          style={{display: likedPosts[post.id] ? 'block' : 'none'}} 
                        />
                      </div>
                      <span className='text-[14px] transition-colors duration-200'>
                        {post.likes?.toLocaleString() || '0'}
                      </span>
                    </button>

                    {/* Comment Button */}
                    <button 
                      className="flex items-center gap-2 text-gray-300 group"
                      onClick={(e) => handleCommentClick(post.id, e)}
                    >
                      <div className="p-1 rounded-full">
                        <TfiCommentAlt className="h-[18px] w-[18px]" />
                      </div>
                      <span className='text-[14px]'>
                        {(post.comments > 0) ? post.comments : '0'}
                      </span>
                    </button>

                    {/* Share Button */}
                    <button 
                      className="flex items-center text-gray-300 group"
                      onClick={(e) => handleSharePost(post.id, e)}
                    >
                      <div className="p-1 rounded-full">
                        <BsSend className="h-[18px] w-[18px]" />
                      </div>
                    </button>
                  </div>

                  {/* Save Button */}
                  <button 
                    className="flex items-center text-gray-300 group transform transition-transform duration-200"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSave(post.id);
                    }}
                  >
                    <div className="p-1 rounded-full">
                      <BsBookmark 
                        className="h-[18px] w-[18px] empty-bookmark" 
                        style={{display: savedPosts[post.id] ? 'none' : 'block'}} 
                      />
                      <BsBookmarkFill 
                        className="h-[18px] w-[18px] text-white filled-bookmark" 
                        style={{display: savedPosts[post.id] ? 'block' : 'none'}} 
                      />
                    </div>
                  </button>
                </div>
              </motion.article>
            ))}
          </div>) : (
          papers.map((paper) => (            <motion.div
              key={paper.id}
              variants={cardVariants}
              whileHover={{ y: -2, scale: 1.01 }}
              whileTap={{ scale: 0.98 }}
              onClick={() => handlePaperClick(paper)}
              className="relative bg-[#111111] border border-gray-800 rounded-2xl p-6 shadow-sm hover:shadow-xl transition-all duration-300 cursor-pointer w-full mx-auto"
              style={{ minHeight: '140px' }}
            >
              {/* Single blue dot indicator for unread papers */}
              {!paper.isRead && (
                <div className="absolute top-4 right-4">
                  <div className="w-3 h-3 bg-blue-500 rounded-full animate-pulse" title="Unread"></div>
                </div>
              )}
              
              <div className="flex flex-col h-full justify-between">
                {/* Title and Description */}
                <div>
                  <h3 className="text-lg font-bold text-white mb-2 line-clamp-2">
                    {paper.paper?.title}
                  </h3>
                  {paper.paper?.description && (
                    <p className="text-gray-400 text-sm line-clamp-2 mb-3">
                      {paper.paper?.description}
                    </p>
                  )}
                </div>
                  {/* Bottom Info */}
                <div className="flex items-center justify-between text-sm text-gray-400">
                  <div className="flex items-center space-x-4">
                    {/* Delivery Time */}
                    <div className="flex items-center space-x-1">
                      <Clock className="w-4 h-4" />
                      <span className="font-medium text-gray-300">{paper.deliveryTime}</span>
                    </div>
                    
                    {/* Post Count */}
                    <div className="flex items-center space-x-1">
                      <FileText className="w-4 h-4" />
                      <span className="text-gray-300">{paper.postCount} Posts</span>
                    </div>
                  </div>
                    {/* Status Badge - Simplified to show only read/unread */}
                  <div className="flex flex-col items-end space-y-1">
                    <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                      !paper.isRead 
                        ? 'bg-blue-500 text-white' 
                        : paper.status === 'scheduled' 
                          ? 'bg-yellow-500 text-black' 
                          : 'bg-gray-500 text-white'
                    }`}>
                      {!paper.isRead ? 'Unread' : paper.status === 'scheduled' ? 'Not Delivered' : 'Read'}
                    </div>
                  </div>
                </div>
                
                {/* Paper date */}
                <div className="text-xs text-gray-500 mt-2">
                  Paper Date: {formatDate(paper.paperDate)}
                  {paper.readAt && (
                    <span className="ml-2">• Read: {formatDate(paper.readAt)}</span>
                  )}
                </div>
              </div>

              {/* Subtle gradient overlay for visual appeal */}
              <div className="absolute inset-0 bg-gradient-to-r from-transparent to-blue-900/10 rounded-2xl pointer-events-none"></div>
            </motion.div>
          ))
        )}
      </motion.div>
      </div>

      {/* More Options Menu */}
      {activeMenu && (
        <div 
          className="fixed z-50 bg-[#111111] border border-gray-700 rounded-lg shadow-lg py-2 min-w-[150px]"
          style={{
            top: menuPosition.top,
            left: menuPosition.left,
            transform: 'translateX(-50%)'
          }}
        >
          <button
            onClick={(e) => handleCopyLink(activeMenu, e)}
            className="w-full px-4 py-2 text-left text-gray-300 hover:bg-gray-800 flex items-center space-x-2"
          >
            <span>Copy Link</span>
          </button>
        </div>
      )}

      {/* Image Viewer Modal */}
      {viewingImage && (
        <Portal>
          <div className="fixed inset-0 z-50 bg-black bg-opacity-90 flex items-center justify-center">
            <div className="relative max-w-4xl max-h-full p-4">
              <button
                onClick={() => setViewingImage(null)}
                className="absolute top-4 right-4 z-10 p-2 bg-black bg-opacity-50 rounded-full text-white hover:bg-opacity-70"
              >
                <X className="w-6 h-6" />
              </button>
              <img
                src={viewingImage}
                alt="Enlarged view"
                className="max-w-full max-h-full object-contain"
              />
            </div>
          </div>
        </Portal>
      )}

      {/* Share Widget */}
      {showShareWidget && (
        <Portal>
          <div className="fixed inset-0 z-50 bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div className="bg-[#111111] border border-gray-700 rounded-2xl p-6 w-full max-w-md">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">Share Post</h3>
                <button
                  onClick={() => setShowShareWidget(false)}
                  className="p-1 hover:bg-gray-800 rounded-full"
                >
                  <X className="w-5 h-5 text-gray-400" />
                </button>
              </div>
              <div className="space-y-3">
                <button
                  onClick={() => handleCopyLink(sharePostId, { stopPropagation: () => {} })}
                  className="w-full p-3 bg-gray-800 hover:bg-gray-700 rounded-lg text-left text-white flex items-center space-x-3"
                >
                  <span>📋</span>
                  <span>Copy Link</span>
                </button>
              </div>
            </div>
          </div>
        </Portal>
      )}

      {/* Copy Notification */}
      {showCopyNotification && (
        <div className="fixed top-4 left-1/2 transform -translate-x-1/2 z-50 bg-green-600 text-white px-4 py-2 rounded-lg shadow-lg">
          Link copied to clipboard!
        </div>
      )}
    </div>
  );
};

export default MyPaper;