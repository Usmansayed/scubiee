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
  Sparkles,
  Save,
  Trash2
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import axios from 'axios';
import { toast } from 'react-toastify';

const EditCommunity = () => {
  const navigate = useNavigate();
  const { id } = useParams();
  const { userData } = useSelector((state) => state.user);
  const api = import.meta.env.VITE_API_URL;
  const cloud = import.meta.env.VITE_CLOUD_URL;

  // Step management
  const [currentStep, setCurrentStep] = useState(1);
  const totalSteps = 3;
  
  // Loading states
  const [loading, setLoading] = useState(true);
  const [originalData, setOriginalData] = useState(null);
  
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
  const [isUpdating, setIsUpdating] = useState(false);
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

  // Fetch community data
  useEffect(() => {
    const fetchCommunity = async () => {
      try {
        setLoading(true);
        const response = await axios.get(`${api}/communities/${id}`, {
          withCredentials: true
        });
        
        if (response.data) {
          const community = response.data;
          
          // Check if user has permission to edit
          if (community.creator?.id !== userData?.id) {
            toast.error("You don't have permission to edit this community");
            navigate(`/community/${id}`);
            return;
          }
          
          // Set form data
          const data = {
            name: community.name || '',
            description: community.description || '',
            hot_topics: community.hot_topics || [],
            post_access_type: community.post_access_type || 'everyone',
            post_access_users: community.post_access_users || [],
            profile_icon: community.profile_icon,
            banner_url: community.banner_url
          };
          
          setFormData(data);
          setOriginalData(data);
          
          // Set image previews
          if (community.profile_icon) {
            setProfileIconPreview(`${cloud}/cloudofscubiee/communityProfile/${community.profile_icon}`);
          }
          if (community.banner_url) {
            setBannerPreview(`${cloud}/cloudofscubiee/communityBanner/${community.banner_url}`);
          }
        }
      } catch (error) {
        console.error('Error fetching community:', error);
        toast.error('Failed to load community data');
        navigate('/communities');
      } finally {
        setLoading(false);
      }
    };

    if (id && userData) {
      fetchCommunity();
    }
  }, [id, userData, api, cloud, navigate]);

  // Focus management
  useEffect(() => {
    if (currentStep === 1 && nameInputRef.current && !loading) {
      nameInputRef.current.focus();
    }
  }, [currentStep, loading]);

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
      navigate(`/community/${id}`);
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

  const handleUserAdd = (user) => {
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
  const handleIconUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    // Validate file
    if (!file.type.startsWith('image/')) {
      setError('Please upload an image file');
      return;
    }

    if (file.size > 5 * 1024 * 1024) { // 5MB
      setError('Image file must be smaller than 5MB');
      return;
    }

    try {
      setUploadingIcon(true);
      setError('');

      // Create preview
      const previewUrl = URL.createObjectURL(file);
      setProfileIconPreview(previewUrl);

      // Store file for upload
      setFormData(prev => ({ ...prev, profile_icon: file }));
    } catch (error) {
      console.error('Error handling icon upload:', error);
      setError('Failed to process image');
    } finally {
      setUploadingIcon(false);
    }
  };

  const handleBannerUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    // Validate file
    if (!file.type.startsWith('image/')) {
      setError('Please upload an image file');
      return;
    }

    if (file.size > 10 * 1024 * 1024) { // 10MB
      setError('Banner image must be smaller than 10MB');
      return;
    }

    try {
      setUploadingBanner(true);
      setError('');

      // Create preview
      const previewUrl = URL.createObjectURL(file);
      setBannerPreview(previewUrl);

      // Store file for upload
      setFormData(prev => ({ ...prev, banner_url: file }));
    } catch (error) {
      console.error('Error handling banner upload:', error);
      setError('Failed to process image');
    } finally {
      setUploadingBanner(false);
    }
  };

  // Check if there are any changes
  const hasChanges = () => {
    if (!originalData) return false;
    
    return (
      formData.name !== originalData.name ||
      formData.description !== originalData.description ||
      JSON.stringify(formData.hot_topics) !== JSON.stringify(originalData.hot_topics) ||
      formData.post_access_type !== originalData.post_access_type ||
      JSON.stringify(formData.post_access_users) !== JSON.stringify(originalData.post_access_users) ||
      (formData.profile_icon instanceof File) ||
      (formData.banner_url instanceof File)
    );
  };

  // Submit handler
  const handleSubmit = async () => {
    if (!validateCurrentStep()) return;
    if (!hasChanges()) {
      toast.info('No changes to save');
      return;
    }

    try {
      setIsUpdating(true);
      setError('');      const submitData = new FormData();
      
      // Add basic fields
      submitData.append('name', formData.name);
      submitData.append('description', formData.description);
      submitData.append('hot_topics', JSON.stringify(formData.hot_topics));
      submitData.append('post_access_type', formData.post_access_type);
      
      // Extract user IDs from post_access_users
      const userIds = formData.post_access_users.map(user => {
        return typeof user === 'object' ? user.id : user;
      });
      submitData.append('post_access_users', JSON.stringify(userIds));

      // Add files if they're new uploads
      if (formData.profile_icon instanceof File) {
        submitData.append('profile_icon', formData.profile_icon);
      }
      if (formData.banner_url instanceof File) {
        submitData.append('banner_url', formData.banner_url);
      }

      const response = await axios.put(`${api}/communities/${id}`, submitData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        withCredentials: true
      });

      if (response.data.success) {
        setSuccess(true);
        toast.success('Community updated successfully!');
        
        // Redirect after a brief moment
        setTimeout(() => {
          navigate(`/community/${id}`);
        }, 1500);
      } else {
        setError(response.data.error || 'Failed to update community');
      }
    } catch (error) {
      console.error('Error updating community:', error);
      setError(error.response?.data?.error || 'Failed to update community');
      toast.error('Failed to update community');
    } finally {
      setIsUpdating(false);
    }
  };

  // Animation variants
  const containerVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { 
      opacity: 1, 
      y: 0,
      transition: { duration: 0.4, ease: "easeOut" }
    }
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
      transition: { duration: 0.2, ease: "easeIn" }
    }
  };

  // Show loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-current border-r-transparent">
            <span className="sr-only">Loading...</span>
          </div>
          <p className="mt-4 text-gray-400">Loading community data...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white mb-10">
      <div className="max-w-2xl mx-auto px-4 py-6">
        {/* Header */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="flex items-center justify-between mb-8"
        >
          <div className="flex items-center space-x-4">
            <motion.button
              whileTap={{ scale: 0.9 }}
              onClick={handleBack}
              className="p-2 hover:bg-gray-800 rounded-full transition-colors"
            >
              <ArrowLeft className="w-6 h-6" />
            </motion.button>
            <div>
              <h1 className="text-2xl max-md:text-xl font-bold">Edit Community</h1>
              <p className="text-gray-400 text-sm">
                Step {currentStep} of {totalSteps}
              </p>
            </div>
          </div>
          
          {/* Save button - show when changes exist */}
          {hasChanges() && (
            <motion.button
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              whileTap={{ scale: 0.95 }}
              onClick={handleSubmit}
              disabled={isUpdating}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white rounded-xl font-medium transition-colors flex items-center space-x-2"
            >
              {isUpdating ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Saving...</span>
                </>
              ) : (
                <>
                  <Save className="w-4 h-4" />
                  <span>Save</span>
                </>
              )}
            </motion.button>
          )}
        </motion.div>

        {/* Progress bar */}
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="mb-8"
        >
          <div className="flex items-center space-x-2 mb-2">
            {Array.from({ length: totalSteps }, (_, i) => (
              <div
                key={i}
                className={`flex-1 h-2 rounded-full transition-all duration-300 ${
                  i + 1 <= currentStep ? 'bg-blue-600' : 'bg-gray-800'
                }`}
              />
            ))}
          </div>
          <div className="flex justify-between text-xs text-gray-400">
            <span>Basic Info</span>
            <span>Images</span>
            <span>Permissions</span>
          </div>
        </motion.div>

        {/* Error Display */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mb-6 p-4 bg-red-900/20 border border-red-500/30 rounded-xl text-red-400"
            >
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Success Display */}
        <AnimatePresence>
          {success && (
            <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              className="mb-6 p-6 bg-green-900/20 border border-green-500/30 rounded-xl text-center"
            >
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.2, type: "spring" }}
                className="w-16 h-16 bg-green-600 rounded-full flex items-center justify-center mx-auto mb-4"
              >
                <Check className="w-8 h-8 text-white" />
              </motion.div>
              <h3 className="text-xl font-semibold text-green-400 mb-2">
                Community Updated Successfully!
              </h3>
              <p className="text-gray-400">
                Redirecting you to the community page...
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step Content */}
        <AnimatePresence mode="wait">
          <motion.div
            key={currentStep}
            variants={stepVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="bg-[#111111] border border-gray-800 rounded-2xl p-6"
          >
            {/* Step 1: Basic Information */}
            {currentStep === 1 && (
              <div className="space-y-6">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 bg-blue-600 rounded-full flex items-center justify-center">
                    <span className="text-white font-semibold">1</span>
                  </div>
                  <div>
                    <h2 className="text-xl font-semibold">Basic Information</h2>
                    <p className="text-gray-400 text-sm">
                      Update your community's name and description
                    </p>
                  </div>
                </div>

                {/* Community Name */}
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Community Name *
                  </label>
                  <input
                    ref={nameInputRef}
                    type="text"
                    value={formData.name}
                    onChange={(e) => handleInputChange('name', e.target.value)}
                    placeholder="Enter community name"
                    maxLength={50}
                    className="w-full px-4 py-3 bg-[#1a1a1a] border border-gray-700 rounded-xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                  <div className="flex justify-between mt-1">
                    <span className="text-xs text-gray-500">
                      Minimum 3 characters
                    </span>
                    <span className="text-xs text-gray-500">
                      {formData.name.length}/50
                    </span>
                  </div>
                </div>

                {/* Community Description */}
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Description *
                  </label>
                  <textarea
                    ref={descriptionRef}
                    value={formData.description}
                    onChange={(e) => handleInputChange('description', e.target.value)}
                    placeholder="Describe what your community is about..."
                    rows={4}
                    maxLength={500}
                    className="w-full px-4 py-3 bg-[#1a1a1a] border border-gray-700 rounded-xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 resize-none"
                  />
                  <div className="flex justify-between mt-1">
                    <span className="text-xs text-gray-500">
                      Tell people what makes your community special
                    </span>
                    <span className="text-xs text-gray-500">
                      {formData.description.length}/500
                    </span>
                  </div>
                </div>

                {/* Hot Topics */}
                <div>
                  <label className="block text-sm font-medium mb-2">
                    Hot Topics
                  </label>
                  <div className="space-y-3">
                    <div className="flex space-x-2">
                      <input
                        type="text"
                        value={newTopic}
                        onChange={(e) => setNewTopic(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleTopicAdd()}
                        placeholder="Add a topic (e.g., technology, gaming)"
                        className="flex-1 px-4 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                      />
                      <motion.button
                        whileTap={{ scale: 0.95 }}
                        onClick={handleTopicAdd}
                        disabled={!newTopic.trim() || formData.hot_topics.length >= 10}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-400 text-white rounded-lg font-medium transition-colors"
                      >
                        Add
                      </motion.button>
                    </div>
                    
                    {/* Topic List */}
                    {formData.hot_topics.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {formData.hot_topics.map((topic, index) => (
                          <motion.div
                            key={topic}
                            initial={{ opacity: 0, scale: 0.8 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className="flex items-center space-x-2 px-3 py-1 bg-blue-600/20 border border-blue-500/30 rounded-full"
                          >
                            <span className="text-sm text-blue-400">#{topic}</span>
                            <button
                              onClick={() => handleTopicRemove(topic)}
                              className="text-blue-400 hover:text-blue-300 transition-colors"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </motion.div>
                        ))}
                      </div>
                    )}
                    
                    <p className="text-xs text-gray-500">
                      Topics help people discover your community ({formData.hot_topics.length}/10)
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Step 2: Images */}
            {currentStep === 2 && (
              <div className="space-y-6">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 bg-blue-600 rounded-full flex items-center justify-center">
                    <span className="text-white font-semibold">2</span>
                  </div>
                  <div>
                    <h2 className="text-xl font-semibold">Community Images</h2>
                    <p className="text-gray-400 text-sm">
                      Update your community's profile icon and banner (optional)
                    </p>
                  </div>
                </div>

                {/* Profile Icon */}
                <div>
                  <label className="block text-sm font-medium mb-3">
                    Profile Icon
                  </label>
                  <div className="flex items-center space-x-4">
                    <div className="relative">
                      <div className="w-20 h-20 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center overflow-hidden">
                        {profileIconPreview ? (
                          <img
                            src={profileIconPreview}
                            alt="Profile icon preview"
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <Users className="w-8 h-8 text-white" />
                        )}
                      </div>
                      {uploadingIcon && (
                        <div className="absolute inset-0 bg-black/50 rounded-2xl flex items-center justify-center">
                          <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1">
                      <input
                        ref={profileIconRef}
                        type="file"
                        accept="image/*"
                        onChange={handleIconUpload}
                        className="hidden"
                      />
                      <motion.button
                        whileTap={{ scale: 0.95 }}
                        onClick={() => profileIconRef.current?.click()}
                        disabled={uploadingIcon}
                        className="w-full px-4 py-3 bg-[#1a1a1a] hover:bg-gray-800 border border-gray-700 hover:border-gray-600 rounded-xl transition-colors flex items-center justify-center space-x-2"
                      >
                        <Upload className="w-5 h-5" />
                        <span>
                          {profileIconPreview ? 'Change Icon' : 'Upload Icon'}
                        </span>
                      </motion.button>
                      <p className="text-xs text-gray-500 mt-1">
                        Recommended: 400x400px, max 5MB
                      </p>
                    </div>
                  </div>
                </div>

                {/* Banner Image */}
                <div>
                  <label className="block text-sm font-medium mb-3">
                    Banner Image
                  </label>
                  <div className="space-y-3">
                    <div className="relative">
                      <div className="w-full h-32 bg-gradient-to-r from-purple-500 to-blue-600 rounded-xl flex items-center justify-center overflow-hidden">
                        {bannerPreview ? (
                          <img
                            src={bannerPreview}
                            alt="Banner preview"
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <ImageIcon className="w-12 h-12 text-white/50" />
                        )}
                      </div>
                      {uploadingBanner && (
                        <div className="absolute inset-0 bg-black/50 rounded-xl flex items-center justify-center">
                          <div className="w-6 h-6 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        </div>
                      )}
                    </div>
                    <input
                      ref={bannerRef}
                      type="file"
                      accept="image/*"
                      onChange={handleBannerUpload}
                      className="hidden"
                    />
                    <motion.button
                      whileTap={{ scale: 0.95 }}
                      onClick={() => bannerRef.current?.click()}
                      disabled={uploadingBanner}
                      className="w-full px-4 py-3 bg-[#1a1a1a] hover:bg-gray-800 border border-gray-700 hover:border-gray-600 rounded-xl transition-colors flex items-center justify-center space-x-2"
                    >
                      <Upload className="w-5 h-5" />
                      <span>
                        {bannerPreview ? 'Change Banner' : 'Upload Banner'}
                      </span>
                    </motion.button>
                    <p className="text-xs text-gray-500">
                      Recommended: 1200x300px, max 10MB
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Step 3: Post Access Permissions */}
            {currentStep === 3 && (
              <div className="space-y-6">
                <div className="flex items-center space-x-3 mb-6">
                  <div className="w-10 h-10 bg-blue-600 rounded-full flex items-center justify-center">
                    <span className="text-white font-semibold">3</span>
                  </div>
                  <div>
                    <h2 className="text-xl font-semibold">Post Permissions</h2>
                    <p className="text-gray-400 text-sm">
                      Choose who can create posts in your community
                    </p>
                  </div>
                </div>

                {/* Post Access Options */}
                <div className="space-y-3">
                  {postAccessOptions.map((option) => {
                    const IconComponent = option.icon;
                    const isSelected = formData.post_access_type === option.key;
                    
                    return (
                      <motion.div
                        key={option.key}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => handleInputChange('post_access_type', option.key)}
                        className={`p-4 border rounded-xl cursor-pointer transition-all ${
                          isSelected
                            ? 'border-blue-500 bg-blue-500/10'
                            : 'border-gray-700 hover:border-gray-600'
                        }`}
                      >
                        <div className="flex items-center space-x-3">
                          <div className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                            isSelected ? 'border-blue-500 bg-blue-500' : 'border-gray-400'
                          }`}>
                            {isSelected && (
                              <motion.div
                                initial={{ scale: 0 }}
                                animate={{ scale: 1 }}
                                className="w-2 h-2 bg-white rounded-full"
                              />
                            )}
                          </div>
                          <IconComponent className={`w-5 h-5 ${
                            isSelected ? 'text-blue-400' : 'text-gray-400'
                          }`} />
                          <div className="flex-1">
                            <h3 className={`font-medium ${
                              isSelected ? 'text-blue-400' : 'text-white'
                            }`}>
                              {option.label}
                            </h3>
                            <p className="text-sm text-gray-400">
                              {option.description}
                            </p>
                          </div>
                        </div>
                      </motion.div>
                    );
                  })}
                </div>

                {/* Selected Users (if applicable) */}
                {formData.post_access_type === 'selected_users' && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium mb-2">
                        Search and Add Users
                      </label>
                      <div className="relative">
                        <input
                          type="text"
                          value={userSearchQuery}
                          onChange={(e) => setUserSearchQuery(e.target.value)}
                          placeholder="Search users by username..."
                          className="w-full px-4 py-3 pl-10 bg-[#1a1a1a] border border-gray-700 rounded-xl text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                        />
                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                        {isSearching && (
                          <div className="absolute right-3 top-1/2 transform -translate-y-1/2">
                            <div className="w-5 h-5 border-2 border-gray-400 border-t-blue-500 rounded-full animate-spin" />
                          </div>
                        )}
                      </div>

                      {/* Search Results */}
                      {searchResults.length > 0 && (
                        <div className="mt-2 max-h-40 overflow-y-auto bg-[#1a1a1a] border border-gray-700 rounded-xl">
                          {searchResults.map((user) => (
                            <motion.button
                              key={user.id}
                              whileHover={{ backgroundColor: "rgba(75, 85, 99, 0.1)" }}
                              onClick={() => handleUserAdd(user)}
                              className="w-full px-4 py-3 flex items-center space-x-3 hover:bg-gray-700/50 transition-colors text-left"
                            >
                              <div className="w-8 h-8 bg-gradient-to-br from-gray-600 to-gray-700 rounded-full flex items-center justify-center">
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
                                <p className="text-white font-medium">@{user.username}</p>
                                {user.fullName && (
                                  <p className="text-gray-400 text-sm">{user.fullName}</p>
                                )}
                              </div>
                            </motion.button>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Selected Users List */}
                    {formData.post_access_users.length > 0 && (
                      <div>
                        <label className="block text-sm font-medium mb-2">
                          Users with Post Access ({formData.post_access_users.length})
                        </label>
                        <div className="space-y-2 max-h-40 overflow-y-auto">
                          {formData.post_access_users.map((user) => (
                            <motion.div
                              key={user.id}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              className="flex items-center justify-between p-3 bg-[#1a1a1a] rounded-lg"
                            >
                              <div className="flex items-center space-x-3">
                                <div className="w-8 h-8 bg-gradient-to-br from-gray-600 to-gray-700 rounded-full flex items-center justify-center">
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
                                  <p className="text-white font-medium">@{user.username}</p>
                                  {user.fullName && (
                                    <p className="text-gray-400 text-sm">{user.fullName}</p>
                                  )}
                                </div>
                              </div>
                              <motion.button
                                whileTap={{ scale: 0.9 }}
                                onClick={() => handleUserRemove(user.id)}
                                className="p-1 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded transition-colors"
                              >
                                <X className="w-4 h-4" />
                              </motion.button>
                            </motion.div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </motion.div>
        </AnimatePresence>

        {/* Navigation Buttons */}
        {!success && (
          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="flex justify-between mt-8"
          >
            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={handleBack}
              className="px-6 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-xl font-medium transition-colors flex items-center space-x-2"
            >
              <ArrowLeft className="w-5 h-5" />
              <span>{currentStep === 1 ? 'Cancel' : 'Back'}</span>
            </motion.button>

            {currentStep < totalSteps ? (
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleNext}
                className="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-medium transition-colors flex items-center space-x-2"
              >
                <span>Next</span>
                <ArrowRight className="w-5 h-5" />
              </motion.button>
            ) : (
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleSubmit}
                disabled={isUpdating || !hasChanges()}
                className="px-6 py-3 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:text-gray-400 text-white rounded-xl font-medium transition-colors flex items-center space-x-2"
              >
                {isUpdating ? (
                  <>
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Updating...</span>
                  </>
                ) : (
                  <>
                    <Save className="w-5 h-5" />
                    <span>Save Changes</span>
                  </>
                )}
              </motion.button>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
};

export default EditCommunity;
