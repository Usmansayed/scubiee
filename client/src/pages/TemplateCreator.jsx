import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaImage, FaXmark, FaChevronLeft, FaChevronRight, FaDownload } from 'react-icons/fa6';

// Utility function to determine text size based on length
const getTextClass = (text, thresholds) => {
  if (!text) return thresholds.small;
  
  const length = text.length;
  if (length < 30) return thresholds.xLarge;
  if (length < 80) return thresholds.large;
  if (length < 150) return thresholds.medium;
  return thresholds.small;
};

// Template 1 - Highlighted Words (previously Template 2)
const HighlightedWordsTemplate = ({ image, text }) => {
  const words = (text || "Your Story Here").split(' ');
  
  const textClass = getTextClass(text, {
    xLarge: "text-3xl md:text-4xl",
    large: "text-2xl md:text-3xl",
    medium: "text-xl md:text-2xl",
    small: "text-lg md:text-xl"
  });
  
  return (
    <div className="relative w-full h-full overflow-hidden">
      {image ? (
        <img src={image} alt="Uploaded" className="w-full h-full object-cover" />
      ) : (
        <div className="absolute inset-0 bg-gray-800"></div>
      )}
      <div className="absolute bottom-0 left-0 right-0 p-8 bg-gradient-to-t from-black to-transparent">
        <p className={`text-white text-left font-light leading-tight ${textClass}`}>
          {words.map((word, index) => (
            <span key={index} className={index % 3 === 0 ? "font-bold text-yellow-400" : ""}>
              {word}{' '}
            </span>
          ))}
        </p>
      </div>
    </div>
  );
};

// Template 2 - Bold Header (previously Template 3) - Modified to display text at bottom with smaller font
const BoldHeaderTemplate = ({ image, text }) => {
  const textClass = getTextClass(text, {
    xLarge: "text-2xl md:text-3xl", // Further reduced 
    large: "text-xl md:text-2xl",   // Further reduced
    medium: "text-lg md:text-xl",   // Further reduced
    small: "text-base md:text-lg"   // Further reduced
  });
  
  return (
    <div className="relative w-full h-full overflow-hidden">
      {image ? (
        <img src={image} alt="Uploaded" className="w-full h-full object-cover" />
      ) : (
        <div className="absolute inset-0 bg-gray-800"></div>
      )}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent flex flex-col items-center justify-end pb-16 px-6">
        <div className="bg-black/70 px-5 py-2 rounded-lg border-l-4 border-red-500 max-w-[95%]">
          <h2 className={`text-white text-center font-extrabold uppercase tracking-wide ${textClass}`}>
            {text || "Your Story Here"}
          </h2>
        </div>
      </div>
    </div>
  );
};

// Template 3 - Gallery Frame (previously Template 4) - Removed white border, positioned text box on left side
const GalleryFrameTemplate = ({ image, text }) => {
  const textClass = getTextClass(text, {
    xLarge: "text-2xl md:text-3xl",
    large: "text-xl md:text-2xl",
    medium: "text-lg md:text-xl",
    small: "text-base md:text-lg"
  });
  
  return (
    <div className="relative w-full h-full overflow-hidden">
      <div className="w-full h-full bg-[#0c0d11]">
        {image ? (
          <div className="w-full h-full relative">
            <img src={image} alt="Uploaded" className="w-full h-full object-cover" />
            <div className="absolute bottom-0 left-0 max-w-[80%] p-4 bg-black/70">
              <p className={`text-white text-left italic font-light ${textClass}`}>
                {text || "Your Story Here"}
              </p>
            </div>
          </div>
        ) : (
          <div className="w-full h-full bg-gray-800"></div>
        )}
      </div>
    </div>
  );
};

// Template 4 - 50/50 Split (New template inspired by Shorts page)
const SplitTemplate = ({ image, text }) => {
  // More aggressive text size reduction based on length for better matching with Shorts UI
  const getTextSizeClass = (text) => {
    if (!text) return "text-xl md:text-2xl";
    
    const length = text.length;
    if (length < 20) return "text-2xl md:text-3xl";
    if (length < 50) return "text-xl md:text-2xl";
    if (length < 100) return "text-lg md:text-xl";
    if (length < 200) return "text-md md:text-lg";
    return "text-sm md:text-base";
  };
  
  const textSizeClass = getTextSizeClass(text);
  
  return (
    <div className="relative w-full h-full overflow-hidden flex flex-col">
      {/* Top 50% for image */}
      <div className="h-[50%] w-full overflow-hidden">
        {image ? (
          <img src={image} alt="Uploaded" className="w-full h-full object-cover rounded-t-2xl" />
        ) : (
          <div className="w-full h-full bg-gray-800 rounded-t-2xl"></div>
        )}
      </div>
      
      {/* Bottom 50% for text - styled to match Shorts page UI */}
      <div className="h-[50%] w-full bg-[#0c0d11] flex flex-col px-3 pt-2">
        <div className="relative flex-1 pr-8">
          <p className={`text-gray-300 max-md mt-1 max-md:text-[16.4px] ${textSizeClass} font-normal`} 
             style={{ fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
            {text || "Your Story Here"}
          </p>
        </div>
        
        {/* Adding interaction icons to match Shorts UI */}
        <div className="absolute right-3 bottom-11 flex flex-col items-center space-y-7">
          <div className="w-7 h-7 rounded-full bg-gray-800 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-white">
              <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
            </svg>
          </div>
          <div className="w-7 h-7 rounded-full bg-gray-800 flex items-center justify-center">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-white">
              <path fillRule="evenodd" d="M4.848 2.771A49.144 49.144 0 0112 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 01-3.476.383.39.39 0 00-.297.17l-2.755 4.133a.75.75 0 01-1.248 0l-2.755-4.133a.39.39 0 00-.297-.17 48.9 48.9 0 01-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97z" clipRule="evenodd" />
            </svg>
          </div>
        </div>
        
        {/* User profile section at bottom */}
        <div className="flex w-[90%] absolute bottom-4 left-0 items-center px-4 pt-2 pb-2">
          <div className="flex items-center">
            <div className="w-9 h-9 rounded-full bg-gray-700"></div>
            <div className="ml-3">
              <p className="text-md font-bold text-white">username</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

function TemplateCreator() {
  const navigate = useNavigate();
  
  // State
  const [image, setImage] = useState(null);
  const [text, setText] = useState('');
  const [charCount, setCharCount] = useState(0);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [currentTemplateIndex, setCurrentTemplateIndex] = useState(0);
  const [showTemplates, setShowTemplates] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  
  // Refs
  const fileInputRef = useRef(null);
  const textAreaRef = useRef(null);
  
  // Templates array - keeping only the requested templates
  const templates = [
    { id: 1, component: HighlightedWordsTemplate, name: "Highlighted Words" },
    { id: 2, component: BoldHeaderTemplate, name: "Bold Header" },
    { id: 3, component: GalleryFrameTemplate, name: "Gallery Frame" },
    { id: 4, component: SplitTemplate, name: "50/50 Split" },
  ];
  
  // Clean up object URL when component unmounts
  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);
  
  // Auto resize textarea
  useEffect(() => {
    if (textAreaRef.current) {
      textAreaRef.current.style.height = 'auto';
      textAreaRef.current.style.height = `${Math.min(textAreaRef.current.scrollHeight, 150)}px`;
    }
    
    // Update character count
    setCharCount(text.length);
  }, [text]);
  
  const handleTextChange = (e) => {
    if (e.target.value.length <= 300) {
      setText(e.target.value);
    }
  };
  
  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setIsUploading(true);
    
    // Validate file type
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    if (!validTypes.includes(file.type)) {
      setErrorMessage('Please upload a JPG or PNG image');
      setIsUploading(false);
      return;
    }
    
    // Validate file size (5MB max)
    if (file.size > 5 * 1024 * 1024) {
      setErrorMessage('Image size must be less than 5MB');
      setIsUploading(false);
      return;
    }
    
    try {
      // Create preview URL
      const objectUrl = URL.createObjectURL(file);
      setPreviewUrl(objectUrl);
      setImage(objectUrl);
      setIsUploading(false);
    } catch (error) {
      setErrorMessage(`Error uploading image: ${error.message}`);
      setIsUploading(false);
    }
  };
  
  const handleFileSelect = () => {
    fileInputRef.current.click();
  };
  
  const handleSubmit = () => {
    if (!image) {
      setErrorMessage('Please upload an image');
      return;
    }
    
    if (text.trim().length === 0) {
      setErrorMessage('Please enter some text');
      return;
    }
    
    // Show the templates in fullscreen directly
    setShowTemplates(true);
    setErrorMessage('');
  };
  
  const handleClear = () => {
    setText('');
    setImage(null);
    setPreviewUrl(null);
    setShowTemplates(false);
    setCharCount(0);
    setErrorMessage('');
    
    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };
  
  const goToPrevTemplate = () => {
    setCurrentTemplateIndex((prevIndex) => 
      prevIndex > 0 ? prevIndex - 1 : templates.length - 1
    );
  };
  
  const goToNextTemplate = () => {
    setCurrentTemplateIndex((prevIndex) => 
      prevIndex < templates.length - 1 ? prevIndex + 1 : 0
    );
  };
  
  // Get current template and adjacent templates
  const currentIndex = currentTemplateIndex;
  const prevIndex = currentIndex > 0 ? currentIndex - 1 : templates.length - 1;
  const nextIndex = currentIndex < templates.length - 1 ? currentIndex + 1 : 0;
  
  const CurrentTemplate = templates[currentIndex].component;
  const PrevTemplate = templates[prevIndex].component;
  const NextTemplate = templates[nextIndex].component;

  // Fullscreen template gallery view
  if (showTemplates) {
    return (
      <div className="fixed inset-0 bg-black z-50 flex flex-col">
        {/* Minimal header */}
        <div className="flex items-center justify-between px-2 py-1 border-b border-gray-800">
          <div className="flex items-center">
            <button 
              onClick={() => setShowTemplates(false)}
              className="mr-2 w-8 h-8 flex items-center justify-center rounded-full bg-gray-800 text-white"
            >
              <FaChevronLeft size={16} />
            </button>
            <span className="text-sm font-medium text-white">
              {templates[currentIndex].name} ({currentIndex + 1}/{templates.length})
            </span>
          </div>
          <button 
            onClick={() => navigate('/')}
            className="w-8 h-8 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-800 hover:text-white"
          >
            <FaXmark size={16} />
          </button>
        </div>
        
        {/* Template Gallery - using full height */}
        <div className="flex-1 flex items-center justify-center bg-[#0a0a0a] relative">
          {/* Main template display */}
          <div className="relative h-full w-full flex items-center justify-center">
            {/* Previous template preview (left side) - styled similar to main but smaller */}
            <div 
              className="hidden md:flex absolute left-2 h-[80%] w-[22%] opacity-40 transform -translate-y-1/2 top-1/2 cursor-pointer hover:opacity-60 transition-opacity items-center justify-center"
              onClick={goToPrevTemplate}
            >
              <div className="h-full aspect-[9/16]">
                <PrevTemplate image={image} text={text} />
              </div>
            </div>
            
            {/* Current template (center, main view) - ensuring 9:16 ratio */}
            <div className="h-[92%] aspect-[9/16] max-w-md">
              <CurrentTemplate image={image} text={text} />
            </div>
            
            {/* Next template preview (right side) - styled similar to main but smaller */}
            <div 
              className="hidden md:flex absolute right-2 h-[80%] w-[22%] opacity-40 transform -translate-y-1/2 top-1/2 cursor-pointer hover:opacity-60 transition-opacity items-center justify-center"
              onClick={goToNextTemplate}
            >
              <div className="h-full aspect-[9/16]">
                <NextTemplate image={image} text={text} />
              </div>
            </div>
            
            {/* Mobile navigation arrows */}
            <button
              onClick={goToPrevTemplate}
              className="md:hidden absolute left-2 top-1/2 transform -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-black/50 text-white z-10"
            >
              <FaChevronLeft size={18} />
            </button>
            <button
              onClick={goToNextTemplate}
              className="md:hidden absolute right-2 top-1/2 transform -translate-y-1/2 w-10 h-10 flex items-center justify-center rounded-full bg-black/50 text-white z-10"
            >
              <FaChevronRight size={18} />
            </button>
          </div>
        </div>
        
        {/* Minimal footer controls */}
        <div className="bg-[#121212] px-3 py-2 flex justify-between items-center">
          <button
            onClick={() => setShowTemplates(false)}
            className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-white text-sm rounded-lg transition-colors"
          >
            Back
          </button>
          
          <div className="flex gap-2">
            <button
              className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-lg flex items-center gap-1.5 transition-colors"
            >
              <FaDownload size={14} />
              <span>Save</span>
            </button>
          </div>
        </div>
      </div>
    );
  }
  
  // Editor view
  return (
    <div className="bg-[#0a0a0a] text-white h-screen">
      <div className="max-w-lg mx-auto bg-[#121212] flex flex-col h-full">
        {/* Minimal header */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800">
          <h1 className="text-lg font-bold">Template Creator</h1>
          <button 
            onClick={() => navigate('/')}
            className="w-8 h-8 flex items-center justify-center rounded-full text-gray-400 hover:bg-gray-800 hover:text-white"
            aria-label="Close"
          >
            <FaXmark size={18} />
          </button>
        </div>
        
        {/* Content area */}
        <div className="p-4 flex-1 overflow-y-auto">
          {/* Error message */}
          {errorMessage && (
            <div className="bg-red-900/30 border border-red-800 text-white px-3 py-2 mb-3 rounded-md text-sm">
              {errorMessage}
            </div>
          )}
          
          <div className="space-y-4">
            {/* Image upload */}
            <div>
              {image ? (
                <div className="mb-3 relative aspect-[9/16] max-h-[400px] mx-auto">
                  <img 
                    src={previewUrl} 
                    alt="Preview" 
                    className="w-full h-full object-cover rounded-lg" 
                  />
                  <button 
                    onClick={() => {
                      setImage(null);
                      setPreviewUrl(null);
                      if (fileInputRef.current) fileInputRef.current.value = '';
                    }}
                    className="absolute top-2 right-2 bg-black bg-opacity-50 text-white p-1.5 rounded-full"
                  >
                    <FaXmark size={14} />
                  </button>
                </div>
              ) : (
                <div>
                  {isUploading ? (
                    <div className="w-full h-64 border-2 border-gray-600 rounded-xl flex flex-col items-center justify-center">
                      <div className="flex items-center justify-center mb-3">
                        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
                      </div>
                      <p className="text-gray-300">Processing image...</p>
                    </div>
                  ) : (
                    <div 
                      onClick={handleFileSelect}
                      className="w-full h-64 border-2 border-dashed border-gray-600 rounded-xl flex flex-col items-center justify-center cursor-pointer hover:border-gray-500 transition-colors"
                    >
                      <div className="bg-gray-300 w-12 h-12 rounded-full flex items-center justify-center mb-3">
                        <FaImage className="text-gray-700" />
                      </div>
                      <p className="text-gray-400">Click to upload an image</p>
                      <p className="text-gray-500 text-xs mt-1">For best results, use a 9:16 ratio image</p>
                    </div>
                  )}
                </div>
              )}
              
              <input 
                type="file"
                ref={fileInputRef}
                onChange={handleImageUpload}
                accept="image/jpeg,image/jpg,image/png"
                className="hidden"
              />
            </div>
            
            {/* Text input */}
            <div className="relative">
              <label className="block text-gray-300 text-sm mb-1">Add Text</label>
              <textarea
                ref={textAreaRef}
                placeholder="Enter your text here (max 300 characters)"
                value={text}
                onChange={handleTextChange}
                className="w-full p-3 bg-[#1a1a1a] text-white rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 resize-none min-h-[100px] placeholder-gray-500"
                maxLength={300}
              />
              <div className="absolute bottom-2 right-3 text-xs text-gray-500">
                {charCount}/300
              </div>
            </div>
            
            {/* Action buttons */}
            <div className="flex gap-3 pt-2">
              <button 
                onClick={handleClear}
                className="flex-1 py-2.5 bg-[#2a2a2a] hover:bg-[#333] text-white rounded-lg transition-colors"
              >
                Clear
              </button>
              <button 
                onClick={handleSubmit}
                className={`flex-1 py-2.5 ${(!image || !text.trim()) ? 'bg-indigo-600/50' : 'bg-indigo-600 hover:bg-indigo-700'} text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2`}
                disabled={!image || !text.trim()}
              >
                <span>Create Templates</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default TemplateCreator;