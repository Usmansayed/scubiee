import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ArrowLeft, 
  Plus, 
  Search, 
  Users, 
  Globe, 
  Lock, 
  Shield,
  Filter,
  ChevronDown,
  RefreshCw,
  Sparkles
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';

const Communities = () => {
  const navigate = useNavigate();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;
  const cloud = import.meta.env.VITE_CLOUD_URL;

  // State management
  const [communities, setCommunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [showFilterDropdown, setShowFilterDropdown] = useState(false);
  const [activeFilter, setActiveFilter] = useState('all');
  const [sortBy, setSortBy] = useState('popular');

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMorePages, setHasMorePages] = useState(true);
  const [totalCommunities, setTotalCommunities] = useState(0);

  // Filter and sort options
  const filterOptions = [
    { key: 'all', label: 'All Communities', icon: Globe },
    { key: 'public', label: 'Public', icon: Globe },
    { key: 'private', label: 'Private', icon: Lock },
    { key: 'restricted', label: 'Restricted', icon: Shield },
  ];

  const sortOptions = [
    { key: 'popular', label: 'Most Popular' },
    { key: 'newest', label: 'Newest First' },
    { key: 'oldest', label: 'Oldest First' },
    { key: 'name', label: 'Alphabetical' },
  ];

  // Fetch communities
  const fetchCommunities = useCallback(async (page = 1, isRefresh = false) => {
    try {
      if (isRefresh) {
        setRefreshing(true);
      } else if (page === 1) {
        setLoading(true);
      }
      
      setError('');

      const params = {
        page,
        limit: 20,
        sort: sortBy,
        ...(activeFilter !== 'all' && { visibility: activeFilter }),
        ...(searchQuery && { search: searchQuery }),
      };

      const response = await axios.get(`${api}/communities`, {
        params,
        withCredentials: true
      });

      if (response.data.communities) {
        if (page === 1) {
          setCommunities(response.data.communities);
        } else {
          setCommunities(prev => [...prev, ...response.data.communities]);
        }
        
        setTotalCommunities(response.data.pagination.total);
        setHasMorePages(page < response.data.pagination.totalPages);
        setCurrentPage(page);
      } else {
        setError('Failed to fetch communities');
      }
    } catch (error) {
      console.error('Error fetching communities:', error);
      setError(error.response?.data?.error || 'Failed to fetch communities');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [api, activeFilter, sortBy, searchQuery]);

  // Initial load
  useEffect(() => {
    fetchCommunities(1);
  }, [fetchCommunities]);

  // Search debounce
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (searchQuery !== '') {
        fetchCommunities(1);
      } else {
        fetchCommunities(1);
      }
    }, 500);

    return () => clearTimeout(timeoutId);
  }, [searchQuery]);

  // Handlers
  const handleBack = () => {
    navigate(-1);
  };

  const handleRefresh = () => {
    setCurrentPage(1);
    fetchCommunities(1, true);
  };

  const handleCreateCommunity = () => {
    navigate('/create-community');
  };

  const handleFilterChange = (filter) => {
    setActiveFilter(filter);
    setShowFilterDropdown(false);
    setCurrentPage(1);
  };

  const handleSortChange = (sort) => {
    setSortBy(sort);
    setCurrentPage(1);
  };

  const handleCommunityClick = (community) => {
    navigate(`/community/${community.id}`);
  };

  const handleLoadMore = () => {
    if (hasMorePages && !loading) {
      fetchCommunities(currentPage + 1);
    }
  };

  // Get visibility icon and color
  const getVisibilityInfo = (visibility) => {
    switch (visibility) {
      case 'public':
        return { icon: Globe, color: 'text-blue-500', bg: 'bg-blue-black/10' };
      case 'private':
        return { icon: Lock, color: 'text-red-500', bg: 'bg-red-500/10' };
      case 'restricted':
        return { icon: Shield, color: 'text-yellow-500', bg: 'bg-yellow-500/10' };
      default:
        return { icon: Globe, color: 'text-gray-500', bg: 'bg-gray-500/10' };
    }
  };

  // Animation variants
  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: { staggerChildren: 0.1 }
    }
  };

  const cardVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.3, ease: "easeOut" }
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white mb-10">
      <div className="max-w-[500px] md:max-w-[500px] mx-auto w-full mt-2 md:w-[95%] max-md:w-[98%]">
        {/* Header */}
        <div className="sticky top-0 z-20 bg-[#0a0a0a]/90 backdrop-blur-md">
          <div className="flex items-center justify-between px-4 py-3">
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleBack}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <ArrowLeft className="w-6 h-6 text-gray-300" />
            </motion.button>
            
            <div className="flex items-center space-x-3">
              <Sparkles className="w-6 h-6 text-blue-400" />
              <h1 className="text-xl font-bold text-white">Communities</h1>
            </div>
            
            <div className="flex items-center space-x-2">
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleRefresh}
                className="p-2 hover:bg-gray-800 rounded-full transition-colors"
                disabled={refreshing}
              >
                <RefreshCw className={`w-5 h-5 text-gray-300 ${refreshing ? 'animate-spin' : ''}`} />
              </motion.button>
              
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleCreateCommunity}
                className="p-2 bg-blue-500 hover:bg-blue-600 text-white rounded-full transition-colors shadow-lg"
              >
                <Plus className="w-6 h-6" />
              </motion.button>
            </div>
          </div>

          {/* Search Bar */}
          <div className="px-4 pb-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search communities..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-[#111111] border border-gray-800 rounded-2xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
          </div>

          {/* Filters and Sort */}
          <div className="px-4 pb-3">
            <div className="flex items-center justify-between space-x-3">
              {/* Filter Dropdown */}
              <div className="relative">
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={() => setShowFilterDropdown(!showFilterDropdown)}
                  className="flex items-center space-x-2 px-4 py-2 bg-[#111111] border border-gray-800 rounded-xl text-sm font-medium text-gray-300 hover:bg-gray-800 transition-colors"
                >
                  <Filter className="w-4 h-4" />
                  <span>{filterOptions.find(f => f.key === activeFilter)?.label}</span>
                  <ChevronDown className="w-4 h-4" />
                </motion.button>

                <AnimatePresence>
                  {showFilterDropdown && (
                    <motion.div
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      className="absolute top-full left-0 mt-2 w-48 bg-[#111111] border border-gray-800 rounded-xl shadow-xl z-30"
                    >
                      {filterOptions.map((option) => {
                        const IconComponent = option.icon;
                        return (
                          <motion.button
                            key={option.key}
                            whileTap={{ scale: 0.98 }}
                            onClick={() => handleFilterChange(option.key)}
                            className={`w-full flex items-center space-x-3 px-4 py-3 text-left hover:bg-gray-800 transition-colors first:rounded-t-xl last:rounded-b-xl ${
                              activeFilter === option.key ? 'text-blue-400 bg-blue-500/10' : 'text-gray-300'
                            }`}
                          >
                            <IconComponent className="w-4 h-4" />
                            <span className="text-sm font-medium">{option.label}</span>
                          </motion.button>
                        );
                      })}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Sort Options */}
              <select
                value={sortBy}
                onChange={(e) => handleSortChange(e.target.value)}
                className="px-4 py-2 bg-[#111111] border border-gray-800 rounded-xl text-sm font-medium text-gray-300 focus:outline-none focus:border-blue-500 transition-colors"
              >
                {sortOptions.map((option) => (
                  <option key={option.key} value={option.key} className="bg-[#111111]">
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Stats */}
          {totalCommunities > 0 && (
            <div className="px-4 pb-3">
              <p className="text-sm text-gray-400">
                Found {totalCommunities} {totalCommunities === 1 ? 'community' : 'communities'}
              </p>
            </div>
          )}
        </div>

        {/* Content */}
        <div className="px-4 py-6">
          {loading && communities.length === 0 ? (
            // Loading skeleton
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((index) => (
                <div key={index} className="bg-[#111111] border border-gray-800 rounded-2xl p-4 animate-pulse">
                  <div className="flex items-start space-x-4">
                    <div className="w-16 h-16 bg-gray-700 rounded-2xl"></div>
                    <div className="flex-1 space-y-2">
                      <div className="h-5 bg-gray-700 rounded w-3/4"></div>
                      <div className="h-3 bg-gray-700 rounded w-full"></div>
                      <div className="h-3 bg-gray-700 rounded w-2/3"></div>
                      <div className="flex items-center space-x-4 mt-3">
                        <div className="h-4 bg-gray-700 rounded w-16"></div>
                        <div className="h-4 bg-gray-700 rounded w-20"></div>
                      </div>
                    </div>
                  </div>
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
                className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold flex items-center space-x-2 mx-auto"
              >
                <RefreshCw className="w-5 h-5" />
                <span>Try Again</span>
              </motion.button>
            </div>
          ) : communities.length === 0 ? (
            // Empty state
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-12"
            >
              <div className="w-20 h-20 bg-gray-800 rounded-full flex items-center justify-center mx-auto mb-6">
                <Users className="w-10 h-10 text-gray-400" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-2">No Communities Found</h3>
              <p className="text-gray-400 mb-6 max-w-sm mx-auto">
                {searchQuery 
                  ? "No communities match your search. Try different keywords."
                  : "Be the first to create a community and bring people together!"
                }
              </p>
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleCreateCommunity}
                className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-semibold flex items-center space-x-2 mx-auto"
              >
                <Plus className="w-5 h-5" />
                <span>Create Community</span>
              </motion.button>
            </motion.div>
          ) : (
            // Communities list
            <motion.div
              variants={containerVariants}
              initial="hidden"
              animate="visible"
              className="space-y-4"
            >
              {communities.map((community) => {
                const visibilityInfo = getVisibilityInfo(community.visibility);
                const VisibilityIcon = visibilityInfo.icon;
                
                return (
                  <motion.div
                    key={community.id}
                    variants={cardVariants}
                    onClick={() => handleCommunityClick(community)}
                    className="bg-[#111111] border border-gray-800 rounded-2xl p-4 hover:bg-[#161616] transition-all duration-200 cursor-pointer group"
                  >
                    <div className="flex items-start space-x-4">
                      {/* Community Icon */}
                      <div className="relative">
                        <div className="w-[74px] h-[74px] bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center group-hover:scale-105 transition-transform">
                          {community.profile_icon ? (                            <img
                              src={`${cloud}/cloudofscubiee/communityProfile/${community.profile_icon}`}
                              alt={community.name}
                              className="w-full h-full rounded-2xl object-cover"
                            />
                          ) : (
                            <Users className="w-8 h-8 text-white" />
                          )}
                        </div>
                        
                       
                      </div>

                      {/* Community Info */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <h3 className="text-lg font-semibold text-white group-hover:text-blue-400 transition-colors truncate">
                              {community.name}
                            </h3>
                            {community.description && (
                              <p className="text-gray-400 text-sm mt-1 line-clamp-2">
                                {community.description}
                              </p>
                            )}
                          </div>
                        </div>

                        {/* Community Stats */}
                        <div className="flex items-center space-x-4 mt-3">
                          <div className="flex items-center space-x-1 text-gray-400">
                            <Users className="w-4 h-4" />
                            <span className="text-sm font-medium">
                              {community.member_count.toLocaleString()}
                            </span>
                          </div>
                          
                          <div className={`flex items-center space-x-1 ${visibilityInfo.color}`}>
                            <VisibilityIcon className="w-4 h-4" />
                            <span className="text-sm font-medium capitalize">
                              {community.visibility}
                            </span>
                          </div>
                        </div>                        {/* Hot Topics - Responsive Display */}
                        {community.hot_topics && community.hot_topics.length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-3">
                            {/* Desktop: Show 3 tags + more */}
                            <div className="hidden md:flex flex-wrap gap-2">
                              {community.hot_topics.slice(0, 3).map((topic, index) => (
                                <span
                                  key={index}
                                  className="px-2 py-1 bg-blue-500/10 text-blue-400 text-xs rounded-lg"
                                >
                                  #{topic}
                                </span>
                              ))}
                              {community.hot_topics.length > 3 && (
                                <span className="px-2 py-1 bg-gray-800 text-gray-400 text-xs rounded-lg">
                                  +{community.hot_topics.length - 3} more
                                </span>
                              )}
                            </div>
                            
                            {/* Mobile: Show 2 tags + more */}
                            <div className="flex md:hidden flex-wrap gap-2">
                              {community.hot_topics.slice(0, 2).map((topic, index) => (
                                <span
                                  key={index}
                                  className="px-2 py-1 bg-blue-500/10 text-blue-400 text-xs rounded-lg"
                                >
                                  #{topic}
                                </span>
                              ))}
                              {community.hot_topics.length > 2 && (
                                <span className="px-2 py-1 bg-gray-800 text-gray-400 text-xs rounded-lg">
                                  +{community.hot_topics.length - 2} more
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                       
                      </div>
                    </div>
                  </motion.div>
                );
              })}

              {/* Load More Button */}
              {hasMorePages && (
                <div className="text-center pt-6">
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleLoadMore}
                    disabled={loading}
                    className="px-6 py-3 bg-[#111111] hover:bg-gray-800 border border-gray-800 text-white rounded-xl font-medium transition-colors disabled:opacity-50"
                  >
                    {loading ? (
                      <div className="flex items-center space-x-2">
                        <RefreshCw className="w-5 h-5 animate-spin" />
                        <span>Loading...</span>
                      </div>
                    ) : (
                      'Load More Communities'
                    )}
                  </motion.button>
                </div>
              )}
            </motion.div>
          )}
        </div>
      </div>

      {/* Click outside to close dropdown */}
      {showFilterDropdown && (
        <div
          className="fixed inset-0 z-10"
          onClick={() => setShowFilterDropdown(false)}
        />
      )}
    </div>
  );
};

export default Communities;
