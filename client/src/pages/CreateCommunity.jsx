import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  ArrowLeft, 
  ArrowRight, 
  Upload, 
  Camera,
  Users,
  Lock,
  Shield,
  Search,
  X,
  Check,
  Image as ImageIcon,
  Sparkles
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';

const CreateCommunity = () => {
  const navigate = useNavigate();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;

  // Step management
  const [currentStep, setCurrentStep] = useState(1);
  const totalSteps = 3;
  // Form data
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    hot_topics: [],
    post_access_type: 'everyone', // 'everyone', 'creator_only', 'selected_users'
    post_access_users: [],
    profile_icon: null,
    banner_url: null
  });

  // UI states
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [newTopic, setNewTopic] = useState('');
  const [userSearchQuery, setUserSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);

  // File upload states
  const [profileIconPreview, setProfileIconPreview] = useState('');
  const [bannerPreview, setBannerPreview] = useState('');
  const [uploadingIcon, setUploadingIcon] = useState(false);
  const [uploadingBanner, setUploadingBanner] = useState(false);
  // Refs
  const nameInputRef = useRef(null);
  const descriptionRef = useRef(null);
  const profileIconRef = useRef(null);
  const bannerRef = useRef(null);

  // Post access options
  const postAccessOptions = [
    {
      key: 'everyone',
      label: 'Everyone',
      description: 'All community members can create posts',
      icon: Users
    },
    {
      key: 'creator_only',
      label: 'Creator Only',
      description: 'Only you can create posts in this community',
      icon: Lock
    },
    {
      key: 'selected_users',
      label: 'Selected Users',
      description: 'Choose specific users who can create posts',
      icon: Shield
    }
  ];

  // Focus management
  useEffect(() => {
    if (currentStep === 1 && nameInputRef.current) {
      nameInputRef.current.focus();
    }
  }, [currentStep]);

  // User search with debounce
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (userSearchQuery.length >= 2 && formData.post_access_type === 'selected_users') {
        searchUsers();
      } else {
        setSearchResults([]);
      }
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [userSearchQuery, formData.post_access_type]);
  // Search users function
  const searchUsers = async () => {
    try {
      setIsSearching(true);
      const response = await axios.get(`${api}/user/search`, {
        params: { q: userSearchQuery, limit: 10 },
        withCredentials: true
      });
      
      if (response.data.users) {
        // Filter out already selected users
        const filteredUsers = response.data.users.filter(
          user => !formData.post_access_users.some(selected => selected.id === user.id)
        );
        setSearchResults(filteredUsers);
      }
    } catch (error) {
      console.error('Error searching users:', error);
    } finally {
      setIsSearching(false);
    }
  };

  // Handlers
  const handleBack = () => {
    if (currentStep === 1) {
      navigate(-1);
    } else {
      setCurrentStep(prev => prev - 1);
    }
  };

  const handleNext = () => {
    if (validateCurrentStep()) {
      setCurrentStep(prev => prev + 1);
    }
  };

  const validateCurrentStep = () => {
    setError('');
    
    switch (currentStep) {
      case 1:
        if (!formData.name.trim()) {
          setError('Community name is required');
          return false;
        }
        if (formData.name.length < 3) {
          setError('Community name must be at least 3 characters');
          return false;
        }
        if (formData.name.length > 50) {
          setError('Community name must be 50 characters or less');
          return false;
        }
        if (!formData.description.trim()) {
          setError('Community description is required');
          return false;
        }
        if (formData.description.length > 500) {
          setError('Description must be 500 characters or less');
          return false;
        }
        return true;
      
      case 2:
        return true; // Images are optional
      
      case 3:
        if (formData.post_access_type === 'selected_users' && formData.post_access_users.length === 0) {
          setError('Please select at least one user who can post');
          return false;
        }
        return true;
      
      default:
        return true;
    }
  };

  const handleInputChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
    if (error) setError('');
  };

  const handleTopicAdd = () => {
    if (newTopic.trim() && formData.hot_topics.length < 10) {
      const topic = newTopic.trim().toLowerCase().replace(/[^a-z0-9]/g, '');
      if (topic && !formData.hot_topics.includes(topic)) {
        setFormData(prev => ({
          ...prev,
          hot_topics: [...prev.hot_topics, topic]
        }));
      }
      setNewTopic('');
    }
  };

  const handleTopicRemove = (topic) => {
    setFormData(prev => ({
      ...prev,
      hot_topics: prev.hot_topics.filter(t => t !== topic)
    }));
  };

  const handleUserSelect = (user) => {
    setFormData(prev => ({
      ...prev,
      post_access_users: [...prev.post_access_users, user]
    }));
    setUserSearchQuery('');
    setSearchResults([]);
  };

  const handleUserRemove = (userId) => {
    setFormData(prev => ({
      ...prev,
      post_access_users: prev.post_access_users.filter(user => user.id !== userId)
    }));
  };

  // File upload handlers
  const handleFileUpload = async (file, type) => {
    if (!file) return;

    const isIcon = type === 'icon';
    const setUploading = isIcon ? setUploadingIcon : setUploadingBanner;
    const setPreview = isIcon ? setProfileIconPreview : setBannerPreview;
    
    try {
      setUploading(true);
      
      // Create preview
      const reader = new FileReader();
      reader.onload = (e) => setPreview(e.target.result);
      reader.readAsDataURL(file);
      
      // Upload file
      const formDataUpload = new FormData();
      formDataUpload.append('file', file);      const response = await axios.post(`${api}/upload/${isIcon ? 'community-icon' : 'communityBanner'}`, formDataUpload, {
        headers: { 'Content-Type': 'multipart/form-data' },
        withCredentials: true
      });
        if (response.data.fileName) {
        handleInputChange(isIcon ? 'profile_icon' : 'banner_url', response.data.fileName);
      }
    } catch (error) {
      console.error(`Error uploading ${type}:`, error);
      setError(`Failed to upload ${type}. Please try again.`);
      setPreview('');
    } finally {
      setUploading(false);
    }
  };

  const handleCreate = async () => {
    if (!validateCurrentStep()) return;
    
    try {
      setIsCreating(true);
      setError('');      const payload = {
        name: formData.name.trim(),
        description: formData.description.trim(),
        hot_topics: formData.hot_topics,
        ...(formData.profile_icon && { profile_icon: formData.profile_icon }),
        ...(formData.banner_url && { banner_url: formData.banner_url })
      };

      // Add post access configuration
      if (formData.post_access_type === 'selected_users') {
        payload.post_access_users = formData.post_access_users.map(user => user.id);
      } else if (formData.post_access_type === 'creator_only') {
        payload.post_access_users = [userData.id];
      }

      const response = await axios.post(`${api}/communities`, payload, {
        withCredentials: true
      });

      if (response.data) {
        setSuccess(true);
        setTimeout(() => {
          navigate('/communities', { replace: true });
        }, 2000);
      }
    } catch (error) {
      console.error('Error creating community:', error);
      setError(error.response?.data?.error || 'Failed to create community. Please try again.');
    } finally {
      setIsCreating(false);
    }
  };

  // Animation variants
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

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { staggerChildren: 0.1 } }
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0 }
  };

  // Success screen
  if (success) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center p-8"
        >
          <div className="w-20 h-20 bg-green-500 rounded-full flex items-center justify-center mx-auto mb-6">
            <Check className="w-10 h-10 text-white" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-2">Community Created!</h2>
          <p className="text-gray-400">Your community has been successfully created.</p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-[500px] md:max-w-[500px] mx-auto w-full mt-2 md:w-[95%] max-md:w-[98%]">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-[#0a0a0a]/90 backdrop-blur-md">
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
              <h1 className="text-xl font-bold text-white">Create Community</h1>
            </div>
            
            <div className="w-10" />
          </div>

          {/* Progress Bar */}
          <div className="px-4 pb-3">
            <div className="flex items-center space-x-2 mb-2">
              <span className="text-sm text-gray-400">Step {currentStep} of {totalSteps}</span>
            </div>
            <div className="w-full bg-gray-800 rounded-full h-2">
              <motion.div
                className="bg-blue-500 h-2 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${(currentStep / totalSteps) * 100}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-4 py-6">
          <AnimatePresence mode="wait">
            {/* Step 1: Basic Info */}
            {currentStep === 1 && (
              <motion.div
                key="step1"
                variants={stepVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="space-y-6"
              >
                <div className="text-center mb-8">
                  <h2 className="text-2xl font-bold text-white mb-2">Basic Information</h2>
                  <p className="text-gray-400">Give your community a name and description</p>
                </div>

                <motion.div variants={containerVariants} initial="hidden" animate="visible" className="space-y-6">
                  {/* Community Name */}
                  <motion.div variants={itemVariants}>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Community Name *
                    </label>
                    <input
                      ref={nameInputRef}
                      type="text"
                      value={formData.name}
                      onChange={(e) => handleInputChange('name', e.target.value)}
                      placeholder="e.g., Tech Enthusiasts, Book Club, Gamers United"
                      className="w-full px-4 py-3 bg-[#111111] border border-gray-800 rounded-2xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
                      maxLength={50}
                    />
                    <div className="flex justify-between mt-1">
                      <span className="text-xs text-gray-500">Make it catchy and memorable</span>
                      <span className="text-xs text-gray-500">{formData.name.length}/50</span>
                    </div>
                  </motion.div>

                  {/* Description */}
                  <motion.div variants={itemVariants}>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Description *
                    </label>
                    <textarea
                      ref={descriptionRef}
                      value={formData.description}
                      onChange={(e) => handleInputChange('description', e.target.value)}
                      placeholder="Describe what your community is about, its purpose, and what members can expect..."
                      className="w-full px-4 py-3 bg-[#111111] border border-gray-800 rounded-2xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors resize-none"
                      rows={4}
                      maxLength={500}
                    />
                    <div className="flex justify-between mt-1">
                      <span className="text-xs text-gray-500">Be clear and descriptive</span>
                      <span className="text-xs text-gray-500">{formData.description.length}/500</span>
                    </div>
                  </motion.div>

                  {/* Hot Topics */}
                  <motion.div variants={itemVariants}>
                    <label className="block text-sm font-medium text-gray-300 mb-2">
                      Hot Topics (Optional)
                    </label>
                    <div className="flex space-x-2 mb-3">
                      <input
                        type="text"
                        value={newTopic}
                        onChange={(e) => setNewTopic(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleTopicAdd()}
                        placeholder="Add topics..."
                        className="flex-1 px-4 py-2 bg-[#111111] border border-gray-800 rounded-xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
                        maxLength={20}
                      />
                      <motion.button
                        whileTap={{ scale: 0.95 }}
                        onClick={handleTopicAdd}
                        className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-xl font-medium transition-colors"
                        disabled={!newTopic.trim() || formData.hot_topics.length >= 10}
                      >
                        Add
                      </motion.button>
                    </div>
                    
                    {formData.hot_topics.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {formData.hot_topics.map((topic, index) => (
                          <motion.span
                            key={index}
                            initial={{ opacity: 0, scale: 0.8 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className="inline-flex items-center space-x-1 px-3 py-1 bg-blue-500/10 text-blue-400 rounded-lg text-sm"
                          >
                            <span>#{topic}</span>
                            <button
                              onClick={() => handleTopicRemove(topic)}
                              className="text-blue-400 hover:text-blue-300"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </motion.span>
                        ))}
                      </div>
                    )}
                    <p className="text-xs text-gray-500 mt-1">
                      Add up to 10 topics that describe your community
                    </p>                  </motion.div>
                </motion.div>

                {/* Error Display */}
                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl"
                  >
                    <p className="text-red-400 text-sm">{error}</p>
                  </motion.div>
                )}

                {/* Next Button */}
                <motion.button
                  whileTap={{ scale: 0.95 }}
                  onClick={handleNext}
                  className="w-full py-4 bg-blue-500 hover:bg-blue-600 text-white rounded-2xl font-semibold flex items-center justify-center space-x-2 transition-colors"
                >
                  <span>Continue</span>
                  <ArrowRight className="w-5 h-5" />
                </motion.button>
              </motion.div>
            )}

            {/* Step 2: Images */}
            {currentStep === 2 && (
              <motion.div
                key="step2"
                variants={stepVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="space-y-6"
              >
                <div className="text-center mb-8">
                  <h2 className="text-2xl font-bold text-white mb-2">Community Images</h2>
                  <p className="text-gray-400">Add a profile icon and banner (optional)</p>
                </div>

                <motion.div variants={containerVariants} initial="hidden" animate="visible" className="space-y-8">
                  {/* Profile Icon */}
                  <motion.div variants={itemVariants}>
                    <label className="block text-sm font-medium text-gray-300 mb-3">
                      Profile Icon
                    </label>
                    <div className="flex items-center space-x-4">
                      <div className="relative">
                        <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center overflow-hidden">
                          {profileIconPreview ? (
                            <img
                              src={profileIconPreview}
                              alt="Profile Icon"
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <Camera className="w-8 h-8 text-white" />
                          )}
                        </div>
                        {uploadingIcon && (
                          <div className="absolute inset-0 bg-black/50 rounded-2xl flex items-center justify-center">
                            <div className="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          </div>
                        )}
                      </div>
                      
                      <div className="flex-1">
                        <input
                          ref={profileIconRef}
                          type="file"
                          accept="image/*"
                          onChange={(e) => handleFileUpload(e.target.files[0], 'icon')}
                          className="hidden"
                        />
                        <motion.button
                          whileTap={{ scale: 0.95 }}
                          onClick={() => profileIconRef.current?.click()}
                          className="w-full py-3 border-2 border-dashed border-gray-600 hover:border-blue-500 rounded-2xl text-gray-400 hover:text-blue-400 transition-colors flex items-center justify-center space-x-2"
                          disabled={uploadingIcon}
                        >
                          <Upload className="w-5 h-5" />
                          <span>Upload Icon</span>
                        </motion.button>
                        <p className="text-xs text-gray-500 mt-2">
                          Recommended: 256x256px, PNG or JPG
                        </p>
                      </div>
                    </div>
                  </motion.div>

                  {/* Banner */}
                  <motion.div variants={itemVariants}>
                    <label className="block text-sm font-medium text-gray-300 mb-3">
                      Community Banner
                    </label>
                    <div className="space-y-4">
                      <div className="relative">
                        <div className="w-full h-32 bg-gradient-to-r from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center overflow-hidden">
                          {bannerPreview ? (
                            <img
                              src={bannerPreview}
                              alt="Banner"
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <ImageIcon className="w-12 h-12 text-white/70" />
                          )}
                        </div>
                        {uploadingBanner && (
                          <div className="absolute inset-0 bg-black/50 rounded-2xl flex items-center justify-center">
                            <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
                          </div>
                        )}
                      </div>
                      
                      <input
                        ref={bannerRef}
                        type="file"
                        accept="image/*"
                        onChange={(e) => handleFileUpload(e.target.files[0], 'banner')}
                        className="hidden"
                      />
                      <motion.button
                        whileTap={{ scale: 0.95 }}
                        onClick={() => bannerRef.current?.click()}
                        className="w-full py-3 border-2 border-dashed border-gray-600 hover:border-blue-500 rounded-2xl text-gray-400 hover:text-blue-400 transition-colors flex items-center justify-center space-x-2"
                        disabled={uploadingBanner}
                      >
                        <Upload className="w-5 h-5" />
                        <span>Upload Banner</span>
                      </motion.button>
                      <p className="text-xs text-gray-500">
                        Recommended: 1200x300px, PNG or JPG
                      </p>
                    </div>
                  </motion.div>
                </motion.div>

                {/* Error Display */}
                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl"
                  >
                    <p className="text-red-400 text-sm">{error}</p>
                  </motion.div>
                )}

                {/* Navigation Buttons */}
                <div className="flex space-x-3">
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleBack}
                    className="flex-1 py-4 bg-gray-800 hover:bg-gray-700 text-white rounded-2xl font-semibold transition-colors"
                  >
                    Back
                  </motion.button>
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleNext}
                    className="flex-1 py-4 bg-blue-500 hover:bg-blue-600 text-white rounded-2xl font-semibold flex items-center justify-center space-x-2 transition-colors"
                  >
                    <span>Continue</span>
                    <ArrowRight className="w-5 h-5" />
                  </motion.button>
                </div>
              </motion.div>
            )}

            {/* Step 3: Post Access */}
            {currentStep === 3 && (
              <motion.div
                key="step3"
                variants={stepVariants}
                initial="hidden"
                animate="visible"
                exit="exit"
                className="space-y-6"
              >
                <div className="text-center mb-8">
                  <h2 className="text-2xl font-bold text-white mb-2">Post Access</h2>
                  <p className="text-gray-400">Choose who can create posts in your community</p>
                </div>

                <motion.div variants={containerVariants} initial="hidden" animate="visible" className="space-y-6">
                  {/* Post Access Options */}
                  <motion.div variants={itemVariants}>
                    <div className="space-y-3">
                      {postAccessOptions.map((option) => {
                        const IconComponent = option.icon;
                        const isSelected = formData.post_access_type === option.key;
                        
                        return (
                          <motion.div
                            key={option.key}
                            whileTap={{ scale: 0.98 }}
                            onClick={() => handleInputChange('post_access_type', option.key)}
                            className={`p-4 border-2 rounded-2xl cursor-pointer transition-all ${
                              isSelected 
                                ? 'bg-blue-500/10 border-blue-500/20 text-blue-400' 
                                : 'border-gray-800 hover:border-gray-700'
                            }`}
                          >
                            <div className="flex items-start space-x-3">
                              <div className={`p-2 rounded-xl ${isSelected ? 'bg-blue-500/10' : 'bg-gray-800'}`}>
                                <IconComponent className={`w-5 h-5 ${isSelected ? 'text-blue-400' : 'text-gray-400'}`} />
                              </div>
                              <div className="flex-1">
                                <h4 className={`font-semibold ${isSelected ? 'text-blue-400' : 'text-white'}`}>
                                  {option.label}
                                </h4>
                                <p className="text-sm text-gray-400 mt-1">
                                  {option.description}
                                </p>
                              </div>
                              {isSelected && (
                                <div className="p-1 bg-blue-500/10 rounded-full">
                                  <Check className="w-4 h-4 text-blue-400" />
                                </div>
                              )}
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>
                  </motion.div>

                  {/* User Selection for Selected Users Option */}
                  {formData.post_access_type === 'selected_users' && (
                    <motion.div variants={itemVariants} className="space-y-4">
                      <label className="block text-sm font-medium text-gray-300">
                        Select Users Who Can Post
                      </label>
                      
                      {/* Search Input */}
                      <div className="relative">
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                        <input
                          type="text"
                          value={userSearchQuery}
                          onChange={(e) => setUserSearchQuery(e.target.value)}
                          placeholder="Search users by username..."
                          className="w-full pl-10 pr-4 py-3 bg-[#111111] border border-gray-800 rounded-2xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
                        />
                        {isSearching && (
                          <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                            <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                          </div>
                        )}
                      </div>

                      {/* Search Results */}
                      {searchResults.length > 0 && (
                        <div className="bg-[#111111] border border-gray-800 rounded-2xl overflow-hidden">
                          {searchResults.map((user) => (
                            <motion.div
                              key={user.id}
                              whileTap={{ scale: 0.98 }}
                              onClick={() => handleUserSelect(user)}
                              className="flex items-center space-x-3 p-4 hover:bg-gray-800 cursor-pointer transition-colors border-b border-gray-800 last:border-b-0"
                            >                              <div className="w-10 h-10 bg-gradient-to-br from-gray-600 to-gray-700 rounded-full flex items-center justify-center">
                                {user.profilePicture ? (
                                  <img
                                    src={`${cloud}/cloudofscubiee/profilePic/${user.profilePicture}`}
                                    alt={user.username}
                                    className="w-full h-full rounded-full object-cover"
                                  />
                                ) : (
                                  <span className="text-sm font-medium text-white">
                                    {user.username.charAt(0).toUpperCase()}
                                  </span>
                                )}
                              </div>
                              <div className="flex-1">
                                <p className="font-medium text-white">@{user.username}</p>
                                {user.firstName && user.lastName && (
                                  <p className="text-sm text-gray-400">
                                    {user.firstName} {user.lastName}
                                  </p>
                                )}
                              </div>
                            </motion.div>
                          ))}
                        </div>
                      )}

                      {/* Selected Users */}
                      {formData.post_access_users.length > 0 && (
                        <div className="space-y-2">
                          <label className="block text-sm font-medium text-gray-300">
                            Selected Users ({formData.post_access_users.length})
                          </label>
                          <div className="space-y-2">
                            {formData.post_access_users.map((user) => (
                              <motion.div
                                key={user.id}
                                initial={{ opacity: 0, scale: 0.9 }}
                                animate={{ opacity: 1, scale: 1 }}
                                className="flex items-center justify-between p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl"
                              >
                                <div className="flex items-center space-x-3">                                  <div className="w-8 h-8 bg-gradient-to-br from-gray-600 to-gray-700 rounded-full flex items-center justify-center">
                                    {user.profilePicture ? (
                                      <img
                                        src={`${cloud}/cloudofscubiee/profilePic/${user.profilePicture}`}
                                        alt={user.username}
                                        className="w-full h-full rounded-full object-cover"
                                      />
                                    ) : (
                                      <span className="text-xs font-medium text-white">
                                        {user.username.charAt(0).toUpperCase()}
                                      </span>
                                    )}
                                  </div>
                                  <div>
                                    <p className="text-sm font-medium text-blue-400">@{user.username}</p>
                                    {user.firstName && user.lastName && (
                                      <p className="text-xs text-gray-400">
                                        {user.firstName} {user.lastName}
                                      </p>
                                    )}
                                  </div>
                                </div>
                                <motion.button
                                  whileTap={{ scale: 0.9 }}
                                  onClick={() => handleUserRemove(user.id)}
                                  className="p-1 text-blue-400 hover:text-blue-300 transition-colors"
                                >
                                  <X className="w-4 h-4" />
                                </motion.button>
                              </motion.div>
                            ))}
                          </div>
                        </div>
                      )}
                    </motion.div>
                  )}
                </motion.div>

                {/* Error Display */}
                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-4 bg-red-500/10 border border-red-500/20 rounded-2xl"
                  >
                    <p className="text-red-400 text-sm">{error}</p>
                  </motion.div>
                )}

                {/* Navigation Buttons */}
                <div className="flex space-x-3">
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleBack}
                    className="flex-1 py-4 bg-gray-800 hover:bg-gray-700 text-white rounded-2xl font-semibold transition-colors"
                  >
                    Back
                  </motion.button>
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={handleCreate}
                    disabled={isCreating}
                    className="flex-1 py-4 bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-2xl font-semibold flex items-center justify-center space-x-2 transition-colors"
                  >
                    {isCreating ? (
                      <>
                        <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        <span>Creating...</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-5 h-5" />
                        <span>Create Community</span>
                      </>
                    )}
                  </motion.button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
};

export default CreateCommunity;
