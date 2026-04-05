import React, { useState, useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import './CreatePost.css';
import axios from 'axios';
import 'react-toastify/dist/ReactToastify.css';
import { FaImage, FaVideo, FaXmark, FaArrowRightLong, FaPlus, FaUsers } from 'react-icons/fa6';
import { setShowCategorySelector, setFormData, setFormType } from '../Slices/WidgetSlice';
import { setIsPosting } from '../Slices/UserSlice';
import CuisineSelector from '../components/postSelection';
import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import { fetchProfileInfo, fetchUserPosts } from '../Slices/profileSlice';

const api = import.meta.env.VITE_API_URL;
const cloud = import.meta.env.VITE_CLOUD_URL;

// Custom hook for horizontal scroll index
function useHorizontalScrollIndex(imageCount) {
  const [currentIndex, setCurrentIndex] = React.useState(0);
  const containerRef = React.useRef(null);

  React.useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const children = Array.from(container.children);
      let minDiff = Infinity;
      let idx = 0;
      children.forEach((child, i) => {
        const diff = Math.abs(child.getBoundingClientRect().left - container.getBoundingClientRect().left);
        if (diff < minDiff) {
          minDiff = diff;
          idx = i;
        }
      });
      setCurrentIndex(idx);
    };

    container.addEventListener('scroll', handleScroll, { passive: true });
    return () => container.removeEventListener('scroll', handleScroll);
  }, [imageCount]);

  React.useEffect(() => {
    setCurrentIndex(0);
  }, [imageCount]);

  return [containerRef, currentIndex];
}

// Horizontal image scroll component for previews
const HorizontalImageScroll = ({ imageFiles, imageIndexes, mediaPreviewUrls, handleRemoveMedia }) => {
  const [scrollRef, scrollIndex] = useHorizontalScrollIndex(imageFiles.length);

  return (
    <div className="relative mb-4">
      <div
        ref={scrollRef}
        className="flex overflow-x-auto snap-x snap-mandatory scrollbar-hide w-[98%] mx-auto py-2 space-x-2"
      >
        {imageFiles.map((file, i) => {
          const idx = imageIndexes[i];
          return (
            <div
              key={`img-${i}`}
              className="flex-shrink-0 snap-start snap-always w-[92%] first:pl-0"
            >
              <div className="[aspect-ratio:14/10] w-full h-full relative group">
                <img
                  src={mediaPreviewUrls[idx]}
                  alt={`Preview ${i}`}
                  className="w-full h-full object-cover rounded-lg"
                />
                <button
                  onClick={() => handleRemoveMedia(idx)}
                  className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <FaXmark className="text-sm" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <div className="absolute bottom-4 right-4 bg-black/60 px-2 py-1 rounded-full text-xs text-white">
        {imageFiles.length > 1 && (
          <span>{`${scrollIndex + 1}/${imageFiles.length}`}</span>
        )}
      </div>
    </div>
  );
};

function CreatePost() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const { communityId } = useParams();
  
  // Check if creating post from within a community
  const isDirectCommunityPost = Boolean(communityId);
  
  // State for community details when posting directly to community
  const [targetCommunity, setTargetCommunity] = useState(null);
  
    // State for post content
  const [text, setText] = useState('');
  const [mediaFiles, setMediaFiles] = useState([]);
  const [mediaPreviewUrls, setMediaPreviewUrls] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPWA, setIsPWA] = useState(false);
  const [showMediaSelector, setShowMediaSelector] = useState(false);
  const [charCount, setCharCount] = useState(0);
  const [ffmpegLoaded, setFfmpegLoaded] = useState(false);
  const [ffmpeg] = useState(() => new FFmpeg());
  const [errorMessage, setErrorMessage] = useState("");
  const [showError, setShowError] = useState(false);
  const [isProcessingMedia, setIsProcessingMedia] = useState(false);
  // Add state for success notification
  const [showSuccessMessage, setShowSuccessMessage] = useState(false);
  
  // Community selection state
  const [showCommunitySelector, setShowCommunitySelector] = useState(false);
  const [userCommunities, setUserCommunities] = useState([]);
  const [selectedCommunities, setSelectedCommunities] = useState([]);
  const [loadingCommunities, setLoadingCommunities] = useState(false);
  
  // Refs
  const fileInputRef = useRef(null);
  const textAreaRef = useRef(null);
  const mediaSelectorRef = useRef(null);
  
  // Redux state
  const showCategorySelector = useSelector((state) => state.widget.showCategorySelector);

  // Check if running as PWA
  useEffect(() => {
    const handleDisplayModeChange = () => setIsPWA(isRunningAsPWA());
    window.addEventListener('resize', handleDisplayModeChange);
    return () => window.removeEventListener('resize', handleDisplayModeChange);
  }, []);
  // Auto resize textarea
  useEffect(() => {
    if (textAreaRef.current) {
      textAreaRef.current.style.height = 'auto';
      textAreaRef.current.style.height = `${Math.min(textAreaRef.current.scrollHeight, 300)}px`;
    }
    
    // Update character count
    setCharCount(text.length);
  }, [text]);
  
  // Fetch community details when posting directly to a community
  useEffect(() => {
    const fetchTargetCommunity = async () => {
      if (isDirectCommunityPost && communityId) {
        try {
          const response = await axios.get(`${api}/communities/${communityId}`, {
            withCredentials: true,
          });
          if (response.data.success) {
            setTargetCommunity(response.data.community);
          }
        } catch (error) {
          console.error('Error fetching target community:', error);
          // If we can't fetch the community, redirect to general create post
          navigate('/create-post');
        }
      }
    };
    
    fetchTargetCommunity();
  }, [isDirectCommunityPost, communityId, navigate]);

  // Close media selector on outside click
  useEffect(() => {
    function handleClickOutside(event) {
      if (mediaSelectorRef.current && !mediaSelectorRef.current.contains(event.target)) {
        setShowMediaSelector(false);
      }
    }
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [mediaSelectorRef]);

  // Initialize FFmpeg
  useEffect(() => {
    const loadFFmpeg = async () => {
      try {
        await ffmpeg.load();
        setFfmpegLoaded(true);
        console.log("FFmpeg loaded successfully");
      } catch (error) {
        console.error("Error loading FFmpeg:", error);
      }
    };
    
    loadFFmpeg();
    
    return () => {
      // Cleanup FFmpeg if needed
    };
  }, [ffmpeg]);

  // Extract hashtags and mentions from text
  const extractTags = (text, symbol) => {
    const regex = new RegExp(`\\${symbol}[A-Za-z0-9_]+`, 'g');
    return text.match(regex) || [];
  };
  // Fetch user's communities
  const fetchUserCommunities = async () => {
    try {
      setLoadingCommunities(true);
      const response = await axios.get(`${api}/communities/user-communities`, {
        withCredentials: true,
      });
        if (response.data.success) {        
        console.log('[DEBUG] User communities response:', response.data.communities);
        
        // Filter communities where user can post based on new access_type logic
        const postableCommunities = response.data.communities.filter(community => {
          const membership = community.membership;
          const isCreator = community.creator_id === membership.user_id;
          
          console.log('[DEBUG] Checking community:', {
            name: community.name,
            access_type: community.access_type,
            user_role: membership.role,
            isCreator,
            user_id: membership.user_id,
            creator_id: community.creator_id
          });
          
          // New simplified logic based on access_type
          switch (community.access_type) {
            case 'admin':
              // Only creator/admin can post
              return isCreator || membership.role === 'admin';
            case 'moderator':
              // Creator, admin, and moderators can post
              return isCreator || membership.role === 'admin' || membership.role === 'moderator';
            case 'everyone':
              // All active members can post
              return true;
            default:
              return false;
          }
        });
        
        console.log('[DEBUG] Filtered postable communities:', postableCommunities);
        setUserCommunities(postableCommunities);
        return postableCommunities;
      }
      return [];
    } catch (error) {
      console.error('Error fetching user communities:', error);
      setUserCommunities([]);
      return [];
    } finally {
      setLoadingCommunities(false);
    }
  };

  // Toggle media selector
  const toggleMediaSelector = () => {
    setShowMediaSelector(!showMediaSelector);
  };

  // Handle file selection
  const handleFileSelect = () => {
    fileInputRef.current.click();
  };

  // Video trimming function
  const trimVideo = async (file, startTime = "0", duration = "120") => {
    if (!ffmpegLoaded) {
      try {
        await ffmpeg.load();
        setFfmpegLoaded(true);
      } catch (error) {
        console.error("Error loading FFmpeg:", error);
        displayErrorMessage("Could not process video. Please try again or use a shorter video.");
        return null;
      }
    }
    
    try {
      // Create a unique input filename
      const inputName = `input-${Date.now()}.mp4`;
      const outputName = `output-${Date.now()}.mp4`;
      
      // Write the input file to FFmpeg's in-memory file system
      await ffmpeg.writeFile(inputName, await fetchFile(file));
      
      // Execute FFmpeg command to trim the video
      await ffmpeg.exec([
        "-i", inputName,
        "-ss", startTime,
        "-t", duration,
        "-c:v", "copy",
        "-c:a", "copy",
        outputName
      ]);
      
      // Read the output file
      const data = await ffmpeg.readFile(outputName);
      
      // Clean up temporary files
      try {
        await ffmpeg.deleteFile(inputName);
        await ffmpeg.deleteFile(outputName);
      } catch (cleanupError) {
        console.error("Error cleaning up FFmpeg temporary files:", cleanupError);
      }
      
      // Create new File object
      return new File([data.buffer], "trimmed_" + file.name, { type: "video/mp4" });
    } catch (error) {
      console.error("Error trimming video:", error);
      displayErrorMessage("Failed to process video. Please try a different file.");
      return null;
    }
  };

  // Helper function to validate file types
  const isValidFileType = (file) => {
    const validImageTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    const validVideoTypes = ['video/mp4'];
    
    if (file.type.startsWith('image/')) {
      return validImageTypes.includes(file.type);
    } else if (file.type.startsWith('video/')) {
      return validVideoTypes.includes(file.type);
    }
    
    return false;
  };

  // Show error message for 3 seconds then hide it
  const displayErrorMessage = (message) => {
    setErrorMessage(message);
    setShowError(true);
    setTimeout(() => {
      setShowError(false);
    }, 3000);
  };

  // Handle media change
  const handleMediaChange = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    setIsProcessingMedia(true);
    
    // Validate file types
    const invalidFiles = files.filter(file => !isValidFileType(file));
    if (invalidFiles.length > 0) {
      displayErrorMessage('Only JPG, JPEG, PNG images and MP4 videos are allowed');
      setIsProcessingMedia(false);
      return;
    }

    // Separate videos and images
    const videoFiles = files.filter(file => file.type.startsWith('video/'));
    const imageFiles = files.filter(file => file.type.startsWith('image/'));

    // Check image file size
    for (const imgFile of imageFiles) {
      if (imgFile.size > 15 * 1024 * 1024) { // 15MB limit for images
        displayErrorMessage('Image size must be less than 15MB');
        setIsProcessingMedia(false);
        return;
      }
    }

    // Check total media limit
    const totalNewFiles = [...videoFiles, ...imageFiles];
    const totalFiles = [...mediaFiles, ...totalNewFiles];
    if (totalFiles.length > 4) {
      displayErrorMessage('Maximum 4 media files allowed');
      setIsProcessingMedia(false);
      return;
    }

    // Process videos (check count, size, duration, and trim if needed)
    let processedVideoFiles = [];
    if (videoFiles.length > 0) {
      // Check if there's already a video
      if (mediaFiles.some(file => file.type.startsWith('video/'))) {
        displayErrorMessage('Only one video is allowed per post');
        setIsProcessingMedia(false);
        return;
      }

      // Check video count
      if (videoFiles.length > 1) {
        displayErrorMessage('Only one video is allowed per post');
        setIsProcessingMedia(false);
        return;
      }

      const videoFile = videoFiles[0];
      
      // Initial size check before processing
      if (videoFile.size > 1024 * 1024 * 1024) { // 1GB pre-processing limit
        displayErrorMessage('Video file is too large (max 1GB)');
        setIsProcessingMedia(false);
        return;
      }

      // Create video element to check duration
      const video = document.createElement('video');
      video.preload = 'metadata';
      
      // Process the video when metadata is loaded
      try {
        await new Promise((resolve, reject) => {
          video.onloadedmetadata = resolve;
          video.onerror = reject;
          video.src = URL.createObjectURL(videoFile);
        });
        
        // Revoke object URL immediately to avoid memory leaks
        const videoObjectUrl = video.src;
        setTimeout(() => URL.revokeObjectURL(videoObjectUrl), 120);
        
        // Check if video needs trimming (longer than 120 seconds)
        if (video.duration > 120) {
          const trimmedVideo = await trimVideo(videoFile);
          if (!trimmedVideo) {
            displayErrorMessage('Failed to process video. Please try again with a shorter video.');
            setIsProcessingMedia(false);
            return;
          }
          
          // Check if trimmed video is still too large
          if (trimmedVideo.size > 120 * 1024 * 1024) { // 120MB limit
            displayErrorMessage('Processed video exceeds 100MB limit. Please use a smaller video file.');
            setIsProcessingMedia(false);
            return;
          }
          
          processedVideoFiles = [trimmedVideo];
        } else {
          // Video is under 120 seconds, just check final size
          if (videoFile.size > 120 * 1024 * 1024) { // 120MB limit
            displayErrorMessage('Video size must be less than 100MB');
            setIsProcessingMedia(false);
            return;
          }
          
          processedVideoFiles = [videoFile];
        }
      } catch (error) {
        console.error("Error processing video:", error);
        displayErrorMessage('Error processing video. Please try a different file.');
        setIsProcessingMedia(false);
        return;
      }
    }

    // Create preview URLs
    const newPreviewUrls = [];
    for (const file of [...processedVideoFiles, ...imageFiles]) {
      newPreviewUrls.push(URL.createObjectURL(file));
    }
    
    setMediaFiles(prevFiles => [...prevFiles, ...processedVideoFiles, ...imageFiles]);
    setMediaPreviewUrls(prevUrls => [...prevUrls, ...newPreviewUrls]);
    setIsProcessingMedia(false);
  };

  // Remove a media file
  const handleRemoveMedia = (index) => {
    // Revoke object URL to avoid memory leaks
    URL.revokeObjectURL(mediaPreviewUrls[index]);
    
    setMediaFiles(prevFiles => prevFiles.filter((_, i) => i !== index));
    setMediaPreviewUrls(prevUrls => prevUrls.filter((_, i) => i !== index));
  };  // Process and prepare for community selection or direct submission
  const handleProceedToSubmit = async () => {
    if ((!text || text.trim() === '') && mediaFiles.length === 0) {
      displayErrorMessage('Please add some text or media to your post');
      return;
    }
    
    // Check character limit
    if (text.length > 2000) {
      displayErrorMessage('Post text cannot exceed 2000 characters');
      return;
    }

    // If posting directly to a community, skip community selection and submit directly
    if (isDirectCommunityPost && communityId) {
      console.log('[DEBUG] Direct community post, submitting directly to community:', communityId);
      await handleSubmitPost([communityId], true); // Pass isDirectCommunityPost=true
      return;
    }

    // For normal create post flow, fetch user communities and show selector
    console.log('[DEBUG] Normal create post flow - fetching user communities...');
    const availableCommunities = await fetchUserCommunities();
    
    console.log('[DEBUG] Available communities:', availableCommunities);
    // If user has communities they can post in, show community selector
    if (availableCommunities.length > 0) {
      console.log('[DEBUG] Showing community selector for normal flow');
      setShowCommunitySelector(true);
    } else {
      console.log('[DEBUG] No communities available, submitting as profile-only post');
      // If no communities, submit directly as profile-only post
      await handleSubmitPost([], false); // Pass isDirectCommunityPost=false
    }
  };  // Handle post submission (AI will detect categories automatically)
  const handleSubmitPost = async (selectedCommunityIds = [], isDirectPost = false) => {
    try {
      setIsSubmitting(true);
      dispatch(setIsPosting(true)); // Set uploading state to true
      
      const formData = new FormData();
      formData.append('content', text);
      formData.append('hashtags', JSON.stringify(extractTags(text, '#')));
      formData.append('mentions', JSON.stringify(extractTags(text, '@')));
      formData.append('selectedCommunities', JSON.stringify(selectedCommunityIds));
      formData.append('isDirectCommunityPost', isDirectPost.toString());
      
      console.log('[DEBUG] Submitting post with:', {
        selectedCommunityIds,
        isDirectCommunityPost: isDirectPost,
        communityId: isDirectCommunityPost ? communityId : null
      });
      
      // No need to append categories - AI will detect them
      
      // Add media files
      mediaFiles.forEach(file => {
        if (file.type.startsWith('image/')) {
          formData.append('postImages', file);
        } else if (file.type.startsWith('video/')) {
          formData.append('postVideos', file);
        }
      });

      const response = await axios.post(`${api}/post/create-post`, formData, {
        withCredentials: true,
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      if (response.status === 201) {
        // Show success message
        setShowSuccessMessage(true);
        setTimeout(() => setShowSuccessMessage(false), 2000);
        
        // Clear form
        setText('');
        setMediaFiles([]);
        setMediaPreviewUrls([]);
      }
      
      // Reset posting state
      dispatch(setIsPosting(false));
      
      // Refresh profile data to include new post
      dispatch(fetchProfileInfo({ forceRefresh: true }))
        .then((profileResponse) => {
          if (profileResponse.payload?.id) {
            dispatch(fetchUserPosts(profileResponse.payload.id));
          }
        });
      
      // Navigate to home after delay
      setTimeout(() => {
        navigate('/');
      }, 500);
      
    } catch (error) {
      console.error('Error creating post:', error);
      displayErrorMessage(error.response?.data?.error || 'Error creating post');
      // Reset posting state on error
      dispatch(setIsPosting(false));
    } finally {
      setIsSubmitting(false);
    }  };

  // Community selection component
  const CommunitySelector = () => {
    console.log('[DEBUG] CommunitySelector rendered with communities:', userCommunities);
      const handleCommunityToggle = (communityId) => {
      setSelectedCommunities(prev => {
        if (prev.includes(communityId)) {
          // If unchecking this community, remove it from selection
          return prev.filter(id => id !== communityId);
        } else {
          // If checking this community, add it to selection
          // This automatically deselects "don't post" option since we now have communities selected
          return [...prev, communityId];
        }
      });
    };    const handleSubmitWithCommunities = async () => {
      console.log('[DEBUG] Normal flow - submitting with communities:', selectedCommunities);
      setShowCommunitySelector(false);
      await handleSubmitPost(selectedCommunities, false); // isDirectCommunityPost=false for normal flow
    };

    const handleSkipCommunities = async () => {
      console.log('[DEBUG] Normal flow - skipping communities (profile-only post)');
      setShowCommunitySelector(false);
      await handleSubmitPost([], false); // isDirectCommunityPost=false, no communities
    };

    return (
      <div className="md:min-h-screen max-md:min-h-[80vh] bg-[#0a0a0a] text-white md:p-4 p-2 pt-3 md:pt-8">
        <div className="max-w-[640px] mx-auto bg-[#121212] rounded-xl shadow-lg overflow-hidden flex flex-col h-[calc(100vh-80px)]">
          {/* Header */}
          <div className="flex items-center justify-between max-md:px-4 max-md:py-2 px-6 py-4 border-b border-gray-800">
            <h1 className="text-xl font-bold">Post in Community</h1>
            <button 
              onClick={() => setShowCommunitySelector(false)}
              className="w-8 h-8 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-800 hover:text-white transition-colors"
            >
              <FaXmark size={24}/>
            </button>
          </div>

          {/* Content */}
          <div className="p-6 max-md:px-4 flex-1 overflow-y-auto">
            <p className="text-gray-400 mb-6">Select communities where you want to share this post:</p>
            
            {loadingCommunities ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
              </div>
            ) : (
              <div className="space-y-3">                {/* Don't post in any community option */}
                <label className={`flex items-center space-x-3 p-3 rounded-lg cursor-pointer transition-all duration-200 border-2 ${
                  selectedCommunities.length === 0 
                    ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/20' 
                    : 'border-gray-600 hover:border-gray-500 hover:bg-gray-800/50'
                }`}>                  <input
                    type="checkbox"
                    checked={selectedCommunities.length === 0}
                    onChange={() => {
                      // When clicking "don't post", clear all selected communities
                      setSelectedCommunities([]);
                    }}
                    className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 focus:ring-blue-500"
                  />
                  <div className="flex items-center space-x-3">
                    <div className="w-10 h-10 bg-gray-600 rounded-full flex items-center justify-center">
                      <FaXmark className="text-gray-400" size={16} />
                    </div>
                    <span className="text-white">Don't post in any community</span>
                  </div>
                </label>

                {/* Community list */}                {userCommunities.map((community) => (
                  <label key={community.id} className={`flex items-center space-x-3 p-3 rounded-lg cursor-pointer transition-all duration-200 border-2 ${
                    selectedCommunities.includes(community.id)
                      ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/20'
                      : 'border-gray-600 hover:border-gray-500 hover:bg-gray-800/50'
                  }`}>
                    <input
                      type="checkbox"
                      checked={selectedCommunities.includes(community.id)}
                      onChange={() => handleCommunityToggle(community.id)}
                      className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 focus:ring-blue-500"
                    />
                    <div className="flex items-center space-x-3 flex-1">
                      <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                        {community.profile_icon ? (
                          <img
                            src={`${cloud}/cloudofscubiee/communityProfile/${community.profile_icon}`}
                            alt={community.name}
                            className="w-full h-full rounded-full object-cover"
                          />
                        ) : (
                          <FaUsers className="w-5 h-5 text-white" />
                        )}
                      </div>
                      <div>
                        <p className="text-white font-medium">{community.name}</p>
                        <p className="text-gray-400 text-sm">{community.member_count} members</p>
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-800 flex items-center justify-between">
            <button 
              onClick={handleSkipCommunities}
              className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
              disabled={isSubmitting}
            >
              Skip
            </button>
            <button 
              onClick={handleSubmitWithCommunities}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-full font-medium flex items-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <div className="flex items-center">
                  <div className="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-white mr-2"></div>
                  Creating Post...
                </div>
              ) : (
                <>
                  Post {selectedCommunities.length > 0 && `(${selectedCommunities.length} ${selectedCommunities.length === 1 ? 'community' : 'communities'})`}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  };

  // If showing community selector, render it
  if (showCommunitySelector) {
    return <CommunitySelector />;
  }

  // Remove category selector logic - AI handles categories now

  return (
    <div className="md:min-h-screen max-md:min-h-[80vh] bg-[#0a0a0a] text-white md:p-4 p-2 pt-3 md:pt-8">
      {/* Add Success Message */}
      {showSuccessMessage && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-6 py-3 rounded-md z-[60] font-medium shadow-lg">
          Post created successfully
        </div>
      )}
      
      {/* Centered Error Message Overlay */}
      {showError && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="bg-black bg-opacity-60 absolute inset-0"></div>
          <div className="bg-red-800 text-white px-6 py-4 rounded-lg max-w-xs mx-auto z-10 shadow-lg text-center">
            <p className="font-medium">{errorMessage}</p>
          </div>
        </div>
      )}
      
      <div className="max-w-[640px] mx-auto bg-[#121212] rounded-xl shadow-lg overflow-hidden flex flex-col h-[calc(100vh-80px)]">        {/* Header area with close button - fixed */}
        <div className="flex items-center justify-between max-md:px-4 max-md:py-2 px-6 py-4 border-b border-gray-800">
          {isDirectCommunityPost && targetCommunity ? (
            <div className="flex items-center space-x-3">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                {targetCommunity.profile_icon ? (
                  <img
                    src={`${cloud}/cloudofscubiee/communityProfile/${targetCommunity.profile_icon}`}
                    alt={targetCommunity.name}
                    className="w-full h-full rounded-full object-cover"
                  />
                ) : (
                  <FaUsers className="w-4 h-4 text-white" />
                )}
              </div>
              <div>
                <h1 className="text-xl font-bold">Post in Community</h1>
                <p className="text-sm text-gray-400">{targetCommunity.name}</p>
              </div>
            </div>
          ) : (
            <h1 className="text-xl font-bold">Create Post</h1>
          )}
          <button 
            onClick={() => navigate('/')}
            className="w-8 h-8 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-800 hover:text-white transition-colors"
          >
            <FaXmark size={24}/>
          </button>
        </div>
        
        {/* Content area - single scrollable container for both text and media */}
        <div className="p-6  max-md:px-2 flex-1 overflow-y-auto custom-scrollbar">
          {/* Error message display */}
          {showError && (
            <div className="bg-red-900/30 border border-red-800 text-white px-4 py-2 mb-4 rounded-md">
              {errorMessage}
            </div>
          )}
          
          {/* Text area for post content - at the top */}
          <div className="mb-4 relative">
            <textarea
              ref={textAreaRef}
              placeholder="What's happening?"
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="w-full p-2 bg-transparent text-white mb-2 focus:outline-none resize-none min-h-[120px] placeholder-gray-500"
              maxLength={2000}
            />
            <div className="absolute -bottom-1 right-6 text-sm text-gray-500">
              {charCount}/2000
            </div>
          </div>
          
          {/* Media preview section - with custom layout based on number of images */}
          {isProcessingMedia ? (
            <div className="mb-6 w-full h-40 border-2 border-gray-600 rounded-xl flex flex-col items-center justify-center">
              <div className="flex items-center justify-center mb-3">
                <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
              </div>
              <p className="text-gray-300">Processing media...</p>
            </div>
          ) : mediaPreviewUrls.length > 0 ? (
            <div className="mb-6">
              {/* First display videos - each in its own row */}
              {mediaFiles.map((file, index) => 
                file.type.startsWith('video/') && (
                  <div key={`video-${index}`} className="relative group w-full mb-2">
                    <video 
                      src={mediaPreviewUrls[index]} 
                      controls 
                      className="w-full rounded-lg max-h-[500px] object-contain" 
                    />
                    <button 
                      onClick={() => handleRemoveMedia(index)}
                      className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <FaXmark className="text-sm" />
                    </button>
                  </div>
                )
              )}
              
              {/* Images: horizontal scroll for mobile, grid for desktop */}
              {(() => {
                const imageFiles = mediaFiles.filter(file => file.type.startsWith('image/'));
                const imageIndexes = mediaFiles.map((file, i) => 
                  file.type.startsWith('image/') ? i : -1).filter(i => i !== -1);

                if (imageFiles.length === 0) {
                  return null;
                }

                // Mobile: horizontal scroll for multiple images
                if (window.innerWidth < 768) {
                  if (imageFiles.length === 1) {
                    const index = imageIndexes[0];
                    return (
                      <div className="relative group w-full h-full">
                        <img 
                          src={mediaPreviewUrls[index]} 
                          alt="Preview" 
                          className="w-full h-full object-cover rounded-lg"
                        />
                        <button 
                          onClick={() => handleRemoveMedia(index)}
                          className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <FaXmark className="text-sm" />
                        </button>
                      </div>
                    );
                  }
                  // Horizontal scroll for multiple images
                  return (
                    <HorizontalImageScroll
                      imageFiles={imageFiles}
                      imageIndexes={imageIndexes}
                      mediaPreviewUrls={mediaPreviewUrls}
                      handleRemoveMedia={handleRemoveMedia}
                    />
                  );
                }

                // Desktop: grid layouts
                if (imageFiles.length === 1) {
                  const index = imageIndexes[0];
                  return (
                    <div className="relative group w-full h-full">
                      <img 
                        src={mediaPreviewUrls[index]} 
                        alt="Preview" 
                        className="w-full h-full object-cover rounded-lg"
                      />
                      <button 
                        onClick={() => handleRemoveMedia(index)}
                        className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <FaXmark className="text-sm" />
                      </button>
                    </div>
                  );
                } else if (imageFiles.length === 2) {
                  return (
                    <div className="grid grid-cols-2 gap-2">
                      {imageIndexes.map((index, i) => (
                        <div key={`img-${i}`} className="relative group aspect-square w-full h-full">
                          <img 
                            src={mediaPreviewUrls[index]} 
                            alt={`Preview ${i}`} 
                            className="w-full h-full object-cover rounded-lg"
                          />
                          <button 
                            onClick={() => handleRemoveMedia(index)}
                            className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <FaXmark className="text-sm" />
                          </button>
                        </div>
                      ))}
                    </div>
                  );
                } else if (imageFiles.length === 3) {
                  return (
                    <div className="grid grid-cols-2 gap-2">
                      {/* First column - tall image that spans full height */}
                      <div className="relative group row-span-2 h-full">
                        <div className="w-full h-full aspect-[1/2]">
                          <img 
                            src={mediaPreviewUrls[imageIndexes[0]]} 
                            alt="Preview 0" 
                            className="w-full h-full object-cover rounded-lg"
                          />
                          <button 
                            onClick={() => handleRemoveMedia(imageIndexes[0])}
                            className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <FaXmark className="text-sm" />
                          </button>
                        </div>
                      </div>
                      {/* Second column - two stacked images */}
                      <div className="flex flex-col gap-2 h-full">
                        <div className="relative group flex-1">
                          <div className="aspect-square w-full h-full">
                            <img 
                              src={mediaPreviewUrls[imageIndexes[1]]} 
                              alt="Preview 1" 
                              className="w-full h-full object-cover rounded-lg"
                            />
                            <button 
                              onClick={() => handleRemoveMedia(imageIndexes[1])}
                              className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                              <FaXmark className="text-sm" />
                            </button>
                          </div>
                        </div>
                        <div className="relative group flex-1">
                          <div className="aspect-square w-full h-full">
                            <img 
                              src={mediaPreviewUrls[imageIndexes[2]]} 
                              alt="Preview 2" 
                              className="w-full h-full object-cover rounded-lg"
                            />
                            <button 
                              onClick={() => handleRemoveMedia(imageIndexes[2])}
                              className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                            >
                              <FaXmark className="text-sm" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                } else if (imageFiles.length === 4) {
                  return (
                    <div className="grid grid-cols-2 gap-2">
                      {imageIndexes.map((index, i) => (
                        <div key={`img-${i}`} className="relative group aspect-square w-full h-full">
                          <img 
                            src={mediaPreviewUrls[index]} 
                            alt={`Preview ${i}`} 
                            className="w-full h-full object-cover rounded-lg"
                          />
                          <button 
                            onClick={() => handleRemoveMedia(index)}
                            className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <FaXmark className="text-sm" />
                          </button>
                        </div>
                      ))}
                    </div>
                  );
                }
              })()}
            </div>
          ) : (
            /* Empty state - Media upload area */
            <div className="mb-6">
              <div 
                onClick={handleFileSelect}
                className="w-full h-40 border-2 border-dashed border-gray-600 rounded-xl flex flex-col items-center justify-center cursor-pointer hover:border-gray-500 transition-colors"
              >
                <div className="bg-gray-300 w-12 h-12 rounded-full flex items-center justify-center mb-3">
                  <FaPlus className="text-gray-700" />
                </div>
                <p className="text-gray-400">Add photos or video</p>
                <p className="text-gray-500 text-xs mt-2">Supported formats: JPG, JPEG, PNG, MP4</p>
              </div>
            </div>
          )}
        </div>
        
        {/* Footer with action buttons - fixed */}
        <div className="px-6 py-4 border-t border-gray-800 flex items-center justify-between mt-auto">
          {/* Single media selector button */}
          <div className="relative">
            <button 
              onClick={handleFileSelect}
              className="w-10 h-10 flex items-center justify-center bg-gray-300 hover:bg-gray-400 rounded-full text-gray-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label="Add media"
              disabled={isProcessingMedia}
            >
              {isProcessingMedia ? (
                <div className="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-gray-700"></div>
              ) : (
                <FaPlus />
              )}
            </button>
            
            {/* Hidden unified file input */}
            <input 
              type="file"
              ref={fileInputRef}
              onChange={handleMediaChange}
              accept="image/jpeg,image/jpg,image/png,video/mp4"
              multiple
              className="hidden"
            />
          </div>            {/* Post button */}
          <button 
            onClick={handleProceedToSubmit}
            className="px-6 py-2 bg-gray-300 hover:bg-gray-400 text-gray-800 rounded-full font-medium flex items-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isSubmitting || isProcessingMedia || (!text.trim() && mediaFiles.length === 0)}
          >
            {isSubmitting ? (
              <div className="flex items-center">
                <div className="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-gray-800 mr-2"></div>
                {isDirectCommunityPost ? 'Posting...' : 'Creating Post...'}
              </div>
            ) : (
              <>
                {isDirectCommunityPost ? 'Post' : 'Post'}
                <FaArrowRightLong className="ml-2" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export default CreatePost;