import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Sparkles, Brain, Loader2 } from 'lucide-react';
import axios from 'axios';

const CommunitySummary = ({ communityId, postCount }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [summary, setSummary] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState(null);

  const generateSummary = async () => {
    if (summary && !isGenerating) {
      setIsExpanded(!isExpanded);
      return;
    }

    setIsGenerating(true);
    setError(null);
    setIsExpanded(true);

    try {
      const token = localStorage.getItem('accessToken');
      const response = await axios.get(
        `http://localhost:3001/communities/${communityId}/summary`,
        {
          headers: { accessToken: token }
        }
      );

      if (response.data.success) {
        // Simulate AI generation delay for better UX
        await new Promise(resolve => setTimeout(resolve, 1500));
        setSummary(response.data.summary);
      } else {
        setError(response.data.message || 'No posts available');
      }
    } catch (err) {
      setError('Failed to generate summary');
      console.error('Error generating summary:', err);
    } finally {
      setIsGenerating(false);
    }
  };

  // Don't show button if no posts
  if (postCount === 0) {
    return null;
  }

  return (
    <div className="w-full">
      {/* Trigger Button */}
      <motion.button
        onClick={generateSummary}
        className="w-full p-4 bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-lg hover:from-blue-100 hover:to-purple-100 transition-all duration-300 group"
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
      >
        <div className="flex items-center justify-center space-x-3">
          <div className="relative">
            <Brain className="w-5 h-5 text-blue-600" />
            <motion.div
              className="absolute -top-1 -right-1"
              animate={{ rotate: 360 }}
              transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
            >
              <Sparkles className="w-3 h-3 text-purple-500" />
            </motion.div>
          </div>
          <span className="text-blue-700 font-medium group-hover:text-blue-800">
            What's happening in this community?
          </span>
        </div>
      </motion.button>

      {/* Expanded Summary Panel */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="mt-4 p-6 bg-gradient-to-br from-blue-50 via-purple-50 to-pink-50 border border-blue-200 rounded-lg">
              {/* Header */}
              <div className="flex items-center space-x-3 mb-4">
                <div className="flex items-center space-x-2">
                  <Brain className="w-5 h-5 text-blue-600" />
                  <span className="text-blue-700 font-semibold">AI Community Insights</span>
                </div>
                {isGenerating && (
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                  >
                    <Loader2 className="w-4 h-4 text-blue-500" />
                  </motion.div>
                )}
              </div>

              {/* Content */}
              {isGenerating ? (
                <div className="space-y-4">
                  {/* Animated thinking dots */}
                  <div className="flex items-center space-x-2 text-blue-600">
                    <span>Analyzing community discussions</span>
                    <motion.div className="flex space-x-1">
                      {[0, 1, 2].map((i) => (
                        <motion.div
                          key={i}
                          className="w-2 h-2 bg-blue-500 rounded-full"
                          animate={{ scale: [1, 1.5, 1] }}
                          transition={{
                            duration: 1,
                            repeat: Infinity,
                            delay: i * 0.2
                          }}
                        />
                      ))}
                    </motion.div>
                  </div>

                  {/* Shimmer effect for text */}
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <motion.div
                        key={i}
                        className="h-4 bg-gradient-to-r from-blue-200 via-purple-200 to-blue-200 rounded animate-pulse"
                        style={{ width: `${90 - i * 10}%` }}
                        animate={{
                          backgroundPosition: ['0% 50%', '100% 50%', '0% 50%']
                        }}
                        transition={{
                          duration: 2,
                          repeat: Infinity,
                          ease: "linear"
                        }}
                      />
                    ))}
                  </div>
                </div>
              ) : error ? (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-red-600 bg-red-50 p-3 rounded-lg border border-red-200"
                >
                  {error}
                </motion.div>
              ) : summary ? (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.2 }}
                  className="space-y-3"
                >
                  <div className="text-gray-700 leading-relaxed">
                    {summary}
                  </div>
                  <div className="flex items-center justify-between text-xs text-gray-500 pt-2 border-t border-blue-200">
                    <span>Generated by AI • Based on latest {postCount} posts</span>
                    <Sparkles className="w-3 h-3" />
                  </div>
                </motion.div>
              ) : null}

              {/* Close button */}
              {!isGenerating && (
                <motion.button
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.5 }}
                  onClick={() => setIsExpanded(false)}
                  className="mt-4 text-sm text-blue-600 hover:text-blue-800 font-medium"
                >
                  Close
                </motion.button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default CommunitySummary;
