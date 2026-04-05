import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, Clock, User, Eye, Heart, MessageCircle, Share, Bookmark, ExternalLink } from 'lucide-react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';

const PaperView = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;
  
  // Get data from location state
  const { paperData, posts } = location.state || {};
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleBack = () => {
    navigate(-1);
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const handlePostClick = (postId) => {
    navigate(`/viewpost/${postId}`);
  };

  if (!paperData) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-bold mb-4">Paper data not found</h2>
          <button 
            onClick={handleBack}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-[500px] md:max-w-[500px] mx-auto w-full mt-2 md:w-[95%] max-md:w-[98%]">
        {/* Header */}
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
            
            <div className="w-10"></div> {/* Spacer for center alignment */}
          </div>
        </div>

        {/* Paper Info */}
        <div className="px-4 py-6">
          <div className="bg-[#111111] border border-gray-800 rounded-2xl p-6 mb-6">
            <h2 className="text-2xl font-bold text-white mb-2">{paperData.paper.title}</h2>
            <p className="text-gray-400 mb-4">{paperData.paper.description}</p>
            
            <div className="flex items-center justify-between text-sm text-gray-400">
              <div className="flex items-center space-x-4">
                <div className="flex items-center space-x-1">
                  <Clock className="w-4 h-4" />
                  <span>Delivered at {paperData.metadata.deliveryTime}</span>
                </div>
                <div className="flex items-center space-x-1">
                  <Eye className="w-4 h-4" />
                  <span>{posts?.length || 0} Posts</span>
                </div>
              </div>
              <div className="text-blue-400 font-medium">
                {formatDate(paperData.metadata.paperDate)}
              </div>
            </div>
          </div>

          {/* Posts List */}
          <div className="space-y-4">
            <h3 className="text-lg font-semibold text-white mb-4">
              Featured Posts ({posts?.length || 0})
            </h3>
            
            {posts && posts.length > 0 ? (
              posts.map((post, index) => (
                <motion.div
                  key={post.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.1 }}
                  whileHover={{ y: -2 }}
                  onClick={() => handlePostClick(post.id)}
                  className="bg-[#111111] border border-gray-800 rounded-2xl p-4 cursor-pointer hover:bg-[#1a1a1a] transition-all duration-300"
                >
                  {/* Post thumbnail if available */}
                  {post.thumbnail && (
                    <div className="w-full h-48 mb-4 rounded-xl overflow-hidden">
                      <img 
                        src={post.thumbnail} 
                        alt={post.title}
                        className="w-full h-full object-cover"
                      />
                    </div>
                  )}
                  
                  {/* Post content */}
                  <div className="flex items-start space-x-3">
                    <img
                      src={post.author.profilePicture || '/default-avatar.png'}
                      alt={post.author.username}
                      className="w-10 h-10 rounded-full"
                    />
                    
                    <div className="flex-1">
                      <div className="flex items-center space-x-2 mb-2">
                        <span className="font-semibold text-white">{post.author.username}</span>
                        {post.author.verified && (
                          <div className="w-4 h-4 bg-blue-500 rounded-full flex items-center justify-center">
                            <span className="text-white text-xs">✓</span>
                          </div>
                        )}
                        <span className="text-gray-500 text-sm">
                          {formatDate(post.createdAt)}
                        </span>
                      </div>
                      
                      {post.title && (
                        <h4 className="text-white font-semibold mb-2 line-clamp-2">
                          {post.title}
                        </h4>
                      )}
                      
                      <p className="text-gray-300 text-sm line-clamp-3 mb-3">
                        {post.description || post.content}
                      </p>
                      
                      {/* Post stats */}
                      <div className="flex items-center justify-between text-gray-400 text-sm">
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
                        
                        <ExternalLink className="w-4 h-4 text-blue-400" />
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))
            ) : (
              <div className="text-center py-12">
                <div className="text-gray-400 mb-4">No posts available in this paper</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default PaperView;
