import React, { useState, useEffect, useRef, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import axios from 'axios';
import { FaImage, FaVideo, FaXmark, FaArrowRightLong, FaPlus, FaChevronLeft, FaChevronRight } from 'react-icons/fa6';
import { setShowCategorySelector, setFormData, setFormType } from '../Slices/WidgetSlice';
import { setIsPosting } from '../Slices/UserSlice';
import CuisineSelector from '../components/postSelection';
import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import { fetchProfileInfo, fetchUserShorts } from '../Slices/profileSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

// Update the MediaPreview component to include better error handling
const MediaPreview = memo(({ item, onRemove, index }) => {
  const [error, setError] = useState(false);
  
  if (!item) return null;
  
  const isImage = item.type.startsWith('image/');
  
  if (error) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-800 relative">
        <p className="text-gray-400">Failed to load media</p>
        {onRemove && (
          <button 
            onClick={() => onRemove(index)}
            className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full"
          >
            <FaXmark className="text-sm" />
          </button>
        )}
      </div>
    );
  }
  
  return (
    <div className="relative w-full h-full">
      {isImage ? (
        // Use the dataUrl for images instead of blob URL
        <img 
          src={item.dataUrl || item.previewUrl}
          alt={`Media preview ${index + 1}`} 
          className="w-full h-full object-cover"
          onError={() => setError(true)}
        />
      ) : (
        <video 
          src={item.previewUrl}
          controls 
          className="w-full h-full object-cover"
          onError={() => setError(true)}
        />
      )}
      
      {onRemove && (
        <button 
          onClick={() => onRemove(index)}
          className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full"
        >
          <FaXmark className="text-sm" />
        </button>
      )}
    </div>
  );
});

function CreateShort() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  
  // State
  const [content, setContent] = useState('');
  const [mediaItems, setMediaItems] = useState([]); // Array of media item objects with file and preview URL
  const [currentMediaIndex, setCurrentMediaIndex] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showMediaSelector, setShowMediaSelector] = useState(false);
  const [charCount, setCharCount] = useState(0);
  const [touchStart, setTouchStart] = useState(0);
  const [touchEnd, setTouchEnd] = useState(0);
  const [ffmpegLoaded, setFfmpegLoaded] = useState(false);
  const [ffmpeg] = useState(() => new FFmpeg());
  const [errorMessage, setErrorMessage] = useState("");
  const [isProcessingMedia, setIsProcessingMedia] = useState(false);
  const [showError, setShowError] = useState(false);
  const [showSuccessMessage, setShowSuccessMessage] = useState(false);
  
  // Refs
  const fileInputRef = useRef(null);
  const textAreaRef = useRef(null);
  const mediaSelectorRef = useRef(null);
  const sliderRef = useRef(null);
  
  // Redux state
  const showCategorySelector = useSelector((state) => state.widget.showCategorySelector);

  // Auto resize textarea
  useEffect(() => {
    if (textAreaRef.current) {
      textAreaRef.current.style.height = 'auto';
      textAreaRef.current.style.height = `${Math.min(textAreaRef.current.scrollHeight, 300)}px`;
    }
    
    // Update character count
    setCharCount(content.length);
  }, [content]);

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

  // Cleanup preview URLs on unmount
  useEffect(() => {
    return () => {
      mediaItems.forEach(item => {
        if (item.previewUrl && item.previewUrl.startsWith('blob:')) {
          try {
            URL.revokeObjectURL(item.previewUrl);
          } catch (err) {
            console.error("Error revoking object URL:", err);
          }
        }
      });
    };
  }, [mediaItems]);

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

  const handleTextChange = (e) => {
    setContent(e.target.value);
  };

  // Toggle media selector
  const toggleMediaSelector = () => {
    setShowMediaSelector(!showMediaSelector);
  };

  // Handle file selection
  const handleFileSelect = () => {
    fileInputRef.current.click();
  };

  // Helper function to convert file to dataURL
  const fileToDataUrl = (file) => {
    return new Promise((resolve, reject) => {
      // Only process images - videos will still use blob URLs
      if (!file.type.startsWith('image/')) {
        resolve(null);
        return;
      }
      
      const reader = new FileReader();
      
      reader.onload = () => {
        resolve(reader.result);
      };
      
      reader.onerror = () => {
        console.error('Error reading file');
        reject(new Error('Error reading file'));
      };
      
      reader.readAsDataURL(file);
    });
  };

  // Helper function to validate file type
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

  // Video trimming function
  const trimVideo = async (file, startTime = "0", duration = "60") => {
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
      // Create unique filenames
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

  // Update media change handler to use base64 for images
  const handleMediaChange = async (e) => {
    const files = Array.from(e.target.files);
    if (!files.length) return;
    
    setIsProcessingMedia(true);

    // Check if we've reached the maximum number of media items (4)
    if (mediaItems.length + files.length > 4) {
      displayErrorMessage('Maximum 4 media items allowed');
      setIsProcessingMedia(false);
      return;
    }
    
    // Check if adding a video when one already exists
    const existingVideo = mediaItems.find(item => item.type.startsWith('video/'));
    const newVideoFiles = files.filter(file => file.type.startsWith('video/'));
    
    if (existingVideo && newVideoFiles.length > 0) {
      displayErrorMessage('Only one video allowed per short');
      setIsProcessingMedia(false);
      return;
    }
    
    // Validate file types
    const invalidFiles = files.filter(file => !isValidFileType(file));
    if (invalidFiles.length > 0) {
      displayErrorMessage('Only JPG, JPEG, PNG images and MP4 videos are allowed');
      setIsProcessingMedia(false);
      return;
    }
    
    try {
      // Process each file - with separate handling for images and videos
      const processedMediaPromises = files.map(async (file) => {
        const uniqueId = `media-${Date.now()}-${Math.random().toString(36).substring(2, 10)}`;
        
        // Handle image files
        if (file.type.startsWith('image/')) {
          // Check image size (15MB limit)
          if (file.size > 15 * 1024 * 1024) {
            throw new Error('Image size must be less than 15MB');
          }
          
          // Convert image to base64 data URL
          const dataUrl = await fileToDataUrl(file);
          const previewUrl = URL.createObjectURL(file);
          
          return {
            id: uniqueId,
            file,
            type: file.type,
            dataUrl,
            previewUrl,
            timestamp: Date.now()
          };
        } 
        // Handle video files
        else if (file.type.startsWith('video/')) {
          // Initial size check
          if (file.size > 1024 * 1024 * 1024) { // 1GB pre-processing limit
            throw new Error('Video file is too large (max 1GB)');
          }
          
          // Create video element to check duration
          const video = document.createElement('video');
          video.preload = 'metadata';
          
          // Return a promise that resolves with the processed video
          await new Promise((resolve, reject) => {
            video.onloadedmetadata = resolve;
            video.onerror = reject;
            video.src = URL.createObjectURL(file);
          });
          
          // Revoke the URL to avoid memory leaks
          const videoObjectUrl = video.src;
          setTimeout(() => URL.revokeObjectURL(videoObjectUrl), 100);
          
          let processedFile = file;
          
          // Check if video needs trimming (longer than 60 seconds)
          if (video.duration > 60) {
            const trimmedVideo = await trimVideo(file);
            if (!trimmedVideo) {
              throw new Error('Failed to process video');
            }
            
            processedFile = trimmedVideo;
          }
          
          // Final size check after processing
          if (processedFile.size > 100 * 1024 * 1024) {
            throw new Error('Video exceeds 100MB limit after processing');
          }
          
          // Create blob URL for preview
          const previewUrl = URL.createObjectURL(processedFile);
          
          return {
            id: uniqueId,
            file: processedFile,
            type: processedFile.type,
            dataUrl: null, // No data URL for videos
            previewUrl,
            timestamp: Date.now()
          };
        } else {
          throw new Error('Unsupported file type');
        }
      });
      
      // Wait for all files to be processed
      const processedMediaItems = await Promise.all(processedMediaPromises);
      
      // Add the new media items to state
      setMediaItems(prevItems => {
        const updatedItems = [...prevItems, ...processedMediaItems];
        
        // If this is first upload, set index to 0
        if (prevItems.length === 0) {
          setTimeout(() => setCurrentMediaIndex(0), 0);
        }
        
        return updatedItems;
      });
    } catch (error) {
      displayErrorMessage(error.message || 'Error processing media files');
    } finally {
      setIsProcessingMedia(false);
    }
  };

  // Improved remove media function
  const handleRemoveMedia = (index) => {
    setMediaItems(prevItems => {
      const itemToRemove = prevItems[index];
      const newItems = prevItems.filter((_, i) => i !== index);
      
      // Revoke blob URL if it exists (mainly for videos)
      if (itemToRemove && itemToRemove.previewUrl) {
        try {
          // Only revoke if it's a blob URL (starts with blob:)
          if (itemToRemove.previewUrl.startsWith('blob:')) {
            setTimeout(() => {
              URL.revokeObjectURL(itemToRemove.previewUrl);
            }, 100);
          }
        } catch (err) {
          console.error('Error revoking URL:', err);
        }
      }
      
      // Adjust current index if needed
      if (newItems.length === 0) {
        setCurrentMediaIndex(0);
      } else if (index <= currentMediaIndex) {
        const newIndex = Math.max(0, currentMediaIndex - 1);
        setCurrentMediaIndex(newIndex);
      }
      
      return newItems;
    });
  };

  const goToPrevMedia = () => {
    if (currentMediaIndex > 0) {
      setCurrentMediaIndex(currentMediaIndex - 1);
    }
  };

  const goToNextMedia = () => {
    if (currentMediaIndex < mediaItems.length - 1) {
      setCurrentMediaIndex(currentMediaIndex + 1);
    }
  };

  // Swipe handlers for touch devices
  const handleTouchStart = (e) => {
    setTouchStart(e.targetTouches[0].clientX);
  };
  
  const handleTouchMove = (e) => {
    setTouchEnd(e.targetTouches[0].clientX);
  };
  
  const handleTouchEnd = () => {
    if (touchStart - touchEnd > 50) {
      // Swipe left, go to next
      goToNextMedia();
    }
    
    if (touchStart - touchEnd < -50) {
      // Swipe right, go to previous
      goToPrevMedia();
    }
  };

  // Extract hashtags and mentions from text
  const extractTags = (text, symbol) => {
    const regex = new RegExp(`\\${symbol}[A-Za-z0-9_]+`, 'g');
    return text.match(regex) || [];
  };

  const handleProceedToCategories = () => {
    if (mediaItems.length === 0) {
      displayErrorMessage('Please add at least one photo or video');
      return;
    }
    
    // Check if content exceeds character limit
    if (content.length > 350) {
      displayErrorMessage('Content exceeds maximum character limit (350)');
      return;
    }

    const hashtags = extractTags(content, '#');
    const mentions = extractTags(content, '@');

    // Store form data in Redux
    const formDataObj = {
      content,
      mediaFiles: mediaItems.map(item => item.file),
      hashtags,
      mentions
    };

    dispatch(setFormData(formDataObj));
    dispatch(setFormType('short'));
    dispatch(setShowCategorySelector(true));
  };
  const handleSubmitWithCategories = async (selectedCategories) => {
    try {
      setIsSubmitting(true);
      dispatch(setIsPosting(true)); // Set uploading state to true
      
      const formData = new FormData();
      formData.append('content', content);
      formData.append('hashtags', JSON.stringify(extractTags(content, '#')));
      formData.append('mentions', JSON.stringify(extractTags(content, '@')));
      formData.append('categories', JSON.stringify(selectedCategories));
      
      // Append multiple media files
      mediaItems.forEach((item, index) => {
        formData.append('media', item.file);
      });
      
      const response = await axios.post(`${api}/post/create-short`, formData, {
        withCredentials: true,
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
        // Show success message
      setShowSuccessMessage(true);
      setTimeout(() => setShowSuccessMessage(false), 2000);
      
      // Reset form
      setContent('');
      setMediaItems([]);
      setCurrentMediaIndex(0);
      dispatch(setFormData(null));
      dispatch(setShowCategorySelector(false));
      
      // Reset posting state
      dispatch(setIsPosting(false));
      
      // Refresh profile data to include new short
      dispatch(fetchProfileInfo({ forceRefresh: true }))
        .then((profileResponse) => {
          if (profileResponse.payload?.id) {
            dispatch(fetchUserShorts(profileResponse.payload.id));
          }
        });
      
      // Navigate to home after delay
      setTimeout(() => {
        navigate('/');
      }, 500);
      
    } catch (error) {
      console.error('Error creating short:', error);
      displayErrorMessage(error.response?.data?.error || 'Error creating short');
      // Reset posting state on error
      dispatch(setIsPosting(false));
    } finally {
      setIsSubmitting(false);
    }
  };

  // If showing category selector, render CuisineSelector component
  if (showCategorySelector) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white">
        <CuisineSelector onSubmitCategories={handleSubmitWithCategories} isSubmitting={isSubmitting} />
      </div>
    );
  }

  return (
    <div className="md:min-h-screen max-md:min-h-[80vh] bg-[#0a0a0a] text-white md:p-4 p-2 pt-3 ">
      <div className="max-w-md mx-auto bg-[#121212] rounded-xl shadow-lg overflow-hidden flex flex-col md:h-[calc(100vh-40px)] max-md:h-[calc(100vh-80px)]">
        {/* Header area with close button - fixed */}
        <div className="flex items-center justify-between max-md:px-4 max-md:py-2 px-6 py-4 border-b border-gray-800">
          <h1 className="text-xl font-bold">Create Short</h1>
          <button 
            onClick={() => navigate('/')}
            className="w-10 h-10 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-800 hover:text-white transition-colors"
          >
            <FaXmark size={24}/>
          </button>
        </div>
        
        {/* Content area - single scrollable container for both media and text */}
        <div className="p-6 max-md:px-4 flex-1 overflow-y-auto custom-scrollbar">
          {/* Error message display */}
          {showError && (
            <div className="bg-red-900/30 border border-red-800 text-white px-4 py-2 mb-4 rounded-md">
              {errorMessage}
            </div>
          )}
          
          {/* Media preview or upload area - at the top */}
          {mediaItems.length > 0 ? (
            <div className="mb-4 relative">
              {/* Media Slider */}
              <div 
                ref={sliderRef}
                className="w-full h-64 overflow-hidden rounded-xl relative"
                onTouchStart={handleTouchStart}
                onTouchMove={handleTouchMove}
                onTouchEnd={handleTouchEnd}
              >
                {mediaItems.length > 0 && currentMediaIndex < mediaItems.length ? (
                  <MediaPreview 
                    key={mediaItems[currentMediaIndex].id}
                    item={mediaItems[currentMediaIndex]} 
                    index={currentMediaIndex}
                    onRemove={handleRemoveMedia}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center bg-gray-800">
                    <p className="text-gray-400">No media to display</p>
                  </div>
                )}
                
                {/* Navigation buttons (only show if multiple media) */}
                {mediaItems.length > 1 && (
                  <>
                    <button 
                      onClick={goToPrevMedia}
                      className="absolute left-2 top-1/2 -translate-y-1/2 bg-black bg-opacity-50 text-white w-8 h-8 rounded-full flex items-center justify-center hover:bg-opacity-70 transition-all hidden md:flex"
                      disabled={currentMediaIndex === 0}
                    >
                      <FaChevronLeft />
                    </button>
                    <button 
                      onClick={goToNextMedia}
                      className="absolute right-2 top-1/2 -translate-y-1/2 bg-black bg-opacity-50 text-white w-8 h-8 rounded-full flex items-center justify-center hover:bg-opacity-70 transition-all hidden md:flex"
                      disabled={currentMediaIndex === mediaItems.length - 1}
                    >
                      <FaChevronRight />
                    </button>
                  </>
                )}
              </div>
              
              {/* Page indicators */}
              {mediaItems.length > 1 && (
                <div className="flex justify-center mt-2 space-x-1">
                  {mediaItems.map((item, idx) => (
                    <button 
                      key={item.id}
                      onClick={() => setCurrentMediaIndex(idx)}
                      className={`w-2 h-2 rounded-full transition-all ${currentMediaIndex === idx ? 'bg-white w-4' : 'bg-gray-500'}`}
                      aria-label={`Go to slide ${idx + 1}`}
                    />
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="mb-6">
              {isProcessingMedia ? (
                <div className="w-full h-64 border-2 border-gray-600 rounded-xl flex flex-col items-center justify-center">
                  <div className="flex items-center justify-center mb-3">
                    <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
                  </div>
                  <p className="text-gray-300">Processing media...</p>
                </div>
              ) : (
                <div 
                  onClick={handleFileSelect}
                  className="w-full h-64 border-2 border-dashed border-gray-600 rounded-xl flex flex-col items-center justify-center cursor-pointer hover:border-gray-500 transition-colors"
                >
                  <div className="bg-gray-300 w-12 h-12 rounded-full flex items-center justify-center mb-3">
                    <FaPlus className="text-gray-700" />
                  </div>
                  <p className="text-gray-400">Add photos or a video</p>
                  <p className="text-gray-500 text-sm mt-1">Up to 4 media files (max 1 video)</p>
                  <p className="text-gray-500 text-xs mt-2">Supported formats: JPG, JPEG, PNG, MP4</p>
                </div>
              )}
            </div>
          )}
          
          {/* Text area for short content - now at the bottom */}
          <div className="mb-4 relative">
            <textarea
              ref={textAreaRef}
              placeholder="What's happening?"
              value={content}
              onChange={handleTextChange}
              className="w-full p-2 bg-transparent text-white mb-2 focus:outline-none resize-none min-h-[120px] placeholder-gray-500"
              maxLength={350}
            />
            <div className="absolute bottom-2 right-2 text-sm text-gray-500">
              {charCount}/400
            </div>
          </div>
        </div>
        
        {/* Footer with action buttons - fixed */}
        <div className="px-6 py-4 border-t border-gray-800 flex items-center justify-between mt-auto">
          {/* Media button */}
          <div>
            <button 
              onClick={handleFileSelect}
              className={`w-10 h-10 flex items-center justify-center ${mediaItems.length < 4 ? 'bg-gray-300 hover:bg-gray-400 text-gray-700' : 'bg-gray-700 hover:bg-gray-600 text-gray-400'} rounded-full transition-colors`}
              aria-label="Add media"
              disabled={mediaItems.length >= 4 || isProcessingMedia}
            >
              {isProcessingMedia ? (
                <div className="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-gray-700"></div>
              ) : (
                <FaPlus />
              )}
            </button>
            
            {/* Hidden file input */}
            <input 
              type="file"
              ref={fileInputRef}
              onChange={handleMediaChange}
              accept="image/jpeg,image/jpg,image/png,video/mp4"
              className="hidden"
              multiple
            />
          </div>
          
          {/* Post button */}
          <button 
            onClick={handleProceedToCategories}
            className="px-6 py-2 bg-gray-300 hover:bg-gray-400 text-gray-800 rounded-full font-medium flex items-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isSubmitting || isProcessingMedia || mediaItems.length === 0}
          >
            {isSubmitting ? (
              <div className="flex items-center">
                <div className="animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-gray-800 mr-2"></div>
                Processing...
              </div>
            ) : (
              <>
                Next
                <FaArrowRightLong className="ml-2" />
              </>
            )}
          </button>
        </div>
      </div>
      
      {/* Add Success Message */}
      {showSuccessMessage && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-6 py-3 rounded-md z-[60] font-medium shadow-lg">
          Short created successfully
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
    </div>
  );
}

export default CreateShort;