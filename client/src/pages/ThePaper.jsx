import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, Clock, RefreshCw, Calendar, Eye, Heart, MessageCircle, Share2, Bookmark } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';

const ThePaper = () => {
  const navigate = useNavigate();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;
  
  // State for paper and UI
  const [paper, setPaper] = useState(null);
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [metadata, setMetadata] = useState(null);  const fetchTodaysPaper = async () => {
    try {
      setError('');
      setLoading(true);
        const response = await axios.get(`${api}/papers/thepaper`, {
        withCredentials: true
      });
      
      if (response.data.success) {
        setPaper(response.data.paper);
        setPosts(response.data.posts);
        setMetadata(response.data.metadata);
      } else {
        setError(response.data.message || 'Failed to fetch today\'s paper');
      }
    } catch (error) {
      console.error('Error fetching today\'s paper:', error);
      if (error.response?.status === 401) {
        setError('Please log in to view your paper');
      } else {
        setError(error.response?.data?.message || 'Failed to fetch today\'s paper');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchTodaysPaper();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchTodaysPaper();
  };

  const handleBack = () => {
    navigate(-1);
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  };

  const formatTime = (dateString) => {
    return new Date(dateString).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const handlePostClick = (postId) => {
    navigate(`/post/${postId}`);
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

  const PostCard = ({ post }) => (
    <motion.div
      variants={cardVariants}
      whileHover={{ y: -2, scale: 1.01 }}
      whileTap={{ scale: 0.98 }}
      onClick={() => handlePostClick(post.id)}
      className="bg-[#111111] border border-gray-800 rounded-2xl p-4 shadow-sm hover:shadow-xl transition-all duration-300 cursor-pointer"
    >
      {/* Post thumbnail */}
      {post.thumbnail && (
        <div className="relative mb-3">
          <img
            src={post.thumbnail}
            alt={post.title}
            className="w-full h-40 object-cover rounded-lg"
          />
        </div>
      )}

      {/* Author info */}
      <div className="flex items-center space-x-3 mb-3">
        <img
          src={post.author?.profilePicture || '/default-avatar.png'}
          alt={post.author?.username}
          className="w-8 h-8 rounded-full"
        />
        <div>
          <span className="text-sm font-medium text-white">{post.author?.username}</span>
          {post.author?.verified && (
            <span className="ml-1 text-blue-400">✓</span>
          )}
        </div>
        <span className="text-xs text-gray-500">{formatTime(post.createdAt)}</span>
      </div>

      {/* Post content */}
      <div className="mb-3">
        {post.title && (
          <h3 className="text-lg font-bold text-white mb-2 line-clamp-2">
            {post.title}
          </h3>
        )}
        {post.description && (
          <p className="text-gray-300 text-sm line-clamp-3">
            {post.description}
          </p>
        )}
      </div>

      {/* Post stats */}
      <div className="flex items-center justify-between text-xs text-gray-400">
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-1">
            <Eye className="w-4 h-4" />
            <span>{post.views || 0}</span>
          </div>
          <div className="flex items-center space-x-1">
            <Heart className="w-4 h-4" />
            <span>{post.likes || 0}</span>
          </div>
          <div className="flex items-center space-x-1">
            <MessageCircle className="w-4 h-4" />
            <span>{post.comments || 0}</span>
          </div>
        </div>
        
        {post.category && (
          <span className="px-2 py-1 bg-gray-800 rounded-full text-xs">
            {post.category}
          </span>
        )}
      </div>
    </motion.div>
  );

  return (
    <div className="min-h-screen mb-8 bg-[#0a0a0a] text-white">
      <div className="max-w-[500px] md:max-w-[500px] mx-auto w-full mt-2 md:w-[95%] max-md:w-[98%]">
        {/* Top Bar */}
        <div className="sticky top-0 z-10 bg-[#0a0a0a]/90 backdrop-blur-md border-b border-gray-800">
          <div className="flex items-center justify-between px-4 py-3">
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleBack}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <ArrowLeft className="w-6 h-6 text-gray-300" />
            </motion.button>
            
            <h1 className="text-xl font-bold text-white">Today's Paper</h1>
            
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleRefresh}
              disabled={refreshing}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <RefreshCw className={`w-5 h-5 text-gray-300 ${refreshing ? 'animate-spin' : ''}`} />
            </motion.button>
          </div>
        </div>

        {/* Paper Header */}
        {paper && !loading && (
          <div className="px-4 py-4 border-b border-gray-800">
            <h2 className="text-2xl font-bold text-white mb-2">{paper.title}</h2>
            {paper.description && (
              <p className="text-gray-400 mb-3">{paper.description}</p>
            )}
            
            <div className="flex items-center justify-between text-sm text-gray-400">
              <div className="flex items-center space-x-4">
                <div className="flex items-center space-x-1">
                  <Calendar className="w-4 h-4" />
                  <span>{metadata?.paperDate ? formatDate(metadata.paperDate) : 'Today'}</span>
                </div>
                <div className="flex items-center space-x-1">
                  <Clock className="w-4 h-4" />
                  <span>{metadata?.deliveryTime}</span>
                </div>
              </div>
              
              <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                !paper.userReadStatus 
                  ? 'bg-blue-900 text-blue-300' 
                  : 'bg-gray-800 text-gray-400'
              }`}>
                {!paper.userReadStatus ? 'Unread' : 'Read'}
              </div>
            </div>

            {paper.isNewlyGenerated && (
              <div className="mt-3 px-3 py-2 bg-green-900/30 border border-green-800 rounded-lg">
                <p className="text-green-300 text-sm">
                  ✨ Fresh paper just generated for you with {posts.length} posts!
                </p>
              </div>
            )}
          </div>
        )}

        {/* Content */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="px-4 py-6"
        >
          {loading ? (
            // Loading skeleton
            <div className="space-y-4">
              {[1, 2, 3].map((index) => (
                <div key={index} className="bg-[#111111] border border-gray-800 rounded-2xl p-4 animate-pulse">
                  <div className="h-40 bg-gray-700 rounded-lg mb-3"></div>
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
            </div>
          ) : !paper ? (
            // No paper state
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-12"
            >
              <Calendar className="w-16 h-16 text-gray-600 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-white mb-2">No paper available</h3>
              <p className="text-gray-400 mb-6">Your paper will be available at the scheduled time</p>
            </motion.div>
          ) : posts.length === 0 ? (
            // Empty posts state
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-12"
            >
              <Calendar className="w-16 h-16 text-gray-600 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-white mb-2">No posts in this paper</h3>
              <p className="text-gray-400">Try refreshing to generate new content</p>
            </motion.div>
          ) : (
            // Posts list
            <div className="space-y-4">
              {posts.map((post, index) => (
                <PostCard key={post.id || index} post={post} />
              ))}
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
};

export default ThePaper;
