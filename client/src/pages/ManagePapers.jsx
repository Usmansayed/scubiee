import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, Plus, Clock, FileText, MoreVertical, X, Trash2, Pause, Play } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { createPortal } from 'react-dom';
import axios from 'axios';

// Portal component for modals
const Portal = ({ children }) => {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return () => setMounted(false);
  }, []);

  return mounted && typeof document !== 'undefined' ? createPortal(children, document.body) : null;
};

const ManagePapers = () => {
  const navigate = useNavigate();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;
  
  // State for papers and UI
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Modal states
  const [showActionModal, setShowActionModal] = useState(false);
  const [selectedPaper, setSelectedPaper] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  
  // Fetch user's created papers from Papers table
  const fetchUserPapers = async () => {
    try {
      setError('');
      setLoading(true);

      const response = await axios.get(`${api}/papers/my-papers`, {
        withCredentials: true
      });
      
      if (response.data.success) {
        setPapers(response.data.papers || []);
      } else {
        setError('Failed to fetch papers');
      }
    } catch (error) {
      console.error('Error fetching papers:', error);
      setError(error.response?.data?.message || 'Failed to fetch papers');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    fetchUserPapers();
  }, []);

  // Close modal on scroll or click outside
  useEffect(() => {
    if (!showActionModal) return;

    const handleScroll = () => {
      handleCloseModal();
    };

    const handleClickOutside = (event) => {
      // Check if click is outside the modal content
      if (event.target.classList.contains('modal-backdrop')) {
        handleCloseModal();
      }
    };

    // Add event listeners
    window.addEventListener('scroll', handleScroll, true);
    document.addEventListener('mousedown', handleClickOutside);

    // Cleanup
    return () => {
      window.removeEventListener('scroll', handleScroll, true);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showActionModal]);

  // Helper functions
  const handleBack = () => {
    navigate(-1);
  };

  const handleCreatePaper = () => {
    navigate('/create-paper');
  };

  const handleMoreClick = (paper, e) => {
    e.stopPropagation();
    setSelectedPaper(paper);
    setShowActionModal(true);
  };

  const handleCloseModal = () => {
    setShowActionModal(false);
    setSelectedPaper(null);
    setActionLoading(false);
  };

  // Action handlers
  const handleDeletePaper = async () => {
    if (!selectedPaper) return;
    
    try {
      setActionLoading(true);
      
      const response = await axios.delete(`${api}/papers/${selectedPaper.id}`, {
        withCredentials: true
      });
      
      if (response.data.success) {
        // Remove paper from local state
        setPapers(papers.filter(p => p.id !== selectedPaper.id));
        handleCloseModal();
      }
    } catch (error) {
      console.error('Error deleting paper:', error);
      setError('Failed to delete paper');
    } finally {
      setActionLoading(false);
    }
  };

  const handleToggleStatus = async () => {
    if (!selectedPaper) return;
    
    try {
      setActionLoading(true);
      
      const newStatus = selectedPaper.status === 'active' ? 'paused' : 'active';
      
      const response = await axios.patch(`${api}/papers/${selectedPaper.id}/status`, {
        status: newStatus
      }, {
        withCredentials: true
      });
      
      if (response.data.success) {
        // Update paper status in local state
        setPapers(papers.map(p => 
          p.id === selectedPaper.id 
            ? { ...p, status: newStatus }
            : p
        ));
        handleCloseModal();
      }
    } catch (error) {
      console.error('Error updating paper status:', error);
      setError('Failed to update paper status');
    } finally {
      setActionLoading(false);
    }
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  // Animation variants
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
      <div className="max-w-[500px] md:max-w-[500px] mx-auto w-full mt-2 md:w-[95%] max-md:w-[98%]">
        {/* Top Bar */}
        <div className="sticky top-0 z-10 bg-[#0a0a0a]/90 backdrop-blur-md">
          <div className="flex items-center justify-between px-4 py-3">
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleBack}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <ArrowLeft className="w-6 h-6 text-gray-300" />
            </motion.button>
            
            <h1 className="text-xl font-bold text-white">Manage Papers</h1>
            
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleCreatePaper}
              className="p-2 bg-blue-500 hover:bg-blue-600 text-white rounded-full transition-colors shadow-lg"
            >
              <Plus className="w-6 h-6" />
            </motion.button>
          </div>
        </div>

        {/* Content */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="px-4 py-6 space-y-4"
          
        >
          {loading ? (
            // Loading skeleton
            <div className="space-y-4">
              {[1, 2, 3].map((index) => (
                <div key={index} className="bg-[#111111] border border-gray-800 rounded-2xl p-6 animate-pulse">
                  <div className="h-6 bg-gray-700 rounded mb-3 w-3/4"></div>
                  <div className="h-4 bg-gray-700 rounded mb-2"></div>
                  <div className="h-4 bg-gray-700 rounded w-1/2"></div>
                </div>
              ))}
            </div>
          ) : error ? (
            // Error state
            <div className="text-center py-12">
              <div className="text-red-400 mb-4">{error}</div>
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={fetchUserPapers}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg"
              >
                Try Again
              </motion.button>
            </div>
          ) : papers.length === 0 ? (
            // Empty state
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-center py-12"
            >
              <FileText className="w-16 h-16 text-gray-600 mx-auto mb-4" />
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
            </motion.div>
          ) : (
            // Papers list
            papers.map((paper) => (
              <motion.div
                key={paper.id}
                variants={cardVariants}
                whileHover={{ y: -2, scale: 1.01 }}
                whileTap={{ scale: 0.98 }}
                className="relative bg-[#111111] border border-gray-800 rounded-2xl p-6 shadow-sm hover:shadow-xl transition-all duration-300 cursor-pointer"
 onClick={(e) => handleMoreClick(paper, e)}              >
                {/* More options button */}
               

                {/* Paper Content */}
                <div className="pr-8">
                  <h3 className="text-lg font-bold text-white mb-2 line-clamp-2">
                    {paper.title}
                  </h3>
                  
                  {paper.description && (
                    <p className="text-gray-400 text-sm line-clamp-3 mb-4">
                      {paper.description}
                    </p>
                  )}

                  {/* Paper Info */}
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

                    {/* Status Badge */}
                    <div className={`px-3 py-1 rounded-full text-xs font-medium ${
                      paper.status === 'active' 
                        ? 'bg-green-500/20 text-green-400 border border-green-500/30' 
                        : 'bg-gray-500/20 text-gray-400 border border-gray-500/30'
                    }`}>
                      {paper.status === 'active' ? 'Active' : 'Inactive'}
                    </div>
                  </div>

                  {/* Creation Date */}
                  <div className="text-xs text-gray-500 mt-2">
                    Created: {formatDate(paper.createdAt)}
                  </div>
                </div>

                {/* Subtle gradient overlay for visual appeal */}
                <div className="absolute inset-0 bg-gradient-to-r from-transparent to-blue-900/5 rounded-2xl pointer-events-none"></div>
              </motion.div>
            ))
          )}
        </motion.div>
      </div>      {/* Action Modal */}
      {showActionModal && selectedPaper && (
        <Portal>
          <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 modal-backdrop">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
              className="bg-white dark:bg-[#0e0e0e] border-gray-900 border-[1px] rounded-3xl shadow-2xl w-full max-w-sm overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="px-6 pt-6 pb-4">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Paper Actions</h3>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">Choose an action for this paper</p>
                  </div>
                  <button
                    onClick={handleCloseModal}
                    className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-full transition-colors"
                  >
                    <X className="w-5 h-5 text-gray-500 dark:text-gray-400" />
                  </button>
                </div>
              </div>

              {/* Paper Info */}
              <div className="px-6 pb-4">
                <div className="bg-gray-50 dark:bg-[#111] rounded-2xl p-4">
                  <h4 className="font-medium text-gray-900 dark:text-white text-sm">{selectedPaper.title}</h4>
                  <div className="flex items-center mt-2">
                    <div className={`w-2 h-2 rounded-full mr-2 ${
                      selectedPaper.status === 'active' ? 'bg-green-500' : 'bg-gray-400'
                    }`}></div>
                    <p className="text-xs text-gray-600 dark:text-gray-400">
                      {selectedPaper.status === 'active' ? 'Active' : 'Inactive'}
                    </p>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="px-6 pb-6 space-y-3">
                {/* Toggle Status Button */}
                <motion.button
                  whileTap={{ scale: 0.98 }}
                  onClick={handleToggleStatus}
                  disabled={actionLoading}
                  className="w-full p-4 bg-white dark:bg-[#111]  hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed border border-gray-200 dark:border-gray-800 rounded-2xl text-gray-900 dark:text-white flex items-center justify-center space-x-3 transition-all duration-200 shadow-sm hover:shadow-md"
                >
                  {selectedPaper.status === 'active' ? (
                    <>
                      <Pause className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                      <span className="font-medium">Deactivate Paper</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-5 h-5 text-gray-600 dark:text-gray-400" />
                      <span className="font-medium">Activate Paper</span>
                    </>
                  )}
                </motion.button>

                {/* Delete Button */}
                <motion.button
                  whileTap={{ scale: 0.98 }}
                  onClick={handleDeletePaper}
                  disabled={actionLoading}
                  className="w-full p-4 bg-white dark:bg-[#111] border-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed border border-gray-200 dark:border-gray-800 rounded-2xl text-gray-900 dark:text-white flex items-center justify-center space-x-3 transition-all duration-200 shadow-sm hover:shadow-md"
                >
                  <Trash2 className="w-5 h-5" />
                  <span className="font-medium">Delete Paper</span>
                </motion.button>

                {/* Cancel Button */}
                <motion.button
                  whileTap={{ scale: 0.98 }}
                  onClick={handleCloseModal}
                  disabled={actionLoading}
                  className="w-full p-4 bg-gray-100 hover:bg-gray-200 dark:bg-[#111]  dark:hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed rounded-2xl text-gray-700 dark:text-gray-300 transition-all duration-200 shadow-sm hover:shadow-md"
                >
                  <span className="font-medium">Cancel</span>
                </motion.button>
              </div>

              {/* Loading Indicator */}
              {actionLoading && (
                <div className="absolute inset-0 bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm flex items-center justify-center rounded-3xl">
                  <div className="text-center">
                    <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-blue-500 border-r-transparent"></div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-3 font-medium">Processing...</p>
                  </div>
                </div>
              )}
            </motion.div>
          </div>
        </Portal>
      )}
    </div>
  );
};

export default ManagePapers;