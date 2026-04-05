import React, { useRef, useState, useEffect } from "react";
import { Stage, Layer, Image, Text, Rect, Transformer, Group, Circle, RegularPolygon } from "react-konva";
import { MdOutlineDriveFolderUpload } from "react-icons/md";
import { IoTextSharp } from "react-icons/io5";
import { FiLink } from "react-icons/fi";
import { VscMention } from "react-icons/vsc";
import "./MEditorWidget.css";
import { UploadCloudIcon } from "lucide-react";
import { LuDownload } from "react-icons/lu";
import { RiDeleteBin6Line } from "react-icons/ri";
import { MdDeleteOutline } from "react-icons/md";
import { RiHashtag } from "react-icons/ri";
import ColorThief from 'colorthief';
import Hammer from 'hammerjs';
import Konva from 'konva';
import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import JSZip from 'jszip';
import { useNavigate } from "react-router-dom";
const api = import.meta.env.VITE_API_URL;
import axios from 'axios';
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import Picker from "emoji-picker-react";
import { BsEmojiSmile } from "react-icons/bs";
import { IoClose } from "react-icons/io5";
import { useSelector, useDispatch } from "react-redux";
import { IoMdClose } from "react-icons/io";
import { MdOutlineNavigateNext } from "react-icons/md";
import { FaChevronRight } from "react-icons/fa6";
import { CircleCheckBig } from 'lucide-react';
import { addCreatedStory } from '../Slices/WidgetSlice';
const cloud = import.meta.env.VITE_CLOUD_URL;

Konva.hitOnDragEnabled = true;
Konva.captureTouchEventsEnabled = true;




const CreateStory = ({file, onClose ,postId}) => {
  const stageRef = useRef(null);
  const fileInputRef = useRef(null);
 const [videoScale, setVideoScale] = useState(1);
  const [images, setImages] = useState([]);
  const [textGroups, setTextGroups] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
const [isTransforming, setIsTransforming] = useState(false);
const [postMediaItems, setPostMediaItems] = useState([]);
const vcloud = import.meta.env.VITE_VIDEO_CLOUD_URL;

  const [showTextOverlay, setShowTextOverlay] = useState(false);
  const [textValue, setTextValue] = useState("");
  const [fontColor, setFontColor] = useState("#ffffff");
  const [backgroundColor, setBackgroundColor] = useState("#000000");
  const [showBackground, setShowBackground] = useState(false);
  const [showMentionOverlay, setShowMentionOverlay] = useState(false);
  const [mentionValue, setMentionValue] = useState("");
  const [showLinkOverlay, setShowLinkOverlay] = useState(false);
  const [linkValue, setLinkValue] = useState("");
  const [hasMedia, setHasMedia] = useState(false);
  const [canvasBgColor, setCanvasBgColor] = useState('#000000');
  const videoRef = useRef(null);
const konvaImageRef = useRef(null);
const [videoFile, setVideoFile] = useState(null);
const [videoPosition, setVideoPosition] = useState({ x: 0, y: 0 });
const [videoTransform, setVideoTransform] = useState({});
const trRef = useRef(null);
const navigate = useNavigate();
const [windowWidth, setWindowWidth] = useState(window.innerWidth);
const [initialRotation, setInitialRotation] = useState(0);
const [initialScale, setInitialScale] = useState({ x: 1, y: 1 });
const [initialDist, setInitialDist] = useState(0);
const [initialAngle, setInitialAngle] = useState(0);
const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
const containerRef = useRef(null);
const [showHashtagOverlay, setShowHashtagOverlay] = useState(false);
const [hashtagValue, setHashtagValue] = useState("");
const [searchResults, setSearchResults] = useState([]);
const [loading, setLoading] = useState(false);
const [videoURL, setVideoURL] = useState(null);
const [isScaled, setIsScaled] = useState(false);
const [imageScaledMap, setImageScaledMap] = useState({});
const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const emojiPickerRef = useRef(null);
  const [showPostOverlay, setShowPostOverlay] = useState(false);
  const [postIdValue, setPostIdValue] = useState("");
  const [postSummary, setPostSummary] = useState(null);
  const [postTransform, setPostTransform] = useState({ x: 50, y: 50, rotation: 0, scaleX: 1, scaleY: 1 });
  const [postThumbnailImage, setPostThumbnailImage] = useState(null);
  const [postProfileImage, setPostProfileImage] = useState(null);
  const widgetStoryPostId = useSelector((state) => state.widget.storyPostId);
  const [creationSuccess, setCreationSuccess] = useState(false);
  const dispatch = useDispatch(); // Add dispatch
  const userData = useSelector((state) => state.user.userData);

  

  // New function to open the overlay
  const openPostOverlay = () => {
    closeAllOverlays();
    setShowPostOverlay(true);
  };

  const addPostSummary = async (id) => {
    try {
      const response = await axios.get(`${api}/post/summary/${id}`, {
        withCredentials: true
      });
      setPostSummary(response.data);
      
      // Handle media array
      if (response.data.media && response.data.media.length > 0) {
        // Process all media items
        const mediaItems = [];
        
        // For each media item, process and add to the array
        for (const mediaItem of response.data.media) {
          const isVideoFile = mediaItem.type === 'video';
          const baseUrl = response.data.isShort 
            ? (isVideoFile ? `${cloud}/cloudofscubiee/shortVideos/` : `${cloud}/cloudofscubiee/shortImages/`)
            : (isVideoFile ? `${cloud}/cloudofscubiee/postVideos/` : `${cloud}/cloudofscubiee/postImages/`);
            
          const mediaUrl = `${baseUrl}${mediaItem.url}`;
          
          // For the first item only, load the thumbnail preview
          if (mediaItems.length === 0) {
            if (isVideoFile) {
              // Video handling - capture first frame for thumbnail
              const video = document.createElement('video');
              video.crossOrigin = "Anonymous";
              video.src = mediaUrl;
              video.muted = true;
              video.playsInline = true;
              
              video.onloadedmetadata = () => {
                video.currentTime = 0.1;
                
                video.onseeked = () => {
                  const canvas = document.createElement('canvas');
                  canvas.width = video.videoWidth;
                  canvas.height = video.videoHeight;
                  const ctx = canvas.getContext('2d');
                  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                  
                  const img = new window.Image();
                  img.crossOrigin = "Anonymous";
                  img.src = canvas.toDataURL('image/png');
                  img.onload = () => setPostThumbnailImage(img);
                };
              };
            } else {
              // Image handling
              const img = new window.Image();
              img.crossOrigin = "Anonymous";
              img.src = mediaUrl;
              img.onload = () => setPostThumbnailImage(img);
            }
          }
          
        // In your addPostSummary function where you create the mediaItems array:
mediaItems.push({
  url: mediaUrl,
  type: isVideoFile ? 'video' : 'image',
  loadedImage: null // Initialize this property
});
        }
        
        // Store processed media items
        setPostMediaItems(mediaItems);
        
      } else if (response.data.thumbnail) {
        // Fallback to thumbnail if media array is not available
        // This is the existing logic
        if (!response.data.isShort) {
          const img = new window.Image();
          img.crossOrigin = "Anonymous";
          img.src = `${cloud}/cloudofscubiee/Postthumbnail/${response.data.thumbnail}`;
          img.onload = () => setPostThumbnailImage(img);
        } else {
          // Your existing short handling code
          const thumbnailExt = response.data.thumbnail.split('.').pop().toLowerCase();
          
          if (['mp4', 'webm', 'mov'].includes(thumbnailExt)) {
            // Video short handling
            const video = document.createElement('video');
            video.crossOrigin = "Anonymous";
            video.src = `${cloud}/cloudofscubiee/shortVideos/${response.data.thumbnail}`;
            video.muted = true;
            video.playsInline = true;
            
            video.onloadedmetadata = () => {
              video.currentTime = 0.1;
              
              video.onseeked = () => {
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                
                const img = new window.Image();
                img.crossOrigin = "Anonymous";
                img.src = canvas.toDataURL('image/png');
                img.onload = () => setPostThumbnailImage(img);
              };
            };
          } else {
            // Image short handling
            const img = new window.Image();
            img.crossOrigin = "Anonymous";
            img.src = `${cloud}/cloudofscubiee/shortImages/${response.data.thumbnail}`;
            img.onload = () => setPostThumbnailImage(img);
          }
        }
      }
      
      // Load profile image - no changes needed here
      if (response.data.author) {
        const profileImg = new window.Image();
        profileImg.crossOrigin = "Anonymous";
        profileImg.onerror = () => {
          profileImg.src = "/logos/DefaultPicture.png";
        };
        profileImg.src = response.data.author.profilePicture ? 
          `${cloud}/cloudofscubiee/profilePic/${response.data.author.profilePicture}` : 
          "/logos/DefaultPicture.png";
        
        profileImg.onload = () => setPostProfileImage(profileImg);
      }
    } catch (error) {
      console.error("Error fetching post summary:", error);
    }
  };
  useEffect(() => {
    if (!file) {
      const activePostId = postId || widgetStoryPostId;
      if (activePostId) {
        setPostIdValue(activePostId);
        addPostSummary(activePostId);
      }
    }
  }, [file, postId, widgetStoryPostId]);

  useEffect(() => {
    if (!file && postId) {
      setPostIdValue(postId);
      addPostSummary();
    }
  }, [file, postId]);

  useEffect(() => {
    if (postSummary && stageSize.width && stageSize.height) {
      // Center the summary (assuming a fixed width of 375 and height of 375*(9/10))
      setPostTransform({
        x: (stageSize.width - 375) / 2,
        y: (stageSize.height - 375 * (9 / 10)) / 2,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
      });
    }
  }, [postSummary, stageSize]);

  useEffect(() => {
    if (!file) return;

    if (file.type.startsWith("image/")) {
      const img = new window.Image();
      img.onload = () => {
        const originalWidth = img.naturalWidth;
        const originalHeight = img.naturalHeight;

        const scale = Math.min(
          stageSize.width / originalWidth,
          stageSize.height / originalHeight
        );

        // Set background color using ColorThief
        const colorThief = new ColorThief();
        const dominantColor = colorThief.getColor(img);
        const rgbColor = `rgb(${dominantColor[0]}, ${dominantColor[1]}, ${dominantColor[2]})`;
        setCanvasBgColor(rgbColor);
        setHasMedia(true);

        const x = (stageSize.width - originalWidth * scale) / 2;
        const y = (stageSize.height - originalHeight * scale) / 2;

        setImages([{
          id: `img_${Date.now()}`,
          image: img,
          file: file,
          x,
          y,
          rotation: 0,
          scaleX: scale,
          scaleY: scale,
          originalWidth,
          originalHeight,
          z_index: 1
        }]);
      };
      img.src = URL.createObjectURL(file);
    } else if (file.type.startsWith("video/")) {
      const video = document.createElement('video');
      video.src = URL.createObjectURL(file);
      
      video.onloadedmetadata = () => {
        const originalWidth = video.videoWidth;
        const originalHeight = video.videoHeight;
        
        const scale = Math.min(
          stageSize.width / originalWidth,
          stageSize.height / originalHeight
        );

        extractFirstFrame(file).then((frameImage) => {
          const colorThief = new ColorThief();
          const dominantColor = colorThief.getColor(frameImage);
          const rgbColor = `rgb(${dominantColor[0]}, ${dominantColor[1]}, ${dominantColor[2]})`;
          setCanvasBgColor(rgbColor);
        });
        setHasMedia(true);

        setVideoFile(file);
        setVideoURL(URL.createObjectURL(file));
        setVideoScale(scale);
      };
    }
  }, [file, stageSize]);


const handleStageClick = (e) => {
  // If the user clicks on an empty area, deselect any selections.
  if (e.target === stageRef.current.getStage()) {
    setSelectedId(null);
  }
};

const toggleEmojiPicker = () => {
  setShowEmojiPicker((prev) => !prev);
};

// When an emoji is selected, append it to the text value
const handleSelectEmoji = (emojiData) => {
  // emojiData.emoji contains the selected emoji
  setTextValue((prev) => prev + emojiData.emoji);
  setShowEmojiPicker(false);
};

// Click outside handler for the emoji picker
useEffect(() => {
  const handleClickOutside = (e) => {
    if (
      emojiPickerRef.current &&
      !emojiPickerRef.current.contains(e.target)
    ) {
      setShowEmojiPicker(false);
    }
  };

  if (showEmojiPicker) {
    document.addEventListener("mousedown", handleClickOutside);
  } else {
    document.removeEventListener("mousedown", handleClickOutside);
  }
  return () =>
    document.removeEventListener("mousedown", handleClickOutside);
}, [showEmojiPicker]);

const getMaxZIndex = () => {
  let max = 0;
  
  // Check video element
  if (videoFile && videoTransform.z_index != null) {
    max = Math.max(max, videoTransform.z_index);
  }
  
  // Check images
  images.forEach(img => {
    max = Math.max(max, img.z_index || 0);
  });
  
  // Check text groups (including mentions, links, hashtags)
  textGroups.forEach(txt => {
    max = Math.max(max, txt.z_index || 0);
  });
  
  return max;
};
const getNextZIndex = () => getMaxZIndex() + 1;



const handleCreateStory = async () => {
  // 1. Guard: ensure there's media (image or video) OR a valid postIdValue.
  if (!hasMedia && !postIdValue) {
    alert("Please upload an image, video, or select a valid post.");
    return;
  }

  try {
    // Hide mention/link/hashtag items temporarily.
    const hiddenItems = textGroups.filter(
      (t) => t.isMention || t.isLink || t.isHashtag
    );
    hiddenItems.forEach((item) => (item.showBackground = false));
    stageRef.current.getStage().batchDraw();

    // 2. Gather metadata for all elements.
    const metadataArray = [];
    let nextZIndex = 1; // lowest z-index for the earliest element

    // If video exists, add the video metadata element.
    if (videoFile) {
      const videoNode = stageRef.current.findOne("#video");
      const offset = videoNode.offset() || { x: 0, y: 0 };
      const rawVideoWidth = videoRef.current
        ? videoRef.current.videoWidth
        : videoTransform.originalWidth;
      const rawVideoHeight = videoRef.current
        ? videoRef.current.videoHeight
        : videoTransform.originalHeight;

      metadataArray.push({
        element_type: "video",
        background_color: null,
        content: videoFile.name,
        position_x: videoNode.x(),
        position_y: videoNode.y(),
        width: rawVideoWidth,
        height: rawVideoHeight,
        rotation: videoNode.rotation(),
        scale: videoNode.scaleX(), // assumes scaleX === scaleY
        isPost: false,
        offset_x: offset.x,
        offset_y: offset.y,
        isVideo: true,
        z_index: nextZIndex++,
      });
    }

    // Handle multiple images.
    if (images.length > 0) {
      images.forEach((image) => {
        const imageNode = stageRef.current.findOne(`#${image.id}`);
        if (!imageNode) return;
        metadataArray.push({
          element_type: "image",
          background_color: null,
          content: image.file.name,
          position_x: imageNode.x(),
          position_y: imageNode.y(),
          width: image.originalWidth,
          height: image.originalHeight,
          rotation: imageNode.rotation(),
          scale: imageNode.scaleX(),
          isPost: false,
          offset_x: 0,
          offset_y: 0,
          z_index: image.z_index,
          scaled: imageScaledMap[image.file.name] ?? (imageNode.scaleX() !== 1),
        });
      });
    }

    // Add text/mention/link/hashtag elements.
    textGroups.forEach((txt) => {
      const node = stageRef.current.findOne(`#${txt.id}`);
      if (!node) return;
      const elementType = txt.isMention
        ? "mention"
        : txt.isLink
        ? "link"
        : txt.isHashtag
        ? "hashtag"
        : "text";
      metadataArray.push({
        element_type: elementType,
        background_color: txt.backgroundColor || null,
        content: txt.text,
        position_x: node.x(),
        position_y: node.y(),
        width: node.width() * node.scaleX(),
        height: node.height() * node.scaleY(),
        rotation: node.rotation(),
        scale: node.scaleX(),
        isPost: false,
        z_index: txt.z_index,
        text_color: elementType === "text" ? txt.fontColor : null,
      });
    });

    // 3. If a postIdValue exists, add it as an element.
    if (postIdValue) {
      metadataArray.push({
        element_type: "post",
        background_color: null,
        content: postIdValue,
        position_x: postTransform.x,
        position_y: postTransform.y,
        width: 375,
        height: 375 * (9 / 10),
        rotation: postTransform.rotation,
        scale: postTransform.scaleX,
        isPost: true,
        z_index: nextZIndex++,
      });
    }

    const formData = new FormData();
    formData.append(
      "storyDetails",
      JSON.stringify({
        width: stageSize.width,
        height: stageSize.height,
        bgcolor: canvasBgColor,
      })
    );
    formData.append("metadata", JSON.stringify(metadataArray));

    // Append video file if available.
    if (videoFile) {
      formData.append("video", videoFile);
    }
    // Append image files if available.
    if (images.length > 0) {
      images.forEach((imgObj) => {
        formData.append("images", imgObj.file);
      });
    }
    // 4. Send the request to create the story.
    const response = await axios.post(`${api}/post/create-story`, formData, {
      withCredentials: true,
      headers: { "Content-Type": "multipart/form-data" },
    });

    // If the response contains the created story data
    if (response.data && response.data.storyId) {
      // Create story data object with the response data
      const storyData = {
        storyId: response.data.storyId,
        viewed: false,
        timestamp: new Date().toISOString(),
        bgcolor: canvasBgColor,
        elements: metadataArray.map(meta => ({
          ...meta,
          // Transform metadata to elements format expected by story viewer
          type: meta.element_type,
          content: meta.content,
          position: { x: meta.position_x, y: meta.position_y },
          transform: {
            rotation: meta.rotation,
            scale: meta.scale
          },
          dimensions: meta.type === "video" || meta.type === "image" ? {
            width: meta.width,
            height: meta.height
          } : undefined,
          z_index: meta.z_index,
          isPost: meta.isPost || false
        })),
        viewsCount: 0,
        isLiked: false
      };
      
      // Dispatch action to add the created story to Redux state
      dispatch(addCreatedStory({
        userId: userData.id,
        storyData
      }));
    }

    setCreationSuccess(true);
    setTimeout(() => {
      setCreationSuccess(false);
      if (onClose) onClose(); // Close the story creation component after success
    }, 1200);
  } catch (error) {
    console.error("Error creating story:", error);
  }
};
const handleSearch = async (value, type) => {
  if (!value.trim()) {
    setSearchResults([]);
    return;
  }

  setLoading(true);
  try {
    const searchTerm = value.replace(/^[#@]/, ''); // Remove # or @ if present
    const endpoint = type === 'hashtag' ? 'hashtag-search' : 'username-search';
    
    const response = await axios.post(`${api}/post/${endpoint}`, {
      searchTerm
    });
    setSearchResults(response.data);
  } catch (error) {
    console.error('Error fetching search results:', error);
    setSearchResults([]);
  } finally {
    setLoading(false);
  }
};
useEffect(() => {
  if (!containerRef.current) return;

  const handleResize = () => {
    const { width, height } = containerRef.current.getBoundingClientRect();
    setStageSize({
      width,
      height
    });
  };

  window.addEventListener("resize", handleResize);
  handleResize();

  return () => window.removeEventListener("resize", handleResize);
}, [containerRef]);

const addHashtag = () => {
  setTextGroups((prev) => [
    ...prev,
    {
      id: `hashtag_${Date.now()}_${Math.random()}`,
      text: hashtagValue,
      x: 100,
      y: 100,
      fontColor: "#000000",
      backgroundColor: "#ffffff",
      showBackground: true,
      rotation: 0,
      scaleX: 1,
      scaleY: 1,
      isHashtag: true,
      z_index: getMaxZIndex() + 1,

    },
  ]);
  setHashtagValue("");
  setShowHashtagOverlay(false);
};

const handleStageTouch = (e) => {
  if (!selectedId || e.evt.touches.length !== 2) return;
  
  const stage = stageRef.current;
  const node = stage.findOne(`#${selectedId}`);
  if (!node) return;

  e.evt.preventDefault();
  const [t1, t2] = e.evt.touches;
  const p1 = { x: t1.clientX, y: t1.clientY };
  const p2 = { x: t2.clientX, y: t2.clientY };
  
  setInitialAngle(Math.atan2(p2.y - p1.y, p2.x - p1.x));
  setInitialRotation(node.rotation());
  setInitialDist(Math.hypot(p1.x - p2.x, p1.y - p2.y));
  setInitialScale({ x: node.scaleX(), y: node.scaleY() });
};

const handleStageTouchMove = (e) => {
  if (!selectedId || e.evt.touches.length !== 2) return;

  const stage = stageRef.current;
  const node = stage.findOne(`#${selectedId}`);
  if (!node) return;

  e.evt.preventDefault();
  const [t1, t2] = e.evt.touches;
  const p1 = { x: t1.clientX, y: t1.clientY };
  const p2 = { x: t2.clientX, y: t2.clientY };
  
  const currentAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
  const angleDiff = (currentAngle - initialAngle) * (180 / Math.PI);
  const currentDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
  const scaleFactor = currentDist / initialDist;

  node.rotation(initialRotation + angleDiff);
  node.scaleX(initialScale.x * scaleFactor);
  node.scaleY(initialScale.y * scaleFactor);
  node.getLayer().batchDraw();
};


useEffect(() => {
  if (!selectedId) return;
  const stage = stageRef.current?.getStage();
  if (!stage) return;
  const node = stage.findOne(`#${selectedId}`);
  if (!node) return;

  let initialRotation = 0;
  let initialAngle = 0;
  let initialDist = 0;
  let initialScaleX = node.scaleX();
  let initialScaleY = node.scaleY();



  const handleTouchStart = (e) => {
    if (e.evt.touches.length === 2) {
      e.evt.preventDefault();
      const [t1, t2] = e.evt.touches;
      const p1 = { x: t1.clientX, y: t1.clientY };
      const p2 = { x: t2.clientX, y: t2.clientY };
      initialAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
      initialRotation = node.rotation();
      initialDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      initialScaleX = node.scaleX();
      initialScaleY = node.scaleY();
    }
  };

  const handleTouchMove = (e) => {
    if (e.evt.touches.length === 2) {
      e.evt.preventDefault();
      const [t1, t2] = e.evt.touches;
      const p1 = { x: t1.clientX, y: t1.clientY };
      const p2 = { x: t2.clientX, y: t2.clientY };
      const currentAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
      const angleDiff = (currentAngle - initialAngle) * (180 / Math.PI);
      const currentDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      const scaleFactor = currentDist / initialDist;
      node.rotation(initialRotation + angleDiff);
      node.scaleX(initialScaleX * scaleFactor);
      node.scaleY(initialScaleY * scaleFactor);
      node.getLayer().batchDraw();
    }
  };

  const handleTouchEnd = () => {
    initialRotation = 0;
    initialAngle = 0;
    initialDist = 0;
    initialScaleX = 0;
    initialScaleY = 0;
  };

  stage.on("touchstart", handleTouchStart);
  stage.on("touchmove", handleTouchMove);
  stage.on("touchend", handleTouchEnd);

  return () => {
    stage.off("touchstart", handleTouchStart);
    stage.off("touchmove", handleTouchMove);
    stage.off("touchend", handleTouchEnd);
  };
}, [selectedId]);

// Utility function to calculate the distance between two points
const getDistance = (p1, p2) => Math.sqrt(Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2));




  const extractFirstFrame = (file) => {
    return new Promise((resolve, reject) => {
      const video = document.createElement("video");
      video.src = URL.createObjectURL(file);
      video.addEventListener("loadeddata", () => {
        video.currentTime = 0;
      });
      video.addEventListener("seeked", () => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, video.videoWidth, video.videoHeight);
        const img = new window.Image();
        img.src = canvas.toDataURL("image/png");
        resolve(img);
      });
      video.addEventListener("error", (err) => reject(err));
    });
  };

  // Handle upload
  const handleUpload = () => {
    // If widgetStoryPostId exists, disallow video uploads even if no media has been added yet.
    if (widgetStoryPostId) {
      fileInputRef.current.accept = "image/*";
    } else if (!hasMedia) {
      fileInputRef.current.accept = "image/*,video/*";
    } else {
      fileInputRef.current.accept = "image/*";
    }
    fileInputRef.current.click();
  };
  // Update Konva canvas with video frames
  const updateKonvaCanvas = () => {
    const video = videoRef.current;
    if (video && konvaImageRef.current) {
      konvaImageRef.current.image(video);
      konvaImageRef.current.getLayer().batchDraw();
      requestAnimationFrame(updateKonvaCanvas); // Continuously update the canvas
    }
  };

  // Start video playback and update Konva
  useEffect(() => {
    if (videoFile && videoRef.current) {
      videoRef.current.play();
      videoRef.current.addEventListener("play", updateKonvaCanvas);
    }

    // Cleanup
    return () => {
      if (videoRef.current) {
        videoRef.current.removeEventListener("play", updateKonvaCanvas);
      }
    };
  }, [videoFile]);

  const handleFilesUpload = (e) => {
    const files = e.target.files;
    if (!files) return;

    const newZIndex = getMaxZIndex() + 1;

  
    [...files].forEach((file) => {
      if (file.type.startsWith("image/")) {
        const img = new window.Image();
        img.onload = () => {
          const originalWidth = img.naturalWidth;
          const originalHeight = img.naturalHeight;
  
          const scale = Math.min(
            stageSize.width / originalWidth,
            stageSize.height / originalHeight
          );
  
          if (!hasMedia) {
            const colorThief = new ColorThief();
            const dominantColor = colorThief.getColor(img);
            const rgbColor = `rgb(${dominantColor[0]}, ${dominantColor[1]}, ${dominantColor[2]})`;
            setCanvasBgColor(rgbColor);
            setHasMedia(true);
          }
  
          const x = (stageSize.width - originalWidth * scale) / 2;
          const y = (stageSize.height - originalHeight * scale) / 2;
  
          setImages(prev => [
            ...prev,
            {
              id: `img_${Date.now()}_${Math.random()}`,
              image: img,
              file: file,
              x,
              y,
              rotation: 0,
              scaleX: scale,
              scaleY: scale,
              originalWidth,
              originalHeight,
              z_index: newZIndex,
              scaled: false

            }
          ]);
          setImageScaledMap(prev => ({
            ...prev,
            [file.name]: false,
            z_index: newZIndex

          }));
        };
        img.src = URL.createObjectURL(file);
      } else if (file.type.startsWith("video/")) {
        const video = document.createElement('video');
        video.src = URL.createObjectURL(file);
        
        video.onloadedmetadata = () => {
          const originalWidth = video.videoWidth;
          const originalHeight = video.videoHeight;
          
          const scale = Math.min(
            stageSize.width / originalWidth,
            stageSize.height / originalHeight
          );
  
          if (!hasMedia) {
            extractFirstFrame(file).then((frameImage) => {
              const colorThief = new ColorThief();
              const dominantColor = colorThief.getColor(frameImage);
              const rgbColor = `rgb(${dominantColor[0]}, ${dominantColor[1]}, ${dominantColor[2]})`;
              setCanvasBgColor(rgbColor);
            });
            setHasMedia(true);
          }
  
          setVideoFile(file);
          setVideoURL(URL.createObjectURL(file));
          setVideoTransform({
            originalWidth,
            originalHeight,
            scale,
            x: (stageSize.width - originalWidth * scale) / 2,
            y: (stageSize.height - originalHeight * scale) / 2,
            rotation: 0
          });
        };
      }
    });
  };
  // Add text
  const addText = () => {
    setTextGroups((prev) => [
      ...prev,
      {
        id: `text_${Date.now()}_${Math.random()}`,
        text: textValue,
        x: 100,
        y: 100,
        fontColor,
        backgroundColor: showBackground ? backgroundColor : null,
        showBackground,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        z_index: getMaxZIndex() + 1
      }
    ]);
    setTextValue("");
    setShowTextOverlay(false);
  };

  useEffect(() => {
    const handleResize = () => {
      setWindowWidth(window.innerWidth);
    };
  
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Transformer
  const TransformerComponent = ({ selectedShape }) => {
    const trRef = useRef(null);

    useEffect(() => {
      if (trRef.current && selectedShape) {
        trRef.current.nodes([selectedShape]);
        trRef.current.getLayer().batchDraw();
      }
    }, [selectedShape]);

    return (
      
      <Transformer
      ref={trRef}
      rotateEnabled={windowWidth >= 1280 }
      enabledAnchors={
        windowWidth >= 1280 
          ? ["top-left", "top-right", "bottom-left", "bottom-right"]
          : []
      }
      rotateAnchorOffset={50}
    />
    );
  };

  // Find selected node
  const getSelectedNode = () => {
    if (!selectedId) return null;
    return stageRef.current
      .getStage()
      .findOne((node) => node.attrs.id === selectedId);
  };

  const handleSelect = (id) => {
    if (selectedId === id) {
      setSelectedId(null);
    } else {
      setSelectedId(id);
      bringElementToFront(id);
    }
  };
  
  const bringElementToFront = (selectedId) => {
    const stage = stageRef.current.getStage();
    const layer = stage.getChildren()[0];
    const allNodes = layer.getChildren();
  
    // Find the highest zIndex.
    let highestZ = 0;
    allNodes.forEach((node) => {
      highestZ = Math.max(highestZ, node.zIndex());
    });
  
    // Find the selected node.
    const selectedNode = allNodes.find((node) => node.attrs.id === selectedId);
    if (!selectedNode) return;
  
    // Do nothing if it's already on top.
    if (selectedNode.zIndex() === highestZ) {
      return;
    }
  
    // Move only the selected node to top; leave others unchanged.
    selectedNode.zIndex(highestZ + 1);
    layer.batchDraw();
  
    if (selectedId === "video") {
      setVideoTransform((prev) => ({ ...prev, z_index: highestZ + 1 }));
    } else {
      setImages((prev) =>
        prev.map((img) =>
          img.id === selectedId
            ? { ...img, z_index: highestZ + 1 }
            : img
        )
      );
      setTextGroups((prev) =>
        prev.map((txt) =>
          txt.id === selectedId
            ? { ...txt, z_index: highestZ + 1 }
            : txt
        )
      );
    }
  };

  const captureFrame = (stage) => {
    return new Promise(resolve => {
      const dataURL = stage.toDataURL();
      const img = new window.Image();
      img.src = dataURL;
      img.onload = () => resolve(dataURL);
    });
  };

  const createVideoFromFrames = async (frames, fps = 30) => {
    const ffmpeg = new FFmpeg();
  
    try {
      await ffmpeg.load(); // Load FFmpeg WebAssembly module
  
      // Write frames into FFmpeg's virtual filesystem
      for (let i = 0; i < frames.length; i++) {
        const frameBase64 = frames[i].replace(/^data:image\/\w+;base64,/, '');
        const frameBuffer = Uint8Array.from(atob(frameBase64), char => char.charCodeAt(0));
        await ffmpeg.writeFile(`frame_${String(i).padStart(3, '0')}.png`, frameBuffer);
      }
  
      // Video output file
      const outputFile = 'output.mp4';
  
      // FFmpeg command to generate the video
      await ffmpeg.exec([
        '-framerate', fps.toString(),  // Set frame rate
        '-i', 'frame_%03d.png',       // Input frame pattern
        '-c:v', 'libx264',            // Video codec
        '-pix_fmt', 'yuv420p',        // Pixel format
        '-vf', 'scale=640:-2',        // Optional: Resize to fit dimensions
        outputFile                    // Output file name
      ]);
  
      // Read the generated video file from FFmpeg's virtual filesystem
      const videoData = await ffmpeg.readFile(outputFile);
  
      // Convert video data to a Blob for downloading
      const blob = new Blob([videoData], { type: 'video/mp4' });
      const url = URL.createObjectURL(blob);
  
      // Trigger download
      const link = document.createElement('a');
      link.href = url;
      link.download = 'animation.mp4';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
  
      console.log('Video created and downloaded successfully!');
    } catch (error) {
      console.error('Error creating video:', error);
    } finally {
      // Cleanup: Remove virtual filesystem files
      for (let i = 0; i < frames.length; i++) {
        await ffmpeg.removeFile(`frame_${String(i).padStart(3, '0')}.png`);
      }
      await ffmpeg.removeFile(outputFile);
    }
  };

 // Extend closeAllOverlays to include the post overlay
 const closeAllOverlays = () => {
  setShowTextOverlay(false);
  setShowMentionOverlay(false);
  setShowLinkOverlay(false);
  setShowHashtagOverlay(false);
  setShowPostOverlay(false);
};
  
  const openTextOverlay = () => {
    closeAllOverlays();
    setShowTextOverlay(true);
  };
  
  const openMentionOverlay = () => {
    closeAllOverlays();
    setShowMentionOverlay(true);
  };
  
  const openLinkOverlay = () => {
    closeAllOverlays();
    setShowLinkOverlay(true);
  };
  
  const openHashtagOverlay = () => {
    closeAllOverlays();
    setShowHashtagOverlay(true);
  };
  useEffect(() => {
    if (!widgetStoryPostId) {
      navigate("/");
    }
  }, [widgetStoryPostId, navigate]);
  
  const handleDownload = async () => {
    if (!videoFile) {
      // Handle image download
      const dataUrl = stageRef.current.toDataURL();
      const link = document.createElement('a');
      link.href = dataUrl;
      link.download = 'story.png';
      link.click();
      return;
    }
    const stage = stageRef.current;
    const fps = 60;
    const duration = 10; // 2 seconds
    const totalFrames = fps * duration;
  
    try {
      // Capture frames from the canvas
      const frames = [];
      for (let i = 0; i < totalFrames; i++) {
        const frame = await captureFrame(stage);
        frames.push(frame);
      }
  
      // Create and download video from frames
      await createVideoFromFrames(frames, fps);
    } catch (error) {
      console.error('Error capturing frames or creating video:', error);
    }
  };
  const addMention = () => {
    setTextGroups((prev) => [
      ...prev,
      {
        id: `mention_${Date.now()}_${Math.random()}`,
        text: mentionValue,
        x: 100,
        y: 100,
        fontColor: "#000000",
        backgroundColor: "#ffffff",
        showBackground: true,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        isMention: true,
        z_index: getMaxZIndex() + 1,
      }
    ]);
    setMentionValue("");
    setShowMentionOverlay(false);
  };

  // Add link
  const addLink = () => {
    setTextGroups((prev) => [
      ...prev,
      {
        id: `link_${Date.now()}_${Math.random()}`,
        text: linkValue,
        x: 100,
        y: 100,
        fontColor: "#000000",
        backgroundColor: "#ffffff",
        showBackground: true,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        isLink: true,
        z_index: getMaxZIndex() + 1,

      }
    ]);
    setLinkValue("");
    setShowLinkOverlay(false);
  };

  // Delete selected object
  const handleDelete = () => {
    if (!selectedId) return;
    setImages((prev) => prev.filter((img) => img.id !== selectedId));
    setTextGroups((prev) => prev.filter((txt) => txt.id !== selectedId));
    setSelectedId(null);
  };

  // Add this function to determine if the selected item is the primary upload
const isPrimaryUpload = () => {
  if (videoFile) {
    return selectedId === 'video';
  } else if (images.length > 0) {
    return selectedId === images[0].id;
  }
  return false;
};

useEffect(() => {
  if (videoFile) {
    const url = URL.createObjectURL(videoFile);
    setVideoURL(url);
    return () => URL.revokeObjectURL(url);
  }
}, [videoFile]);

const getTextGradient = () => ({
  colors: [
   
    '#FF3E6B',  // Reddish Pink
    '#9C27B0',  // Purple
    '#3F51B5',  // Indigo
    '#2196F3',  // Bright Blue
    '#00BCD4',  // Cyan
    '#4CAF50',  // Green
    '#FFC107'   // Gold
  ],
  font: "'Poppins', sans-serif"
});

console.log(searchResults)

useEffect(() => {
  if (videoFile && videoRef.current) {
    videoRef.current.addEventListener("loadedmetadata", () => {
      // Always set loop to true so even non-trimmed videos will replay
      videoRef.current.loop = true;
      if (videoRef.current.duration > 60) {
        videoRef.current.currentTime = 0;
        // Only trim if the video is longer than 60s
        videoRef.current.addEventListener("timeupdate", () => {
          if (videoRef.current.currentTime >= 60) {
            videoRef.current.currentTime = 0;
          }
        });
      }
      videoRef.current.play();
      videoRef.current.addEventListener("play", updateKonvaCanvas);
    });
  }
  return () => {
    if (videoRef.current) {
      videoRef.current.removeEventListener("play", updateKonvaCanvas);
    }
  };
}, [videoFile]);

const createColorVariations = (color) => {
  const rgbValues = color.replace('rgb(', '').replace(')', '').split(',');
  const baseValues = rgbValues.map(val => parseInt(val));
  
  // Create 4 variations with subtle differences
  const color1 = baseValues.map(val => Math.min(255, val + (255 - val) * 0.15));
  const color2 = baseValues.map(val => Math.min(255, val + (255 - val) * 0.10));
  const color3 = baseValues.map(val => Math.min(255, val + (255 - val) * 0.05));
  const color4 = baseValues; // Original color
  
  return {
    color1: `rgba(${color1.join(',')}, 0.60)`,
    color2: `rgba(${color2.join(',')}, 0.70)`,
    color3: `rgba(${color3.join(',')}, 0.75)`,
    color4: `rgba(${color4.join(',')}, 0.70)`
  };
};
  return (
    
    <div className="fixed inset-0 flex xl:mt-4 500:mt-1 justify-center md:items-center z-100">
       {creationSuccess && (
        <div className="absolute top-1/2 -translate-y-1/2 left-1/2 transform -translate-x-1/2 bg-gray-950 border-[1px] border-gray-700 p-4 rounded-lg flex items-center space-x-2 z-50">
          <CircleCheckBig className="w-8 h-8 text-white" />
          <span className="text-white font-semibold">
            Story created successfully!
          </span>
        </div>
      )}
    <div className="max-w-[380px]  border-gray-600 500:border-[1px] w-full  500:rounded-xl overflow-hidden">
    <button
  style={{
    position: "absolute",
    top: "15px",
    right: "50px",
    zIndex: 10,
    background: "transparent",
    border: "none",
    cursor: "pointer"
  }}
  onClick={(e) => {
    e.stopPropagation();
    // If onClose is provided, call it.
    if (onClose) {
      onClose();
    }
    // When rendered as a page, navigate back home.
    navigate('/');
  }}
  className="max-md:hidden"
>
  <IoMdClose style={{ color: "#fff", fontSize: "40px" }} />
</button>
    <div className="relative">
     
      
      {/* Your existing CreateStory UI */}
      <div 
        ref={containerRef}
        className="[aspect-ratio:9/16] max-h-[700px] rounded-xl"
      >

      {/* Hidden file input */}
      <input
        type="file"
        multiple
        accept="image/*"
        ref={fileInputRef}
        onChange={handleFilesUpload}
        style={{ display: "none" }}
      />

      {/* Overlay for text input */}
      {showTextOverlay && (
        <div className="fixed  mt-20  inset-0 flex items-center justify-center thetopone max-md:mb-60">
          <div className="p-4 backdrop-blur-md bg-[#0a0a0a] opacity-100 rounded-lg shadow-lg w-[90%] max-w-[375px] space-y-5">
            <h2 className="text-lg font-semibold text-white">Add Text Overlay</h2>
            <div className="flex items-center space-x-2 relative">
              <input
                type="text"
                className="flex-grow p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
                placeholder="Enter text here"
                value={textValue}
                autoFocus
                onChange={(e) => setTextValue(e.target.value)}
              />
              <input
                type="color"
                className="w-[50px] h-[50px] p-0 border-0 rounded-xl bg-transparent cursor-pointer"
                value={fontColor}
                onChange={(e) => setFontColor(e.target.value)}
              />
             
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  className="form-checkbox h-5 w-5 text-gray-500 border border-gray-500 rounded focus:ring-gray-500"
                  checked={showBackground}
                  onChange={(e) => setShowBackground(e.target.checked)}
                />
                <span className="text-smd text-gray-300">Background</span>
              </div>
              {showBackground && (
                <input
                  type="color"
                  className="w-10 h-10 p-0 border-0 bg-transparent cursor-pointer"
                  value={backgroundColor}
                  onChange={(e) => setBackgroundColor(e.target.value)}
                />
              )}
            </div>
            <div className="flex items-center justify-start  space-x-4">
          
            <button
                onClick={addText}
                className="px-5 py-1 bg-white text-black font-semibold rounded-md hover:bg-gray-400 transition duration-200"
              >
                Add Text
              </button>
              <button
                onClick={() => setShowTextOverlay(false)}
                className="px-5 py-1 bg-white text-black font-semibold rounded-md hover:bg-gray-400 transition duration-200"
              >
                Cancel
              </button>
              {windowWidth > 1024 && (
                <div className="relative">
                  <BsEmojiSmile
                    onClick={toggleEmojiPicker}
                    className="ml-20 text-xl rounded-md text-white"
                  />
                  {showEmojiPicker && (
                    <div
                      ref={emojiPickerRef}
                      style={{
                        position: "absolute",
                        bottom: "calc(100% + 5px)", // Place picker above the emoji icon with a 5px gap
                        left: 68,
                        zIndex: 50,
                      }}
                    >
                      <Picker onEmojiClick={handleSelectEmoji} theme="dark" />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

{showMentionOverlay && (
  <div className="fixed inset-0 mt-20 max-md:mt-6  flex items-center justify-center thetopone max-md:mb-40">
    <div className="p-4 backdrop-blur-md bg-[#0a0a0a] rounded-lg shadow-lg w-[90%] max-w-[380px] space-y-5">
      <h2 className="text-white font-semibold">Add Mention</h2>
      <div className="relative">
  <input
    type="text"
    placeholder="@username"
    value={mentionValue}
    onChange={(e) => {
      setMentionValue(e.target.value);
      handleSearch(e.target.value, 'username');
    }}
    className="flex w-full p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
    autoFocus
  />

  {searchResults.length > 0 && (
    <div className="absolute bottom-full mb-2 left-0 w-full bg-[#1a1a1a] rounded-lg shadow-lg z-50 max-h-48 overflow-y-auto">
      {searchResults.map((result) => (
        <div
          key={result.username}
          className="flex items-center p-3 hover:bg-[#252525] cursor-pointer"
          onClick={() => {
            setMentionValue(result.username);
            setSearchResults([]);
          }}
        >
          <img
            className="w-7 h-7 rounded-full bg-gray-300"
           
            src={
              result.profilePicture ?
              `${cloud}/cloudofscubiee/profilePic/${result.profilePicture}` : "/logos/DefaultPicture.png"}
            alt={result.username}
          />
          <div className="ml-2 text-white text-sm flex items-center">
            {result.username}
            {result.verified ? (
              <RiVerifiedBadgeFill className='text-blue-500 w-4 h-4 ml-1' />
            ): null}
          </div>
        </div>
      ))}
    </div>
  )}
</div>

      <div className="flex justify-start space-x-3">
        <button 
          onClick={addMention} 
          className="px-3 py-1 font-medium bg-white text-black rounded-md"
        >
          Add Mention
        </button>
        <button 
          onClick={() => {
            setShowMentionOverlay(false);
            setSearchResults([]);
          }} 
          className="px-3 py-1 font-medium bg-white text-black rounded-md"
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
)}


{showPostOverlay && (
  <div className="overlay">
    <input
      type="text"
      placeholder="Enter Post ID"
      value={postIdValue}
      onChange={(e) => setPostIdValue(e.target.value)}
    />
    <button onClick={addPostSummary}>Save</button>
    <button onClick={closeAllOverlays}>Cancel</button>
  </div>
)}

      {showLinkOverlay && (
        <div className="fixed inset-0 mt-20 max-md:mt-6  flex items-center justify-center thetopone max-md:mb-40">
        <div className="p-4 backdrop-blur-md bg-[#0a0a0a] rounded-lg shadow-lg w-[90%] max-w-[380px] space-y-5">
          <h2 className="text-white font-semibold">Add Link</h2>
            <input
              type="text"
              placeholder="Enter link text"
              value={linkValue}
              onChange={(e) => setLinkValue(e.target.value)}
              className="flex w-full p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
              autoFocus
            />
            <div className="flex justify-start space-x-3">
              <button onClick={addLink}  className="px-3 py-1 font-medium bg-white text-black rounded-md">
                Add Link
              </button>
              <button onClick={() => setShowLinkOverlay(false)}  className="px-3 py-1 font-medium bg-white text-black rounded-md">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

{showHashtagOverlay && (
  <div className="fixed inset-0 mt-20 max-md:mt-6  flex items-center justify-center thetopone max-md:mb-40">
    <div className="p-4 backdrop-blur-md bg-[#0a0a0a] rounded-lg shadow-lg w-[90%] max-w-[380px] space-y-5">
      <h2 className="text-white font-semibold">Add Hashtag</h2>
      <div className="relative">
        <input
          type="text"
          placeholder="#hashtag"
          value={hashtagValue}
          onChange={(e) => {
            const value = e.target.value.replace(/^#/, ''); // Remove # if present
            setHashtagValue(value);
            handleSearch(value, 'hashtag');
          }}
          className="flex w-full p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
          autoFocus
        />

{searchResults.length > 0 && (
  <div className="absolute bottom-full mb-2 left-0 w-full bg-[#1a1a1a] rounded-lg shadow-lg z-50 max-h-48 overflow-y-auto">
    {searchResults.map((result) => (
      <div
        key={result._id}
        className="flex items-center justify-between p-3 hover:bg-[#252525] cursor-pointer"
        onClick={() => {
          setHashtagValue(result.name);
          setSearchResults([]);
        }}
      >
        <span className="text-white">#{result.name}</span>
        <span className="text-gray-400 text-sm font-sans font-semibold">{result.Count || 0} Posts</span>
      </div>
    ))}
  </div>
)}
      </div>
      <div className="flex justify-start space-x-3">
        <button 
          onClick={addHashtag} 
          className="px-3 py-1 font-medium bg-white text-black rounded-md"
        >
          Add Hashtag
        </button>
        <button 
          onClick={() => {
            setShowHashtagOverlay(false);
            setSearchResults([]);
          }} 
          className="px-3 py-1 font-medium bg-white text-black rounded-md"
        >
          Cancel
        </button>
      </div>
    </div>
  </div>
)}
      {/* Konva Stage */}
      <div    className={`  [aspect-ratio:9/16] max-h-[640px] max-w-[380px]  h-[calc(100vh-16px)] `}
      style={{ background: 'canvasBgColor' }}
       ref={containerRef} >
        <div className="relative h-0  space-x-3 pl-3 bg-transparent w-full flex justify-start rounded-t-xl thetopone backdrop-blur-lg">
          <button
            onClick={handleUpload}
          >
            <UploadCloudIcon className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 mt-2 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
 
          <button
            onClick={openTextOverlay}
          >
            <IoTextSharp className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          <button
            onClick={openLinkOverlay}
          >
            <FiLink className="inline w-[36px] h-[36px] md:w-[38px] md:h-[38px]  px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          <button onClick={openHashtagOverlay}>
    <RiHashtag  className="inline w-[38px] h-[38px] md:w-[40px] md:h-[40px] px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
  </button>
          <button
            onClick={openMentionOverlay}
          >
            <VscMention className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-1 py-[1px] rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>

              {selectedId && !isPrimaryUpload() && (
                <button
                  onClick={handleDelete}
                >
                  <RiDeleteBin6Line className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]"/>
                </button>
              )}
          <button
            onClick={handleCreateStory}
          >
            <FaChevronRight    className="inline w-[34px] h-[34px] md:h-[37px] md:w-[37px] px-3 py-2 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          </div>
          {videoFile && (
  <>
    {/* Hidden video element */}
    <video
     ref={videoRef}
     src={videoURL}
      style={{ display: "none" }}
      crossOrigin="anonymous" // Ensure CORS issues are avoided for local files
      onLoadedMetadata={(e) => {
        const video = e.target;
        const videoWidth = video.videoWidth;
        const videoHeight = video.videoHeight;
        const canvasWidth = stageSize.width;
        const canvasHeight = stageSize.height;
        const scale = Math.min(canvasWidth / videoWidth, canvasHeight / videoHeight);
        setVideoScale(scale);
      }}
    />
  </>
)}
<div
  className="stage-wrapper"
  style={{
    borderRadius: windowWidth > 500 ? '1rem' : '0',
    overflow: 'hidden'
  }}
>
<Stage
  
     width={stageSize.width}
     height={stageSize.height}
  ref={stageRef}
  onMouseDown={handleStageClick}
  onTouchStart={handleStageTouch}
  onTouchMove={handleStageTouchMove}

  style={{
    background: (() => {
      const colors = createColorVariations(canvasBgColor);
      return `radial-gradient(circle at center, 
        ${colors.color1} 0%, 
        ${colors.color2} 30%, 
        ${colors.color3} 60%, 
        ${colors.color4} 100%)`
    })()
  }}>
  <Layer>
    {videoFile && (
      <Image
      ref={konvaImageRef}
      id="video"
      image={videoRef.current}
      width={videoRef.current ? videoRef.current.videoWidth : 0}
      height={videoRef.current ? videoRef.current.videoHeight : 0}
      // Center the video on the canvas using the same math from createpost.jsx
      x={
        (stageSize.width - (videoRef.current ? videoRef.current.videoWidth * videoScale : 0)) /
        2
      }
      y={
        (stageSize.height - (videoRef.current ? videoRef.current.videoHeight * videoScale : 0)) /
        2
      }
      scaleX={videoScale}
      scaleY={videoScale}
      draggable={windowWidth >= 1280 || selectedId === "video"}
        onClick={(e) => {
          e.cancelBubble = true;
          handleSelect('video');
        }}
        onTap={(e) => {
          e.cancelBubble = true;
          handleSelect('video');
        }}
        onDragEnd={(e) => {
          const node = e.target;
          setVideoPosition({ x: node.x(), y: node.y() });
        }}
        onTransformEnd={(e) => {
          const node = e.target;
          const scaleX = node.scaleX();
          const scaleY = node.scaleY();
          console.log(`Image scaled: scaleX=${scaleX}, scaleY=${scaleY}`);
         
         
          setIsScaled(true);
          console.log(isScaled);
        
        
          // Check if the image is scaled (assuming uniform scaling)
          const isScaled = scaleX !== 1 || scaleY !== 1;
          if (isScaled) {
            console.log(`Image scaled: scaleX=${scaleX}, scaleY=${scaleY}`);
          }
                    setVideoTransform({
            x: node.x(),
            y: node.y(),
            rotation: node.rotation(),
            scaleX: node.scaleX(),
            scaleY: node.scaleY(),
            scaled: isScaled

          });
        }}
      />
    )}
    {selectedId === 'video' && (
       <Transformer
       ref={trRef}
       rotateEnabled={windowWidth >= 1280 }
       enabledAnchors={
         windowWidth >= 1280 
           ? ["top-left", "top-right", "bottom-left", "bottom-right"]
           : []
       }
       rotateAnchorOffset={50}
     />
    )}
    {images.map((imgObj) => (
      <Image
        key={imgObj.id}
        id={imgObj.id}
        image={imgObj.image}
        x={imgObj.x}
        y={imgObj.y}
        draggable={windowWidth >= 1280 || selectedId === imgObj.id}
        offsetX={0}
        offsetY={0}
        rotation={imgObj.rotation}
        scaleX={imgObj.scaleX}
        scaleY={imgObj.scaleY}
        onClick={(e) => {
          e.cancelBubble = true;
          handleSelect(imgObj.id);
        }}
        onTap={(e) => {
          e.cancelBubble = true;
          handleSelect(imgObj.id);
        }}
        onDragEnd={(e) => {
          const node = e.target;
          setImages((prev) =>
            prev.map((o) =>
              o.id === imgObj.id
                ? { ...o, x: node.x(), y: node.y() }
                : o
            )
          );
        }}
        onTransformEnd={(e) => {

          const node = e.target;
          const scaleX = node.scaleX();
          const scaleY = node.scaleY();
       
          setImages((prev) =>
            prev.map((img) =>
              img.id === imgObj.id
                ? { ...img, x: node.x(), y: node.y(), rotation: node.rotation(), scaleX, scaleY, scaled: true }
                : img
            )
          );
        
          // Also update the map
          setImageScaledMap((prev) => ({
            ...prev,
            [imgObj.file.name]: true
          }));
            setImages((prev) =>
            prev.map((o) =>
              o.id === imgObj.id
                ? {
                    ...o,
                    x: node.x(),
                    y: node.y(),
                    rotation: node.rotation(),
                    scaleX: node.scaleX(),
                    scaleY: node.scaleY(),
                    scaled: isScaled

                  }
                : o
            )
          );
        }}
      />
    ))}
   {postSummary && (
     <Group
  id="postElement"
  draggable={windowWidth >= 1280 || selectedId === "postElement"}
  x={postTransform.x}
  y={postTransform.y}
  rotation={postTransform.rotation}
  scaleX={postTransform.scaleX}
  scaleY={postTransform.scaleY}
  onClick={(e) => {
    e.cancelBubble = true;
    handleSelect("postElement");
  }}
  onTap={(e) => {
    e.cancelBubble = true;
    handleSelect("postElement");
  }}
  onDragEnd={(e) => {
    const node = e.target;
    setPostTransform((prev) => ({
      ...prev,
      x: node.x(),
      y: node.y(),
    }));
  }}
  onTransformEnd={(e) => {
    const node = e.target;
    setPostTransform({
      x: node.x(),
      y: node.y(),
      rotation: node.rotation(),
      scaleX: node.scaleX(),
      scaleY: node.scaleY(),
    });
  }}
>
  <Rect
    width={375}
    height={375 * (9 / 10)}
    fill="black"
    opacity={0.40}
    cornerRadius={8}
  />
  {/* Reserve top space for profile image and username */}
  {/* Reserve top space for profile image and username */}
{postProfileImage && (
  <>
    {/* Background rectangle for the profile image */}
    <Rect
      x={8}
      y={6}
      width={30}
      height={30}
      cornerRadius={15}
      fill="#e2e8f0"
    />
    {/* Profile image on top of the background */}
    <Image
      image={postProfileImage}
      x={8}
      y={6}
      width={30}
      height={30}
      cornerRadius={15}
    />
  </>
)}
<Text
  text={postSummary.author.username}
  fontSize={15.5}
  fill="#ccc"
  x={46} // Leave space for profile pic (8 + 30 + 8)
  y={14}
  fontFamily="sans-serif"
/>
{/* Display thumbnail with little top margin and extra bottom space */}
{postThumbnailImage && postMediaItems.length > 0 && (
  <Group x={0} y={40}>
    {postMediaItems.map((item, idx) => {
      // Grid layout calculations
      const itemWidth = 375;
      const itemHeight = 375 * (9 / 10) - 95;
      let columns = 1;
      let rows = 1;
      
      if (postMediaItems.length === 2) columns = 2;
      else if (postMediaItems.length === 3) columns = 3;
      else if (postMediaItems.length === 4) {
        columns = 2;
        rows = 2;
      }
      
      const cellWidth = itemWidth / columns;
      const cellHeight = itemHeight / rows;
      
      // Position calculation
      const row = postMediaItems.length === 4 ? Math.floor(idx / 2) : 0;
      const col = postMediaItems.length === 4 ? idx % 2 : idx;
      const x = col * cellWidth;
      const y = row * cellHeight;
      
      // Render item based on type
      if (item.type === 'image') {
        if (idx === 0) {
          return (
            <Image
              key={`post_media_${idx}`}
              image={postThumbnailImage}
              x={x}
              y={y}
              width={cellWidth - 1}
              height={cellHeight - 1}
              crop={{
                x: 0,
                y: 0,
                width: postThumbnailImage.width,
                height: postThumbnailImage.height
              }}
            />
          );
        } else {
          // Load the other images
          if (!item.loadedImage) {
            const img = new window.Image();
            img.crossOrigin = "Anonymous";
            img.src = item.url;
            img.onload = () => {
              const updatedMediaItems = [...postMediaItems];
              updatedMediaItems[idx].loadedImage = img;
              setPostMediaItems(updatedMediaItems);
            };
          }
          
          return item.loadedImage ? (
            <Image
              key={`post_media_${idx}`}
              image={item.loadedImage}
              x={x}
              y={y}
              width={cellWidth - 1}
              height={cellHeight - 1}
            />
          ) : (
            <Rect
              key={`post_media_${idx}`}
              x={x}
              y={y}
              width={cellWidth - 1}
              height={cellHeight - 1}
              fill="#333"
              stroke="#444"
              strokeWidth={1}
            />
          );
        }
      } else {
        // For videos, just show triangle play button
        return (
          <Group key={`post_media_${idx}`}>
            <Rect
              x={x}
              y={y}
              width={cellWidth - 1}
              height={cellHeight - 1}
              fill="#222"
            />
            <RegularPolygon
              x={x + cellWidth/2}
              y={y + cellHeight/2}
              sides={3}
              radius={12}
              fill="#fff"
              rotation={90}
            />
          </Group>
        );
      }
    })}
  </Group>
)}
<Text
  text={postSummary.title}
  fontSize={15.5}
  fill="#ccc"
  x={8}
  y={375 * (9 / 10) - 45}
  width={375 - 16}
  ellipsis={true}
  lineHeight={1.2}
  fontFamily="Roboto"
  wrap="word"
  maxLines={2}
  height={15.5 * 1.2 * 3} // Set explicit height for 2 lines: fontSize * lineHeight * maxLines
  textOverflow="ellipsis"
  padding={2}
/>
</Group>
    )}
   {textGroups.map((txt) => (
  <Group
    key={txt.id}
    id={txt.id}
    x={txt.x}
    y={txt.y}
    draggable={windowWidth >= 1280 || selectedId === txt.id}
    rotation={txt.rotation}
    scaleX={txt.scaleX}
    scaleY={txt.scaleY}
    onClick={(e) => {
      e.cancelBubble = true;
      handleSelect(txt.id);
    }}
    onTap={(e) => {
      e.cancelBubble = true;
      handleSelect(txt.id);
    }}
    onDragEnd={(e) => {
      const node = e.target;
      setTextGroups((prev) =>
        prev.map((o) =>
          o.id === txt.id ? { ...o, x: node.x(), y: node.y() } : o
        )
      );
    }}
    onTransformEnd={(e) => {
      const node = e.target;
      const scaleX = node.scaleX();
      const scaleY = node.scaleY();
      
      // Update text scale and position
      setTextGroups((prev) =>
        prev.map((o) =>
          o.id === txt.id
            ? {
                ...o,
                x: node.x(),
                y: node.y(),
                rotation: node.rotation(),
                scaleX: scaleX,
                scaleY: scaleY
              }
            : o
        )
      );
    }}
  >
        {txt.showBackground && (
          <Rect
            id={`${txt.id}_bg`}
            x={0}
            y={0}
            fill={txt.backgroundColor}
            listening
            cornerRadius={6}
          />
        )}
  <Text
  text={
    txt.isMention
      ? `@ ${txt.text}`
      : txt.isLink
      ? `🔗 ${txt.text}`
      : txt.isHashtag
      ? `# ${txt.text}`
      : txt.text
  }
  fontSize={20}
  fillLinearGradientStartPoint={{ x: 0, y: 0 }}
  fillLinearGradientEndPoint={{ x: txt.text.length * 20, y: 0 }} // Horizontal gradient
  fillLinearGradientColorStops={
    // If it's a special text type (mention, link, or hashtag), use gradient
    (txt.isMention || txt.isLink || txt.isHashtag)
      ? [
          0, getTextGradient().colors[0],
          0.25, getTextGradient().colors[1],
          0.5, getTextGradient().colors[2],
          0.75, getTextGradient().colors[3],
          1, getTextGradient().colors[4]
        ]
      : [0, txt.fontColor, 1, txt.fontColor]
  }
  fontStyle={txt.isMention || txt.isLink || txt.isHashtag ? 'bold' : 'normal'}
  x={5}
  y={5}
  ref={(node) => {
    if (node && txt.showBackground) {
      const newWidth = node.width() + 10;
      const newHeight = node.height() + 10;
      const rect = node.getParent().findOne(`#${txt.id}_bg`);
      if (rect) {
        rect.width(newWidth);
        rect.height(newHeight);
      }
    }
  }}
/>
      </Group>
    ))}

{selectedId && textGroups.find(t => t.id === selectedId) && (
  <Transformer
    ref={trRef}
    rotateEnabled={true}
    enabledAnchors={[
      "top-left",
      "top-right",
      "bottom-left",
      "bottom-right"
    ]}
    rotateAnchorOffset={50}
  />
)}
    <TransformerComponent selectedShape={getSelectedNode()} />
  </Layer>
</Stage>
</div>

</div>
    </div>
    </div>
    </div>
    </div>

  );
};

export default CreateStory;