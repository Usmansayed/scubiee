import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, ArrowRight, Plus, Clock, Hash } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';

const CreatePaper = () => {
  const navigate = useNavigate();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;  const [currentStep, setCurrentStep] = useState(1);
  const [paperTitle, setPaperTitle] = useState('');
  const [paperDescription, setPaperDescription] = useState('');
  const [selectedTime, setSelectedTime] = useState('10:00 AM');
  const [selectedPostCount, setSelectedPostCount] = useState(30);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  
  // Time options
  const timeOptions = [
    '6:00 AM', '7:00 AM', '8:00 AM', '9:00 AM', '10:00 AM', '11:00 AM',
    '12:00 PM', '1:00 PM', '2:00 PM', '3:00 PM', '4:00 PM', '5:00 PM',
    '6:00 PM', '7:00 PM', '8:00 PM', '9:00 PM', '10:00 PM', '11:00 PM'
  ];
  
  // Post count options
  const postCountOptions = [10, 20, 30, 50, 100];
  
  const textareaRef = useRef(null);
  const timeScrollRef = useRef(null);
  const postScrollRef = useRef(null);

  useEffect(() => {
    if (currentStep === 1 && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [currentStep]);

  const handleBack = () => {
    if (currentStep === 1) {
      navigate(-1);
    } else {
      setCurrentStep(1);
    }
  };
  const handleNext = () => {
    if (currentStep === 1) {
      // Check if description exceeds limit and show error
      if (paperDescription.length > 4000) {
        alert('Description must be 4000 characters or less. Please shorten your text.');
        return;
      }
      setCurrentStep(2);
    }
  };
  const handleCreate = async () => {
    if (!paperTitle.trim() || !paperDescription.trim()) {
      setError('Please fill in all required fields');
      return;
    }

    if (!userData?.id) {
      setError('You must be logged in to create a paper');
      return;
    }

    setIsCreating(true);
    setError('');    try {
      const response = await axios.post(`${api}/papers`, {
        title: paperTitle.trim(),
        description: paperDescription.trim(),
        authorId: userData.id,
        deliveryTime: selectedTime,
        postCount: selectedPostCount
      }, {
        withCredentials: true
      });

      if (response.data.success) {
        setSuccess(true);
        console.log('Paper created successfully:', response.data.paper);
        
        // Show success message briefly before navigating
        setTimeout(() => {
          navigate('/my-papers', { replace: true }); // Use replace to avoid back button issues
        }, 1500);
      } else {
        setError(response.data.message || 'Failed to create paper');
      }
    } catch (error) {
      console.error('Error creating paper:', error);
      setError(error.response?.data?.message || 'Failed to create paper. Please try again.');
    } finally {
      setIsCreating(false);
    }
  };const ScrollPicker = ({ options, selected, onSelect, scrollRef, type }) => {
    const [isScrolling, setIsScrolling] = useState(false);
    const [isTouching, setIsTouching] = useState(false);
    const scrollTimeoutRef = useRef(null);
    const lastScrollTimeRef = useRef(0);
    const accumulatedDeltaRef = useRef(0);
    const touchStartRef = useRef(null);
    const userInitiatedScrollRef = useRef(false);
    const itemHeight = 40;
    const visibleItems = 3;
    const containerHeight = itemHeight * visibleItems;
    const scrollThreshold = 30;

    // Auto-scroll to selected item when selection changes externally
    useEffect(() => {
      if (userInitiatedScrollRef.current) {
        userInitiatedScrollRef.current = false;
        return;
      }

      const container = scrollRef.current;
      if (!container) return;

      const selectedIndex = options.indexOf(selected);
      const targetScroll = selectedIndex * itemHeight;
      
      container.scrollTo({ top: targetScroll, behavior: 'smooth' });
    }, [selected, options]);

    // Mouse wheel handling for desktop
    useEffect(() => {
      const container = scrollRef.current;
      if (!container) return;

      const handleWheel = (e) => {
        // Don't interfere with touch scrolling
        if (isTouching) return;
        
        e.preventDefault();
        
        const now = Date.now();
        const timeDiff = now - lastScrollTimeRef.current;
        
        if (timeDiff > 200) {
          accumulatedDeltaRef.current = 0;
        }
        
        lastScrollTimeRef.current = now;
        accumulatedDeltaRef.current += e.deltaY;
        
        if (Math.abs(accumulatedDeltaRef.current) >= scrollThreshold) {
          const currentIndex = options.indexOf(selected);
          let newIndex;
          
          if (accumulatedDeltaRef.current > 0) {
            newIndex = Math.min(currentIndex + 1, options.length - 1);
          } else {
            newIndex = Math.max(currentIndex - 1, 0);
          }
          
          if (newIndex !== currentIndex) {
            userInitiatedScrollRef.current = true;
            onSelect(options[newIndex]);
          }
          
          accumulatedDeltaRef.current = 0;
        }
      };

      container.addEventListener('wheel', handleWheel, { passive: false });
      
      return () => {
        container.removeEventListener('wheel', handleWheel);
      };
    }, [options, selected, onSelect, isTouching]);

    // Touch handling
    const handleTouchStart = (e) => {
      setIsTouching(true);
      touchStartRef.current = e.touches[0].clientY;
      setIsScrolling(false);
      
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };

    const handleTouchEnd = () => {
      setIsTouching(false);
      touchStartRef.current = null;
      
      // Snap to nearest item after touch ends
      const container = scrollRef.current;
      if (!container) return;

      scrollTimeoutRef.current = setTimeout(() => {
        const scrollTop = container.scrollTop;
        const nearestIndex = Math.round(scrollTop / itemHeight);
        const clampedIndex = Math.max(0, Math.min(nearestIndex, options.length - 1));
        const snapScroll = clampedIndex * itemHeight;
        
        // Update selection if it changed
        const newSelected = options[clampedIndex];
        if (newSelected !== selected) {
          userInitiatedScrollRef.current = true;
          onSelect(newSelected);
        }
        
        // Snap scroll position
        container.scrollTo({ top: snapScroll, behavior: 'smooth' });
        setIsScrolling(false);
      }, 100);
    };

    const handleTouchScroll = (e) => {
      if (!isTouching) return;
      
      setIsScrolling(true);
      
      // Clear any pending snap timeout while actively scrolling
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
      
      // Throttled selection update during scroll
      const container = e.target;
      const scrollTop = container.scrollTop;
      const nearestIndex = Math.round(scrollTop / itemHeight);
      
      if (nearestIndex >= 0 && nearestIndex < options.length) {
        const newSelected = options[nearestIndex];
        if (newSelected !== selected) {
          userInitiatedScrollRef.current = true;
          onSelect(newSelected);
        }
      }
    };

    const handleOptionClick = (option) => {
      userInitiatedScrollRef.current = true;
      onSelect(option);
      
      const container = scrollRef.current;
      if (container) {
        const index = options.indexOf(option);
        const targetScroll = index * itemHeight;
        container.scrollTo({ top: targetScroll, behavior: 'smooth' });
      }
    };    return (
      <div className="relative h-full overflow-hidden">
        {/* Fixed selection indicator */}
        <div 
          className="absolute inset-x-0 bg-blue-900/30 border-2 border-gray-600 rounded-xl z-10 pointer-events-none"
          style={{
            height: `${itemHeight}px`,
            top: `50%`,
            transform: 'translateY(-50%)'
          }}
        ></div>
        
        {/* Scrollable container */}
        <div
          ref={scrollRef}
          onScroll={handleTouchScroll}
          onTouchStart={handleTouchStart}
          onTouchEnd={handleTouchEnd}
          className="h-full overflow-y-scroll scrollbar-hide"
          style={{ 
            scrollbarWidth: 'none', 
            msOverflowStyle: 'none',
            scrollSnapType: 'y mandatory',
            WebkitOverflowScrolling: 'touch'
          }}
        >
          {/* Top padding to center first item */}
          <div style={{ height: `calc(50% - ${itemHeight / 2}px)` }}></div>
          
          {options.map((option, index) => (
            <motion.div
              key={option}
              className={`flex items-center justify-center font-medium cursor-pointer transition-all duration-200 ${
                option === selected 
                  ? 'text-blue-400 scale-105' 
                  : 'text-gray-400 hover:text-gray-300'
              }`}
              style={{ 
                height: `${itemHeight}px`,
                scrollSnapAlign: 'center'
              }}
              whileTap={{ scale: 0.95 }}
              onClick={() => handleOptionClick(option)}
            >
              <div className="flex items-center space-x-2">
                {type === 'time' && <Clock className="w-4 h-4" />}
                {type === 'posts' && <Hash className="w-4 h-4" />}
                <span className="text-sm">{option}{type === 'posts' ? ' Posts' : ''}</span>
              </div>
            </motion.div>
          ))}
          
          {/* Bottom padding to center last item */}
          <div style={{ height: `calc(50% - ${itemHeight / 2}px)` }}></div>
        </div>

        {/* Gradient overlays for smooth edges */}
        <div className="absolute top-0 left-0 right-0 h-8 bg-gradient-to-b from-[#0f0f0f] to-transparent pointer-events-none z-5"></div>
        <div className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-[#0f0f0f] to-transparent pointer-events-none z-5"></div>
      </div>
    );
  };

  const stepVariants = {
    hidden: { opacity: 0, x: 50 },
    visible: { 
      opacity: 1, 
      x: 0,
      transition: { duration: 0.3, ease: "easeOut" }
    },
    exit: { 
      opacity: 0, 
      x: -50,
      transition: { duration: 0.3, ease: "easeIn" }
    }
  };
  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white mb-10">
      <div className="max-w-[580px] md:max-w-[500px] mx-auto w-full md:w-[95%] max-md:w-[99%]">
        {/* Top Bar */}
        <div className="sticky top-0 z-20 bg-[#0a0a0a]/90 backdrop-blur-md  border-gray-800">
          <div className="flex items-center justify-between px-4 pt-4">
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleBack}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <ArrowLeft className="w-6 h-6 text-gray-300" />
            </motion.button>
            
            <h1 className="text-xl font-bold text-white">
              {currentStep === 1 ? 'Describe Your Paper' : 'Schedule & Settings'}
            </h1>
            
            <div className="w-10 h-10 flex items-center justify-center">
              <div className="flex space-x-1">
                <div className={`w-2 h-2 rounded-full ${currentStep === 1 ? 'bg-blue-500' : 'bg-gray-600'}`}></div>
                <div className={`w-2 h-2 rounded-full ${currentStep === 2 ? 'bg-blue-500' : 'bg-gray-600'}`}></div>
              </div>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 px-4 py-4 ">
        <AnimatePresence mode="wait">          {currentStep === 1 && (
            <motion.div
              key="step1"
              variants={stepVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="max-w-2xl mx-auto"
            >
              <div className="bg-[#111111] border border-gray-800 rounded-3xl p-6 max-md:p-4 shadow-sm">                <div className="mb-6">
                  <h2 className="text-[21px] font-semibold text-white mb-2">
                    What would you like in your digital paper?
                  </h2>
                  <p className="text-gray-400 font-sans">
                    Give your paper a title and describe your preferences - topics, regions, news sources, or anything specific you'd like to see.
                  </p>
                </div>

                <div className="space-y-4">                  {/* Title Input */}
                  <div className="relative">
                    <input
                      type="text"
                      value={paperTitle}
                      onChange={(e) => {
                        const value = e.target.value;
                        if (value.length <= 35) {
                          setPaperTitle(value);
                        }
                      }}
                      placeholder="My Digital Paper Title"
                      className="w-full p-4 text-[16px] bg-[#0f0f0f] border-2 border-gray-700 text-white placeholder-gray-500 rounded-2xl focus:border-blue-500/90 focus:outline-none transition-colors"
                      style={{ lineHeight: '1.6' }}
                    />
                    <div className="absolute bottom-4 right-4 text-xs text-gray-500">
                      {paperTitle.length}/35
                    </div>
                  </div>

                  {/* Description Textarea */}
                  <div className="relative">
                    <textarea
                      ref={textareaRef}
                      value={paperDescription}
                      onChange={(e) => setPaperDescription(e.target.value)}
                      placeholder="e.g., Latest tech news from Silicon Valley, startup funding rounds, AI developments, and cryptocurrency updates. Focus on breaking news and analysis from reputable sources like TechCrunch, Wired, and The Verge..."
                      className="w-full h-64 p-4 text-md bg-[#0f0f0f] border-2 border-gray-700 text-white placeholder-gray-500 rounded-2xl focus:border-blue-500/90 focus:outline-none resize-none transition-colors"
                      style={{ lineHeight: '1.6' }}
                    />
                    <div className="absolute bottom-4 right-4 text-sm text-gray-500">
                      {paperDescription.length} characters
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex justify-end">                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleNext}
                    disabled={!paperTitle.trim() || !paperDescription.trim()}
                    className={`px-6 py-2 rounded-2xl font-semibold text-lg flex items-center space-x-2 transition-all ${
                      paperTitle.trim() && paperDescription.trim()
                        ? 'bg-blue-500 hover:bg-blue-700 text-white shadow-lg'
                        : 'bg-gray-700 text-gray-500 cursor-not-allowed'
                    }`}
                  >
                    <span>Next</span>
                    <ArrowRight className="w-5 h-5" />
                  </motion.button>
                </div>
              </div>
            </motion.div>
          )}          {currentStep === 2 && (
            <motion.div
              key="step2"
              variants={stepVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="max-w-4xl mx-auto"
            >
              <div className="bg-[#111111] border border-gray-800 rounded-3xl p-4 shadow-sm">
                <div className="mb-8 text-center">
                  <h2 className="text-2xl font-bold text-white mb-2">
                    When and how much?
                  </h2>
                  <p className="text-gray-400 font-sans">
                    Choose your preferred delivery time and number of posts
                  </p>
                </div>                <div className="grid md:grid-cols-2 gap-4 mb-6">
                  {/* Time Picker */}
                  <div className="bg-[#0f0f0f] h-[200px] md:h-[260px] border border-gray-700 rounded-2xl p-4">
                    <h3 className="text-lg font-semibold text-white mb-3 text-center">
                      Delivery Time
                    </h3>
                    <div className="h-[calc(100%-2.5rem)]">
                      <ScrollPicker
                        options={timeOptions}
                        selected={selectedTime}
                        onSelect={setSelectedTime}
                        scrollRef={timeScrollRef}
                        type="time"
                      />
                    </div>
                  </div>

                  {/* Post Count Picker */}
                  <div className="bg-[#0f0f0f] h-[200px] md:h-[260px] border border-gray-700 rounded-2xl p-4">
                    <h3 className="text-lg font-semibold text-white mb-2 text-center">
                      Number of Posts
                    </h3>
                    <div className="h-[calc(100%-2.5rem)]">
                      <ScrollPicker
                        options={postCountOptions}
                        selected={selectedPostCount}
                        onSelect={setSelectedPostCount}
                        scrollRef={postScrollRef}
                        type="posts"
                      />
                    </div>
                  </div>
                </div>

                {/* Summary */}
                <div className=" border border-gray-700 rounded-2xl p-4 mb-5">
                  <h3 className="text-lg font-semibold text-white mb-2">Summary</h3>                  <div className="space-y-2 text-gray-300 font-sansd">
                    <p><strong>Title:</strong> {paperTitle || 'Untitled Paper'}</p>
                    <p><strong>Delivery:</strong> Daily at {selectedTime}</p>
                    <p><strong>Posts:</strong> {selectedPostCount} articles per paper</p>
                    <p><strong>Content:</strong> {paperDescription.slice(0, 100)}...</p>
                  </div>
                </div>                <div className="flex justify-end">
                  {error && (
                    <div className="mb-4 p-3 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">
                      {error}
                    </div>
                  )}
                  
                  {success && (
                    <div className="mb-4 p-3 bg-green-500/20 border border-green-500/30 rounded-lg text-green-400 text-sm">
                      Paper created successfully! Redirecting...
                    </div>
                  )}
                  
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleCreate}
                    disabled={isCreating || success}
                    className={`px-6 py-2 rounded-2xl font-semibold text-lg flex items-center space-x-2 shadow-lg transition-colors ${
                      isCreating || success
                        ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                        : 'bg-blue-600 hover:bg-blue-700 text-white'
                    }`}
                  >
                    <span>{isCreating ? 'Creating...' : success ? 'Created!' : 'Create'}</span>
                    {isCreating ? (
                      <div className="w-5 h-5 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Plus className="w-5 h-5" />
                    )}
                  </motion.button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      </div>
    </div>
  );
};

export default CreatePaper;