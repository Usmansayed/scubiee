import React, { useState, useEffect, useRef, useCallback, useMemo ,useLayoutEffect} from 'react';
import axios from 'axios';
import Picker from 'emoji-picker-react';
import { FiSend, FiSearch, FiAlertCircle, FiHeart, FiMessageSquare } from 'react-icons/fi';
import { BsEmojiSmile } from 'react-icons/bs';
import ScrollToBottom from 'react-scroll-to-bottom';
import { useSelector, useDispatch } from 'react-redux';
import { IoClose } from "react-icons/io5";
import { IoMdMore } from "react-icons/io";
import { IoArrowBack } from 'react-icons/io5'; // add this import at the top
import { RiVerifiedBadgeFill } from "react-icons/ri";
import { useNavigate, useParams } from 'react-router-dom'; // Add useParams import
import imageCompression from 'browser-image-compression';
const cloud = import.meta.env.VITE_CLOUD_URL;

import './App.css'; // Import the CSS file

import { FaReply } from "react-icons/fa";
import { MdContentCopy } from "react-icons/md";
import { RiDeleteBin6Line } from "react-icons/ri";
import { AiOutlineUsergroupDelete } from "react-icons/ai";
import { FaPlus } from "react-icons/fa6";
import { setRecentChats, updateRecentChat,  } from './Slices/ChatSlice';
import { debounce } from 'lodash';
import { FixedSizeList as List } from 'react-window';
import socket from './socket';
import { PulseLoader } from 'react-spinners';
// At the top of your Chat.jsx file, add these imports
import { RiFullscreenLine } from "react-icons/ri";
import { MdOutlineFileDownload } from "react-icons/md";

const Chat = () => {
  const { userId } = useParams(); // Extract userId from URL parameter
  const dispatch = useDispatch();
  const api = import.meta.env.VITE_API_URL;
  const Domain = import.meta.env.Domain;
  const [tempBlobMessages, setTempBlobMessages] = useState(new Map());
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [noMoreMessages, setNoMoreMessages] = useState(false);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [showNetworkError, setShowNetworkError] = useState(false);
  const vcloud = import.meta.env.VITE_VIDEO_CLOUD_URL;
  const [highlightedMessageId, setHighlightedMessageId] = useState(null);
  const navigate = useNavigate();
  const createGroupBoxRef = useRef(null)
  const [showCreateGroupBox, setShowCreateGroupBox] = useState(false)
  
  // Add a specific loading state for direct URL access
  const [isUrlUserLoading, setIsUrlUserLoading] = useState(!!userId);

  const [selectedUser, setSelectedUser] = useState(null);
  const [messages, setMessages] = useState({});
  const [newMessage, setNewMessage] = useState('');
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [selectedReaction, setSelectedReaction] = useState(null);

  const [searchResults, setSearchResults] = useState([]);
  const [sentMessageIds] = useState(new Set());

 const [selectedReactionDetails, setSelectedReactionDetails] = useState(null);
 const [alertMessage, setAlertMessage] = useState(null);
 const [isLoadingMoreChats, setIsLoadingMoreChats] = useState(false);
 const [noMoreRecentChats, setNoMoreRecentChats] = useState(false); // <-- ADD THIS
 


  const [currentUser, setCurrentUser] = useState(null);
  const recentChats = useSelector(state => state.chat.recentChats);
  const [onlineUsers, setOnlineUsers] = useState(new Set());
  const [contextMenu, setContextMenu] = useState(null);
  const [replyToMessage, setReplyToMessage] = useState(null);
  const chatWindowRef = useRef(null);
  const activelyViewing = useRef(new Set());
  const emojiPickerRef = useRef(null);
  const contextMenuRef = useRef(null);
  const [emojiContextMenu, setEmojiContextMenu] = useState(null);
  const scrollBlockClass = "overflow-hidden";
  const messageRefs = useRef({});

  const [imagePreview, setImagePreview] = useState(null);
  const [imageCaption, setImageCaption] = useState('');
  const [isImageUploading, setIsImageUploading] = useState(false); // New state for tracking image upload process

  const reactionRemoveRef = useRef(null);
  const [chatType, setChatType]= useState(0)
  const [ displayReactionRemove,setDisplayReactionRemove ] = useState(null)
  const [isRoomJoined, setIsRoomJoined] = useState(false);
  const [changeUser, setChangeUser] = useState(null)
  const [chatOpened, setChatOpened] = useState(false);
  const previousScroll = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const [isPageLoading, setIsPageLoading] = useState(false);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const initialLoad = useRef(true);
  const [missedCount, setMissedCount] = useState(0);
  const recentChatsContainerRef = useRef(null);
  const recentChatsPrevScroll = useRef(null);
  const [longPressTimer, setLongPressTimer] = useState(null);
  const [showEmojiMenu, setShowEmojiMenu] = useState(false);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const [isSmallScreen, setIsSmallScreen] = useState(window.innerWidth < 768); // Example breakpoint
  const [activeChatOptions, setActiveChatOptions] = useState(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [chatToDelete, setChatToDelete] = useState(null);
  const pressTimerRef = useRef(null);
  const [selectedPost, setSelectedPost] = useState(null);
  const [isReturningFromPost, setIsReturningFromPost] = useState(false); // Add this state

  const [replyPostSummary, setReplyPostSummary] = useState(null);
  const [isInitialFetch, setIsInitialFetch] = useState(true);
  const lastFetchRef = useRef(null);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [fullscreenImage, setFullscreenImage] = useState(null);
  const emojiPickerContainerRef = useRef(null);
  const [loadingImages, setLoadingImages] = useState({});

  useEffect(() => {
    const handler = (e) => {
      // Only prevent right-click context menu on media elements
      if ((e.target.tagName === "VIDEO" || e.target.tagName === "IMG") && e.type === "contextmenu") {
        e.preventDefault();
      }
    };
    
    // Make sure we're only attaching to the contextmenu event
    document.addEventListener("contextmenu", handler);
    
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  useEffect(() => {
    const handleClickOutsideEmojiPicker = (event) => {
      if (
        showEmojiPicker &&
        emojiPickerContainerRef.current && 
        !emojiPickerContainerRef.current.contains(event.target) &&
        !event.target.classList.contains('emoji-picker-trigger')
      ) {
        setShowEmojiPicker(false);
      }
    };
  
    document.addEventListener('mousedown', handleClickOutsideEmojiPicker);
    
    return () => {
      document.removeEventListener('mousedown', handleClickOutsideEmojiPicker);
    };
  }, [showEmojiPicker]);

  const PostSkeleton = () => (
    <div className="my-4 bg-white/5 rounded-lg px-2 pb-3 pt-1 min-w-[280px] w-[340px]  max-md:min-w-[270px]  max-md:max-w-[340px] max-w-[420px]  animate-pulse">
      <div className="flex items-center gap-2 mb-[6px]">
        <div className="w-8 h-8 rounded-full bg-[#0a0a0a]"></div>
        <div className="h-4 w-24 bg-[#0a0a0a] rounded"></div>
      </div>
      <div className="w-full [aspect-ratio:9/6] bg-[#0a0a0a] rounded-md"></div>
      <div className="mt-2 space-y-2">
        <div className="h-4 w-3/4 bg-[#0a0a0a] rounded"></div>
        <div className="h-4 w-1/2 bg-[#0a0a0a] rounded"></div>
      </div>
    </div>
  );

  const ReplyPostSkeleton = () => (
    <div className="my-4 bg-white/5 rounded-lg px-2 pb-3 pt-1 min-w-[320px] max-w-[400px] animate-pulse">
      <div className="flex items-center gap-2 mb-[6px]">
        <div className="w-8 h-8 rounded-full bg-[#0a0a0a]"></div>
        <div className="h-4 w-24 bg-[#0a0a0a] rounded"></div>
      </div>
      <div className="w-full [aspect-ratio:9/6] bg-[#0a0a0a] rounded-md"></div>
      <div className="mt-2 space-y-2">
        <div className="h-4 w-3/4 bg-[#0a0a0a] rounded"></div>
        <div className="h-4 w-1/2 bg-[#0a0a0a] rounded"></div>
      </div>
    </div>
  );

  const ImageLoadingSkeleton = () => (
    <div className="relative flex items-center justify-center bg-white/5 w-[260px] md:w-[280px] lg:w-[320px]  aspect-square rounded-lg animate-pulse">
      <div className="absolute inset-0 bg-gradient-to-b from-gray-800 to-gray-900 opacity-70"></div>
      <div className="absolute inset-0 overflow-hidden">
        <div className="h-full w-4 bg-gradient-to-r from-transparent via-gray-700/30 to-transparent animate-[shimmer_1.5s_infinite]" 
             style={{ backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite', animationTimingFunction: 'linear' }}></div>
      </div>
      <div className="z-10 flex flex-col items-center justify-center space-y-2">
        <div className="w-10 h-10 rounded-md bg-gray-700/50"></div>
        <div className="w-16 h-2 rounded-full bg-gray-700/50"></div>
      </div>
      <div className="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-gray-900 to-transparent"></div>
    </div>
  );

  useEffect(() => {
    if (isSmallScreen && selectedUser) {
      // When a user is selected on mobile, push a new history state
  
      // Add event listener for popstate (back button press)
      const handlePopState = (event) => {
        // Close the selected chat when the back button is pressed
        setSelectedUser(null);
      };
  
      window.addEventListener("popstate", handlePopState);
      
      return () => {
        // Clean up event listener when component unmounts or chat closes
        window.removeEventListener("popstate", handlePopState);
      };
    }
  }, [isSmallScreen, selectedUser]);


useEffect(() => {
  if (isSmallScreen && !selectedUser) {
    document.body.classList.add('no-scroll');
    document.documentElement.classList.add('no-scroll');
  } else {
    document.body.classList.remove('no-scroll');
    document.documentElement.classList.remove('no-scroll');
  }
  // Clean up on unmount
  return () => {
    document.body.classList.remove('no-scroll');
    document.documentElement.classList.remove('no-scroll');
  };
}, [isSmallScreen, selectedUser]);

  // Handle navigation from ViewPost back to chat
  useEffect(() => {
    // Check if user is returning from viewing a post
    const checkReturnFromPost = () => {
      const referrer = document.referrer;
      // Set returning state if coming from post view
      if (referrer && referrer.includes('/viewpost/')) {
        setIsReturningFromPost(true);
        // Reset after a delay to ensure proper display
        setTimeout(() => {
          setIsReturningFromPost(false);
        }, 1000);
      }
    };

    // Check when component mounts or when selectedUser changes
    checkReturnFromPost();
  }, [selectedUser]);

useEffect(() => {
  if (replyToMessage && replyToMessage.isPost) {
    axios
      .get(`${api}/post/summary/${replyToMessage.content}`, {
        withCredentials: true,
      })
      .then((response) => {
        setReplyPostSummary(response.data);
      })
      .catch((error) => {
        console.error("Error fetching reply post summary:", error);
      });
  } else {
    setReplyPostSummary(null);
  }
}, [replyToMessage]);

  let pressTimer = null;

  const handleDeleteChatroom = async (chatRoomId) => {
    try {
      const response = await axios.post(
        `${api}/chat/delete-chatroom`,
        { roomId: chatRoomId },
        { withCredentials: true }
      );
      if (response.data.success) {
        dispatch({ type: 'chat/removeRecentChat', payload: chatRoomId });
        console.log(recentChats)
      }
    } catch (error) {
      console.error('Error deleting chatroom:', error);
    }
  };

  useEffect(() => {
    if (highlightedMessageId) {
      const timer = setTimeout(() => {
        setHighlightedMessageId(null);
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [highlightedMessageId]);

  const handleTouchStart = (e, message) => {
      // Don't process touch events for buttons or their children
  if (e.target.tagName === 'BUTTON' || 
    e.target.closest('button') || 
    e.target.tagName === 'svg' ||
    e.target.tagName === 'path') {
  return;
}
    if (window.innerWidth >= 768) return;
    
    // Prevent default browser behavior (text selection and context menu)
    e.stopPropagation();
  
    const targetElement = e.currentTarget;
    if (!targetElement) return;
  
    pressTimer = setTimeout(() => {
      if (!targetElement) return;
      const messageRect = targetElement.getBoundingClientRect();
      const isSender = message.senderId === currentUser.id;
      const menuHeight = 200;
      let emojiY = messageRect.bottom + window.scrollY;
      let top = messageRect.bottom + window.scrollY;
      if (top + menuHeight > window.innerHeight) {
        top = window.innerHeight - menuHeight + 6;
        emojiY = window.innerHeight - menuHeight + 54;
      }
      setContextMenu({
        mouseX: isSender ? 0 : window.innerWidth - 165,
        mouseY: top,
        message,
        isSender
      });
  
      setEmojiContextMenu({
        mouseX: isSender ? 0 : window.innerWidth - 400,
        mouseY: emojiY,
        message,
        isSender
      });
    }, LONG_PRESS_DELAY);
  };

  const handleTouchEnd = (e) => {
    // Don't interfere with button events
    if (e.target.tagName === 'BUTTON' || 
        e.target.closest('button') ||
        e.target.tagName === 'svg' ||
        e.target.tagName === 'path') {
      clearTimeout(pressTimer);
      return;
    }
    
    // Rest of your existing code
    if (e.cancelable && e.target.tagName !== 'A') {
      e.preventDefault();
    }
    clearTimeout(pressTimer);
  };

  useEffect(() => {
    const handleResize = () => {
      setIsSmallScreen(window.innerWidth < 768);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

// Update the handleBackToChats function
const handleBackToChats = () => {
  if (isSmallScreen) {
    // If we manually go back using the UI back button, we need to replace the current state
    // to avoid having multiple history entries
    window.history.replaceState(null, "");
  }
  setSelectedUser(null);
};

  const handleAngleDownClick = () => {
    if (isSmallScreen) {
      setShowEmojiMenu(true);
      setShowContextMenu(true);
    } else {
      // Handle the default behavior for larger screens if needed
      setShowContextMenu(!showContextMenu); // Example: toggle context menu only
    }
  };


// Update the fetchMoreRecentChats function
const fetchMoreRecentChats = async () => {
  if (!recentChats.length || isLoadingMoreChats || noMoreRecentChats) return; // <-- ADD noMoreRecentChats check

  setIsLoadingMoreChats(true);
  const container = recentChatsContainerRef.current;
  if (container) {
    recentChatsPrevScroll.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    };
  }

  try {
    const lastChatRoomId = recentChats[recentChats.length - 1].chatRoomId;
    const response = await axios.get(
      `${api}/chat/recent-chats?lastChatRoomId=${lastChatRoomId}`,
      { withCredentials: true }
    );
    if (response.data && response.data.length) {
      // Prevent duplicates by filtering out chats already in recentChats
      const existingIds = new Set(recentChats.map(c => c.chatRoomId));
      const newChats = response.data.filter(chat => !existingIds.has(chat.chatRoomId));
      if (newChats.length === 0) {
        setNoMoreRecentChats(true); // No new unique chats
      } else {
        dispatch(setRecentChats([...recentChats, ...newChats]));
      }
    } else {
      setNoMoreRecentChats(true); // <-- SET FLAG IF NO MORE CHATS
    }
  } catch (error) {
    console.error('Error fetching more recent chats:', error);
  } finally {
    setIsLoadingMoreChats(false);
  }
};
  // Add a useLayoutEffect to adjust scroll position after recentChats update:
useLayoutEffect(() => {
  const container = recentChatsContainerRef.current;
  if (container && recentChatsPrevScroll.current) {
    const diff = container.scrollHeight - recentChatsPrevScroll.current.scrollHeight;
    container.scrollTop = recentChatsPrevScroll.current.scrollTop + diff;
    recentChatsPrevScroll.current = null;
  }
}, [recentChats])
  
    // onScroll handler for the recent chats container
    const handleRecentChatsScroll = (e) => {
      const { scrollTop, scrollHeight, clientHeight } = e.target;
      if (scrollTop + clientHeight >= scrollHeight - 10) {
        fetchMoreRecentChats();
      }
    };
  

  useLayoutEffect(() => {
    if (chatWindowRef.current) {
      chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
    }
    // Reset initialLoad so that subsequent updates run the effect normally.
    initialLoad.current = true;
  }, [selectedUser]);
  
  useEffect(() => {
    if (!chatWindowRef.current || !currentUser || !selectedUser || isLoadingMore) return;
  
    const timer = setTimeout(() => {
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      const roomMessages = messages[roomId] || [];
  
      if (roomMessages.length === 0) {
        setShowScrollDown(false);
        return;
      }
  
      const { scrollTop, scrollHeight, clientHeight } = chatWindowRef.current;
  
      // If the user is near the top (likely fetching older messages), don't show the button.
      if (scrollTop < 50) {
        setShowScrollDown(false);
        return;
      }
  
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
  
      // For the very first load, do not show the button.
      if (initialLoad.current) {
        initialLoad.current = false;
        setShowScrollDown(false);
        return;
      }
  
      const lastMessage = roomMessages[roomMessages.length - 1];
  
      // Show scroll down button only if the last message is from the other user and user is not near bottom.
      if (lastMessage.senderId !== currentUser.id && !isNearBottom) {
        setShowScrollDown(true);
      } else {
        setShowScrollDown(false);
      }
    }, 100); // small delay for DOM update
  
    return () => clearTimeout(timer);
  }, [messages, currentUser, selectedUser, isLoadingMore]);
  
  const handleChatScroll = () => {
    if (!chatWindowRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = chatWindowRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
    if (isNearBottom) {
      setMissedCount(0);
    }
  };

  useEffect(() => {
    // existing logic when selectedUser changes
    setMissedCount(0);
  }, [selectedUser]);
  
  useEffect(() => {
    if (!chatWindowRef.current) return;
    chatWindowRef.current.addEventListener('scroll', handleChatScroll);
    return () => chatWindowRef.current.removeEventListener('scroll', handleChatScroll);
  }, []);


  // When user clicks the scroll down button
  const handleScrollToBottom = () => {
    if (chatWindowRef.current) {
      chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
      setMissedCount(0);
    }
  };
 useEffect(() => {

    if (!chatWindowRef.current) return;
    
    const { scrollTop, scrollHeight, clientHeight } = chatWindowRef.current;
    
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
    
    if (isNearBottom) {
    
    chatWindowRef.current.scrollTop = scrollHeight;
    
    }
    
    }, [messages]);

    const fetchMoreMessages = async () => {
      if (!selectedUser || !currentUser) return;
      if (isLoadingMore || noMoreMessages) return;
      if (lastFetchRef.current && Date.now() - lastFetchRef.current < 1000) return;
      
      setIsLoadingOlder(true); // Show loading indicator
      lastFetchRef.current = Date.now();
    
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      const currentMessages = messages[roomId] || [];
      
      if (currentMessages.length === 0 && !isInitialFetch) return;
    
      if (chatWindowRef.current) {
        previousScroll.current = {
          scrollTop: chatWindowRef.current.scrollTop,
          scrollHeight: chatWindowRef.current.scrollHeight,
        };
      }
    
      setIsLoadingMore(true);
      try {
        const lastMessageId = currentMessages.length > 0 ? currentMessages[0].id : null;
        const response = await axios.get(
          `${api}/chat/messages/${roomId}${lastMessageId ? `?lastMessageId=${lastMessageId}` : ''}`, 
          { withCredentials: true }
        );
    
        if (response.data && response.data.length > 0) {
          setMessages(prevMessages => ({
            ...prevMessages,
            [roomId]: [...response.data, ...(prevMessages[roomId] || [])]
          }));
          
          if (response.data.length < 20) {
            setNoMoreMessages(true);
          }
        } else {
          setNoMoreMessages(true);
        }
      } catch (error) {
        console.error("Error fetching more messages:", error);
      } finally {
        setIsLoadingMore(false);
        setIsLoadingOlder(false); // Hide loading indicator
        setIsInitialFetch(false);
      }
    };
    
  useLayoutEffect(() => {
    if (!isLoadingMore && previousScroll.current && chatWindowRef.current) {
      const diff = chatWindowRef.current.scrollHeight - previousScroll.current.scrollHeight;
      chatWindowRef.current.scrollTop = previousScroll.current.scrollTop + diff;
      previousScroll.current = null; // reset after using
    }
  }, [messages, isLoadingMore]);


  const ImageUploadWidget = ({ image, onClose, onSend, caption, setCaption }) => {
    return (
      <div className="absolute inset-0 bg-[#0a0a0a] z-10 flex flex-col">
        <div className="flex justify-between items-center p-4 border-b border-[#2c3117]">
          <h3 className="text-lg font-medium text-white">Send Image</h3>
          <button 
            onClick={onClose}
            className="text-gray-400 hover:text-white"
          >
            <IoClose size={24} />
          </button>
        </div>
        
        <div className="flex-1 flex items-center justify-center p-4">
          <img 
            src={URL.createObjectURL(image)} 
            alt="Preview" 
            className="max-h-[70vh] max-w-full object-contain rounded-lg"
          />
        </div>
        
        <div className="p-4 border-t border-[#2c3117] flex items-center gap-4">
          <input
            type="text"
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="Add a caption..."
            className="flex-1 p-2 bg-[#272726]  rounded-lg text-white"
          />
          <button 
            onClick={onSend}
            className="text-gray-400 hover:text-gray-600 p-2"
          >
            <FiSend size={28} />
          </button>
        </div>
      </div>
    );
  };
  const handleOfflineReactionUpdate = (messageId, reaction) => {
    if (isRoomJoined) return;
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    setMessages((prevMessages) => {
      const updatedMessages = { ...prevMessages };
      const msgs = updatedMessages[roomId] || [];
      const idx = msgs.findIndex((m) => m.id === messageId);
      if (idx !== -1) {
        // Assume currentUser is the sender
        msgs[idx].sendersReaction = reaction;
        updatedMessages[roomId] = [...msgs];
      }
      return updatedMessages;
    });
  };
  
  const handleOfflineDeleteMessage = (messageId) => {
    if (isRoomJoined) return;
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    setMessages((prevMessages) => {
      const updatedMessages = { ...prevMessages };
      updatedMessages[roomId] = (updatedMessages[roomId] || []).filter(
        (msg) => msg.id !== messageId
      );
      return updatedMessages;
    });
  };
  
  
  // Modify handleImageUpload:
  const handleImageUpload = useCallback(async (e) => {
    const file = e.target.files[0];
    if (!file) return;
  
    // Set loading state to true when starting the upload
    setIsImageUploading(true);

    // Validate file type
    const fileType = file.type;
    if (!['image/jpeg', 'image/jpg', 'image/png'].includes(fileType)) {
      alert('Only JPEG, JPG, and PNG images are allowed.');
      setIsImageUploading(false);
      return;
    }
  
    if (file.size > 10 * 1024 * 1024) {
      alert('File too large (max 10MB).');
      setIsImageUploading(false);
      return;
    }
  
    try {
      const options = {
        maxSizeMB: 1,
        maxWidthOrHeight: 1920,
        useWebWorker: true,
        fileType: file.type,
        initialQuality: 0.8
      };
  
      const compressedFile = await imageCompression(file, options);
      setImagePreview(compressedFile);
      setImageCaption('');
    } catch (error) {
      console.error('Error compressing image:', error);
    } finally {
      setIsImageUploading(false); // Reset loading state
    }
  }, []);
  
  const handleSendImage = async () => {
    if (!imagePreview || !currentUser?.id || !selectedUser?.id) return;
    
    if (!isOnline) {
      toast.warning("You're offline. Please try again when connected.");
      return;
    }
    
    try {
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      const tempMsgId = `temp_${Date.now()}`;
      
      // Add temporary message with notification text
      setMessages(prevMessages => ({
        ...prevMessages,
        [roomId]: [
          ...(prevMessages[roomId] || []),
          {
            id: tempMsgId,
            senderId: currentUser.id,
            content: 'Your image is being sent...',
            chatRoomId: roomId,
            createdAt: new Date().toISOString(),
            isTemp: true, // Flag to identify temporary messages
          }
        ]
      }));
      
      // Clear the preview immediately to avoid duplicate sends
      setImagePreview(null);
      
      const options = {
        maxSizeMB: 1,
        maxWidthOrHeight: 1920,
        useWebWorker: true,
        fileType: imagePreview.type,
        initialQuality: 0.8
      };
      
      // Compress the image
      const compressedFile = await imageCompression(imagePreview, options);
      const formData = new FormData();
      formData.append('image', compressedFile);
      formData.append('senderId', currentUser.id);
      formData.append('receiverId', selectedUser.id);
      formData.append('caption', imageCaption);
    
      // Upload the image
      const response = await axios.post(`${api}/chat/upload-image`, formData, {
        withCredentials: true
      });
    
      if (response.data.success) {
        const fileName = response.data.fileName;        
        // Update recent chats immediately with the correct read status
        dispatch(updateRecentChat({
          chatRoomId: roomId,
          updates: {
            lastMessage: 'Image',
            lastMessageSenderId: currentUser.id,
            lastMessageRead: activelyViewing.current.has(roomId)
          }
        }));
    
        socket.emit('sendMessage', {
          roomId,
          UserDetails: [currentUser.id, selectedUser.id],
          content: fileName, // file name from the backend
          isMedia: true,
          caption: imageCaption || '',
          createdAt: new Date(),
        });
        
        // Clear any leftover caption in state
        setImageCaption('');
        
        // Automatically remove the temporary message after 4 seconds
        setTimeout(() => {
          setMessages(prevMessages => {
            const updatedMessages = { ...prevMessages };
            updatedMessages[roomId] = updatedMessages[roomId].filter(msg => msg.id !== tempMsgId);
            return updatedMessages;
          });
        }, 4000);
      }
    } catch (error) {
      console.error('Error sending image:', error);
    }
  };
  
  const handleScrollToMessage = (messageId) => {
    const targetRef = messageRefs.current[messageId];
    if (targetRef && chatWindowRef.current) {
      setHighlightedMessageId(messageId);
      const containerRect = chatWindowRef.current.getBoundingClientRect();
      const targetRect = targetRef.getBoundingClientRect();
      // Add 40px offset to the scroll position
      const offset = targetRect.top - containerRect.top + chatWindowRef.current.scrollTop - 12;
      chatWindowRef.current.scrollTo({ top: offset, behavior: 'smooth' });
    }
  };

  useEffect(() => {
    const fetchUserData = async () => {
      try {
        const response = await axios.get(`${api}/user/user`, { withCredentials: true });

        setCurrentUser(response.data);
      } catch (error) {
        console.error('Error fetching user data:', error);
      }
    };

    fetchUserData();
  }, []);

  useEffect(() => {
    const fetchRecentChats = async () => {
      try {
        const response = await axios.get(`${api}/chat/recent-chats`, { withCredentials: true });
        dispatch(setRecentChats(response.data));
      } catch (error) {
        console.error('Error fetching recent chats:', error);
      }
    };
  
    fetchRecentChats();
  }, [dispatch]);


  useEffect(() => {
    if (selectedUser && currentUser) {
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      socket.emit('enterRoom', { roomId, userId: currentUser.id });
      socket.emit('openChat', { roomId, userId: currentUser.id });
    }
  }, [selectedUser, currentUser]);

useEffect(() => {
  const newSocket = socket;
  
  // Initialize the online users set from both initial data and socket events
  const initializeOnlineUsers = async () => {
    try {
      // Request the current online users status from the server
      newSocket.emit('requestOnlineUsers');
      
      // Also use the isOnline flag from recentChats to initialize our set
      if (recentChats && recentChats.length) {
        setOnlineUsers(prevOnlineUsers => {
          const newSet = new Set(prevOnlineUsers);
          recentChats.forEach(chat => {
            if (chat.otherUser?.isOnline) {
              // Store ID as string instead of parseInt
              newSet.add(String(chat.otherUser.id));
            }
          });
          return newSet;
        });
      }
    } catch (error) {
      console.error('Error initializing online users:', error);
    }
  };
  
  initializeOnlineUsers();

  // Add handler for initial online users
  newSocket.on('initialOnlineUsers', ({ users }) => {
    console.log('Received initialOnlineUsers:', users);
    // Convert array of user objects or IDs to a Set of IDs (as strings)
    const onlineUserIds = new Set(users.map(user => 
      typeof user === 'object' ? String(user.id) : String(user)
    ));
    
    setOnlineUsers(prevUsers => {
      const updatedSet = new Set(prevUsers);
      onlineUserIds.forEach(id => updatedSet.add(id));
      return updatedSet;
    });
  });

  // Handle user coming online - store as string
  newSocket.on('userOnline', ({ userId }) => {
    console.log('User online event received for:', userId);
    setOnlineUsers(prev => {
      const newSet = new Set(prev);
      newSet.add(String(userId)); // Store as string
      return newSet;
    });
  });

  // Handle user going offline - ensure consistent string format
  newSocket.on('userOffline', ({ userId }) => {
    console.log('User offline event received for:', userId);
    setOnlineUsers(prev => {
      const newSet = new Set(prev);
      newSet.delete(String(userId)); // Compare as string
      return newSet;
    });
  });

  // When recentChats changes, update online users from isOnline flag
  const updateOnlineUsersFromChats = () => {
    if (recentChats && recentChats.length) {
      setOnlineUsers(prevUsers => {
        const updatedSet = new Set(prevUsers);
        recentChats.forEach(chat => {
          if (chat.otherUser?.isOnline) {
            updatedSet.add(String(chat.otherUser.id));
          }
        });
        return updatedSet;
      });
    }
  };

  updateOnlineUsersFromChats();

  return () => {
    newSocket.off('initialOnlineUsers');
    newSocket.off('userOnline');
    newSocket.off('userOffline');
  };
}, [currentUser, recentChats]); // Added recentChats as dependency

  useEffect(() => {
  
    const newSocket = socket;

    // Add handler for initial online users
    newSocket.on('initialOnlineUsers', ({ users }) => {
      setOnlineUsers(new Set(users));
    });

    newSocket.on('userOnline', ({ userId }) => {
      setOnlineUsers(prev => new Set([...prev, userId]));
    });

    newSocket.on('userOffline', ({ userId }) => {
      setOnlineUsers(prev => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    });

    newSocket.on('receive_message', (message) => {
      console.log('New message received:', message);
    
      // Check if the chatRoomId exists in the activelyViewing Set
      const isActive = activelyViewing.current.has(message.chatRoomId);
    
      setMessages((prevMessages) => ({
        ...prevMessages,
        [message.chatRoomId]: [
          ...(prevMessages[message.chatRoomId] || []),
          { 
            ...message, 
            read: activelyViewing.current.has(message.chatRoomId)
          }
        ]
      }));

      if (currentUser && message.senderId !== currentUser.id && chatWindowRef.current) {
        const { scrollTop, scrollHeight, clientHeight } = chatWindowRef.current;
        const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
        if (!isNearBottom) {
          setMissedCount(prev => prev + 1);
        }
      }
    
      // Update recent chats
      dispatch(updateRecentChat({
        chatRoomId: message.chatRoomId,
        updates: {
          lastMessage: message.isMedia ? 'Image' : message.content,
          lastMessageSenderId: message.senderId,
          lastMessageRead: false
        }
      }));
    
      // If actively viewed, emit the 'messageSeen' event immediately
    
    });
    
    newSocket.on('messagesRead', ({ roomId, userId }) => {
      // Update recentChats read status
      setRecentChats((prevChats) => 
        prevChats.map(chat => {
          if (chat.chatRoomId === roomId) {
            return { ...chat, lastMessageRead: true };
          }
          return chat;
        })
      );
    
      // Update messages read status
      setMessages((prevMessages) => {
        const updatedMessages = { ...prevMessages };
        if (updatedMessages[roomId]) {
          updatedMessages[roomId] = updatedMessages[roomId].map((msg) =>
            msg.senderId !== userId ? { ...msg, read: true } : msg
          );
        }
        return updatedMessages;
      });
    });

    newSocket.on('messageSeen', ({ messageId, userId }) => {
      console.log('Message seen event received for message:', messageId);
    
 
      setMessages((prevMessages) => {
        const updatedMessages = { ...prevMessages };
        for (const roomId in updatedMessages) {
          updatedMessages[roomId] = updatedMessages[roomId].map((msg) =>
            msg.id === messageId ? { ...msg, read: true } : msg
          );
        }
        return updatedMessages;
      });
      
    });

    newSocket.on('userOpenedChat', ({ roomId, userId, BrowserUser }) => {
      if (currentUser.id !== BrowserUser) {
          activelyViewing.current.add(roomId);
          console.log(`User ${userId} opened chat in room ${roomId}`);
      }
    });
  
    newSocket.on('userClosedChat', ({ roomId, userId, BrowserUser }) => {
      if (currentUser.id !== BrowserUser) {
          activelyViewing.current.delete(roomId);
          console.log(`User ${userId} closed chat in room ${roomId}`);
      }
    });

    newSocket.on('userOnline', ({ userId }) => {
      setOnlineUsers((prevOnlineUsers) => new Set(prevOnlineUsers).add(userId));
    });

    newSocket.on('userOffline', ({ userId }) => {
      setOnlineUsers((prevOnlineUsers) => {
        const updatedOnlineUsers = new Set(prevOnlineUsers);
        updatedOnlineUsers.delete(userId);
        return updatedOnlineUsers;
      });
    });

    newSocket.on('currentOnlineUsers', ({ roomId, onlineUsers }) => {
      setOnlineUsers((prevOnlineUsers) => {
        const updatedOnlineUsers = new Set(prevOnlineUsers);
        onlineUsers.forEach(userId => updatedOnlineUsers.add(userId));
        return updatedOnlineUsers;
      });
    });

    newSocket.on('messageDeleted', ({ messageId, roomId }) => {
      setMessages((prevMessages) => {
        const updatedMessages = { ...prevMessages };
        if (updatedMessages[roomId]) {
          updatedMessages[roomId] = updatedMessages[roomId].filter((msg) => msg.id !== messageId);
        }
        return updatedMessages;
      });
    });

    // Emit an event to notify the server that the user has refreshed the page
    newSocket.emit('userRefreshed', { userId: currentUser?.id });

  }, [currentUser]);

  const formatLastMessage = (message, isMedia, currentUserId, senderId, read, lastActivity) => {
    console.log('Message:', message, 'LastActivity:', lastActivity);
  
    // 1) Check if this is a reaction activity
    if (lastActivity?.reaction) {
      return lastActivity.senderId === currentUserId 
        ? `You reacted ${lastActivity.reaction} to a message`
        : `Reacted ${lastActivity.reaction} to a message`;
    }
  
    // 2) If this message is a reply
    if (message && typeof message === 'object' && message.replyToMessageId ) {
      return currentUserId === senderId
        ? 'You replied to a message'
        : 'replied to a message';
    }
  
    // 3) If this message is a post
    if (message && typeof message === 'object' && message.isPost) {
      return currentUserId === senderId
        ? 'You sent an post'
        : 'sent an post';
    }
  
    // 4) Handle media
    let messageText = '';
    if (message && typeof message === 'object') {
      messageText = message.content || '';
    } else if (typeof message === 'string') {
      messageText = message;
    }
  
    if (isMedia || (messageText && (/\.(jpg|png|jpeg)$/i).test(messageText))) {
      return currentUserId === senderId ? 'You sent an image' : 'Sent an image';
    }
  
    // 5) Handle text
    if (messageText) {
      return messageText.length > 30
        ? `${messageText.substring(0, 30)}...`
        : messageText;
    }
  
    return 'No messages yet';
  };

  useEffect(() => {
    const roomId = selectedUser ? [currentUser.id, selectedUser.id].sort().join('_') : null;
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        if (selectedUser && currentUser && socket) {
          socket.emit('enterRoom', { roomId, userId: currentUser.id });
          socket.emit('openChat', { roomId, userId: currentUser.id });
          // fetchCurrentChatMessages();
        }
      } else if (document.visibilityState === 'hidden' && selectedUser && currentUser) {
        socket.emit('leftRoom', { roomId, userId: currentUser.id });
        socket.emit('closeChat', { roomId, userId: currentUser.id });
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [selectedUser, currentUser]);

  useEffect(() => {
    return () => {
      if (selectedUser && currentUser && socket) {
        const roomId = [currentUser.id, selectedUser.id].sort().join('_');
        socket.emit('leftRoom', { roomId, userId: currentUser.id });
        socket.emit('closeChat', { roomId, userId: currentUser.id });
      }
    };
  }, [location, selectedUser, currentUser]);

  useEffect(() => {
    const handleBeforeUnload = () => {
      if (selectedUser && currentUser && socket) {
        const roomId = [currentUser.id, selectedUser.id].sort().join('_');
        socket.emit('leftRoom', { roomId, userId: currentUser.id });
        socket.emit('closeChat', { roomId, userId: currentUser.id });
      }
    };
  
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [selectedUser, currentUser, socket]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (reactionRemoveRef.current && !reactionRemoveRef.current.contains(event.target)) {
        setDisplayReactionRemove(null);
      }
    };
  
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [reactionRemoveRef]);




  useEffect(() => {
    const handleBeforeUnload = () => {
      if (selectedUser && currentUser && socket) {
        const roomId = [currentUser.id, selectedUser.id].sort().join('_');
        socket.emit('closeChat', { roomId, userId: currentUser.id });
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [selectedUser, currentUser, socket]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (emojiContextMenu && emojiPickerRef.current && !emojiPickerRef.current.contains(event.target)) {
        setEmojiContextMenu(null); 
      }
      if (contextMenu && contextMenuRef.current && !contextMenuRef.current.contains(event.target)) {
        setContextMenu(null);
      }
    };
  
    // Add mousedown event listener
    document.addEventListener('mousedown', handleClickOutside);
  
    // Cleanup
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [emojiContextMenu, contextMenu]); 

  
  // Update the click handlers
  const handleOptionsClick = (event, message) => {
    event.stopPropagation();
    event.preventDefault();
  
    // Close emoji menu if open
    setEmojiContextMenu(null);
  
    const elementRect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 155;
     const isSender = (message.senderId === currentUser.id);
    // Calculate available space below
    const availableSpaceBelow = window.innerHeight - elementRect.bottom;
    const menuHeight = availableSpaceBelow < 180 ? (isSender ? 300 : 220) : 0;
  
   
  
    let adjustedX = isSender ? elementRect.left - menuWidth - 100 : elementRect.right + 210;
    let adjustedY = elementRect.top + window.scrollY - (menuHeight / 2);
  
    // Toggle the context menu
    setContextMenu(prevState => 
      prevState?.message?.id === message.id ? null : {
        mouseX: adjustedX,
        mouseY: adjustedY,
        message,
        isSender,
      }
    );
  };

const handleEmojiPickerClick = (event, message) => {
  event.stopPropagation();

  // Close options menu if open
  setContextMenu(null);

  const elementRect = event.currentTarget.getBoundingClientRect();
  const menuWidth = 170;
  const menuHeight = 28;
  const isSender = (message.senderId === currentUser.id);

  let adjustedX = isSender ? elementRect.left - menuWidth - 200 : elementRect.right + 40;
  let adjustedY = elementRect.top + window.scrollY - (menuHeight / 2);

  // Toggle the emoji menu
  setEmojiContextMenu(prevState => 
    prevState?.message?.id === message.id ? null : {
      mouseX: adjustedX,
      mouseY: adjustedY,
      message,
      isSender,
    }
  );
};



   useEffect(() => {
      const handleUserScrollOrKey = (e) => {
        if (
          e.type === 'wheel' ||
          e.key === 'ArrowUp' ||
          e.key === 'ArrowDown' ||
          e.key === 'PageUp' ||
          e.key === 'PageDown'
        ) {
          setContextMenu(null);
          setEmojiContextMenu(null);
        }
      };
    
      window.addEventListener('wheel', handleUserScrollOrKey);
      document.addEventListener('keydown', handleUserScrollOrKey);
    
      return () => {
        window.removeEventListener('wheel', handleUserScrollOrKey);
        document.removeEventListener('keydown', handleUserScrollOrKey);
      };
    }, [setContextMenu, setEmojiContextMenu]);
  
  
    const handleUserClick = async (user) => {
      if (selectedUser && selectedUser.id === user.id) {
        console.log("User already selected, skipping action");
        return;
      }
      
      setIsPageLoading(true);
      setChangeUser(user);
      setNoMoreMessages(false);
      setIsInitialFetch(true);
      lastFetchRef.current = null;
      if (isSmallScreen) {
        window.history.pushState({ chatOpen: true }, "");
      }
    
   
    
      if (selectedUser) {
        const previousRoomId = selectedUser
          ? [currentUser.id, selectedUser.id].sort().join('_')
          : selectedGroup?.chatRoomId;
        socket.emit('leftRoom', { roomId: previousRoomId, userId: currentUser.id });
        socket.emit('closeChat', { roomId: previousRoomId, userId: currentUser.id });
      }
    
      setSelectedUser(user);
      setSelectedGroup(null);
      setSearchQuery('');
      setSearchResults([]);
      setChatOpened(true);
    
      if (!currentUser) {
        console.error('Current user not found');
        setIsPageLoading(false);
        return;
      }
    
      const roomId = [currentUser.id, user.id].sort().join('_');
      socket.emit('joinRoom', { userId: currentUser.id, otherUserId: user.id });
    
      try {
        const response = await axios.get(`${api}/chat/messages/${roomId}`, { withCredentials: true });
        setMessages((prevMessages) => ({
          ...prevMessages,
          [roomId]: response.data,
        }));
    
        if (document.visibilityState === 'visible') {
          socket.emit('enterRoom', { roomId, userId: currentUser.id });
          socket.emit('openChat', { roomId, userId: currentUser.id });
          dispatch(updateRecentChat({
            chatRoomId: roomId,
            updates: {
              lastMessageRead: true
            }
          }));
        }
      } catch (error) {
        console.error('Error fetching messages:', error);
      } finally {
        setIsPageLoading(false);
        setTimeout(() => {
          if (chatWindowRef.current) {
            chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
          }
        }, 50);
      }
      
      // Update URL without reloading the page - do this after all other operations
      if (user.id) {
        console.log("Updating URL to:", `/chat/${user.id}`);
        navigate(`/chat/${user.id}`, { replace: true });
      }
    };
  
    
  
  //--this is the handle send message which manages the sending of messages in the frontend , it also classifies whether a message is for group
  //--and if yes it sends the messag to the handle send message in group fuction 
  
    const handleSendMessage = () => {

      if (!newMessage.trim() || !currentUser) return;
     setTimeout(() => {
          if (chatWindowRef.current) {
            chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
          }
        }, 50);
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      const UserDetails = [currentUser.id, selectedUser.id];

      
    
      // If socket is offline, update recent chats locally with user's input
      if (!socket || !socket.connected) {
        dispatch(updateRecentChat({
          chatRoomId: roomId,
          updates: {
            lastMessage: newMessage,
            lastMessageSenderId: currentUser.id,
            lastMessageRead: false
          }
        }));
      } else {
        // Socket is active – send via socket with acknowledgement updating recent chats later
        socket.emit('sendMessage', {
          roomId,
          UserDetails,
          content: newMessage,
          replyToMessageId: replyToMessage?.id || null,
          createdAt: new Date()
        }, (ackMessage) => {
          // Optional: further update recent chats after acknowledgement if needed
        });
      }
    
      setNewMessage('');
      setReplyToMessage(null);
    };
  
  
    const handleEmojiClick = (emojiObject) => {
      setNewMessage((prevMessage) => prevMessage + emojiObject.emoji);
    };  
  
    // Debounced search function
    const debouncedSearch = useCallback(
      debounce(async (query) => {
        if (!query.trim()) {
          setSearchResults([]);
          return;
        }
        try {
          const response = await axios.post(
            `${api}/chat/search`, 
            { username: query },  // This is the request body
            { withCredentials: true }  // This is the config object
          );
          setSearchResults(response.data);
        } catch (error) {
          console.error('Error searching users:', error);
        }
      }, 300),
      []
    );
  
    const handleSearch = (e) => {
      setSearchQuery(e.target.value);
      debouncedSearch(e.target.value);
    };
  
    const handleCloseContextMenu = () => {
      setContextMenu(null);
    };
  
    const handleDeleteMessage = (messageId, roomId, deleteForEveryone = false) => {
      if (!socket.connected) {
        handleOfflineDeleteMessage(messageId);
        return;
      }
    
      socket.emit('deleteMessage', {
        roomId,
        senderId: currentUser.id,
        receiverId: selectedUser.id,
        messageId,
        deleteForEveryone
      });
      
      handleCloseContextMenu();
    };
  
    const handleDeleteFromMe = async (message) => {
      try {
        const response = await axios.post(`${api}/chat/delete-message-from-me`, {
          messageId: message.id,
        }, { withCredentials: true });
    
        if (response.data.success) {
          // Update the local state to reflect the deletion
          setMessages((prevMessages) => {
            const updatedMessages = { ...prevMessages };
            const roomId = message.chatRoomId;
            updatedMessages[roomId] = updatedMessages[roomId].filter(msg => msg.id !== message.id);
            return updatedMessages;
          });
        }
      } catch (error) {
        console.error('Error deleting message from me:', error);
      }
    };
  
    const handleReplyMessage = (message) => {
      console.log("Replying to message id:", message.id); // Log the message id for debugging
      setReplyToMessage(message);
      handleCloseContextMenu();
    };
  
    const handleCopyMessage = (message) => {
      navigator.clipboard.writeText(message.content);
      handleCloseContextMenu();
    };
  
    const defaultProfilePicture = 'https://placehold.co/40x40';
    
    // Memoized Message component
    const MemoizedMessage = useMemo(() => React.memo(({ msg, currentUser }) => {
      const originalMessage = msg.replyMessage;
      const originalSenderUsername =
        originalMessage?.senderId === currentUser?.id
          ? "You"
          : selectedUser?.username || "User";
      const isSender = msg.senderId === currentUser?.id;
      const senderReaction = msg.sendersReaction;
      const receiverReaction = msg.reciversReaction;
    
      const hasReaction = msg.reactions && msg.reactions.length > 0;
      const thisMessageRef = useRef(null);
      const [expanded, setExpanded] = useState(false);
      const onlyEmojisRegex = /^[\p{Extended_Pictographic}\p{Emoji_Presentation}\u200d\s]+$/u;
      const isOnlyEmojis = (text) => onlyEmojisRegex.test(text);
      const [postSummary, setPostSummary] = useState(null);
      const [isImageLoading, setIsImageLoading] = useState(true);

      useEffect(() => {
        if (thisMessageRef.current) {
          messageRefs.current[msg.id] = thisMessageRef.current;
        }
      }, [msg.id]);
  
console.log(contextMenu?.message?.id)

useEffect(() => {
  if (msg.isPost) {
    axios
      .get(`${api}/post/summary/${msg.content}`, { withCredentials: true })
      .then((response) => {
        setPostSummary(response.data);
        console.log("Post summary:", response.data);
      })
      .catch((error) => {
        console.error("Error fetching post summary:", error);
        // Set a fallback state when post cannot be fetched
        setPostSummary({
          id: msg.content,
          title: "This post is unavailable",
          author: { 
            username: "Unknown", 
            profilePicture: null 
          },
          mainMedia: null,
          isShort: false,
          mediaType: null,
          unavailable: true // Flag to indicate this is an unavailable post
        });
      });
  }
}, [msg.isPost, msg.content]);

// Inside your MemoizedMessage component, add this state and effect to fetch the reply post summary:
const [replyPostSummary, setReplyPostSummary] = useState(null);

useEffect(() => {
  if (originalMessage?.isPost) {
    axios
      .get(`${api}/post/summary/${originalMessage.content}`, {
        withCredentials: true,
      })
      .then((response) => {
        setReplyPostSummary(response.data);
        console.log("Reply post summary:", response.data);
      })
      .catch((error) => {
        console.error("Error fetching reply post summary:", error);
      });
  } else {
    setReplyPostSummary(null);
  }
}, [originalMessage]);
    
return (
<div ref={thisMessageRef}
  className={`flex flex-col rounded-xl relative group overflow-visible
    ${hasReaction ? 'mb-6' : 'mb-1'}
    ${msg.id === highlightedMessageId ? 'bg-[#3f3d3d] opacity-80' : ''}`} 
  onContextMenu={(event) => { event.preventDefault(); }}
>


    {!isSender && (
      <div className="flex items-center ">
        <div className="text-sm text-gray-400">{msg.senderUsername}</div>
      </div>
    )}
<div
  onTouchStart={(e) => handleTouchStart(e, msg)}
  onTouchEnd={handleTouchEnd}
  className={`message-item max-lg:max-w-[90%] relative select-none ${  // Added select-none here
    isSender
      ? `self-end text-white ${
          msg.isPost
            ? 'bg-transparent mb-3'
            : (msg.caption || (!msg.isMedia && !isOnlyEmojis(msg.content)))
              ? 'bg-gradient-to-r from-indigo-800 from-1% to-blue-900 to-99% rounded-tl-lg'
              : 'bg-transparent mb-3'
        } ${isOnlyEmojis(msg.content) && !msg.caption ? 'text-3xl' : ''}`
      : `self-start text-white ${
          msg.isPost
            ? 'bg-transparent mb-3'
            : (msg.caption || (!msg.isMedia && !isOnlyEmojis(msg.content)))
              ? 'bg-[#2c2c2c] rounded-tr-lg'
              : 'bg-transparent mb-3'
        } ${isOnlyEmojis(msg.content) && !msg.caption ? 'text-3xl' : ''}`
  } ${
    msg.isMedia || msg.isPost ? 'py-1 px-1' : 'py-2 px-4'
  } rounded-b-lg max-w-lg transition-all duration-300 min-w-[100px]`}
>
  {/* Icon containers for sender */}
  {!isSmallScreen && isSender && (
    <div
      className={`absolute right-[calc(100%+8px)] top-1/2 -translate-y-1/2 z-30 ${
        (contextMenu?.message?.id === msg.id || emojiContextMenu?.message?.id === msg.id)
          ? 'flex'
          : 'hidden group-hover:flex'
      } space-x-2 cursor-pointer`}
    >
      <div
        onClick={(event) => handleOptionsClick(event, msg)}
        className="three-dots-btn text-white hover:text-gray-600  text-[16px] font-bold"
      >
        <IoMdMore className="h-5 w-5 -mt-[1px]" />
      </div>
      <div
        onClick={(event) => handleEmojiPickerClick(event, msg)}
        className="text-gray-400 hover:text-gray-600"
      >
        <BsEmojiSmile size={16} />
      </div>
    </div>
  )}

  {/* Icon containers for receiver */}
  {!isSmallScreen && !isSender && (
    <div
      className={`absolute left-[calc(100%+8px)] top-1/2 -translate-y-1/2 z-30 ${
        (contextMenu?.message?.id === msg.id || emojiContextMenu?.message?.id === msg.id)
          ? 'flex'
          : 'hidden group-hover:flex'
      } space-x-2 cursor-pointer`}
    >
      <div
        onClick={(event) => handleEmojiPickerClick(event, msg)}
        className="text-gray-400 hover:text-gray-600 ml-4 pr-1 "
      >
        <BsEmojiSmile size={16} />
      </div>
      <div
        onClick={(event) => handleOptionsClick(event, msg)}
        className="three-dots-btn text-white hover:text-gray-600 text-[16px] font-bold"
      >
        <IoMdMore className="h-5 w-5 -mt-[2px]" />
      </div>
    </div>
  )}
{msg.replyToMessageId && (
  originalMessage ? (
    <div
      onClick={() => handleScrollToMessage(msg.replyToMessageId)}
      className={`${
        isSender ? "bg-[#1d4364]" : "bg-[#353535]"
      } text-white hover:cursor-pointer text-sm max-w-72 mt-1 ml-[-8px] pl-[9px] pb-2 rounded mb-1 border-l-4 border-cyan-600`}
    >
      <div className="font-semibold">{originalSenderUsername}</div>
      <div className="italic flex flex-col gap-1 message">
      {originalMessage.isPost ? (
  replyPostSummary ? (
    <div className="flex flex-col p-2 mx-1">
      <div className="flex items-center gap-2 my-2">
        <img
          src={
            replyPostSummary.author.profilePicture ?
            `${cloud}/cloudofscubiee/profilePic/${replyPostSummary.author.profilePicture}` : "/logos/DefaultPicture.png"}
          
          alt="Profile"
          className="w-6 h-6 bg-gray-300 rounded-full object-cover"
        />
        <span className="font-semibold text-sm">{replyPostSummary.author.username}</span>
      </div>
      {replyPostSummary.isShort ? (
        replyPostSummary.mediaType === "video" ? (
          <video 
            src={`${cloud}/cloudofscubiee/shortVideos/${replyPostSummary.mainMedia}`}
            className="h-full w-72 max-h-72 object-cover rounded"
            preload="metadata"
            muted
          />
        ) : (
          <img 
            src={`${cloud}/cloudofscubiee/shortImages/${replyPostSummary.mainMedia}`}
            alt={replyPostSummary.title}
            className="h-full w-72 max-h-72 object-cover rounded"
          />
        )
      ) : (
        <img
          src={`${cloud}/cloudofscubiee/postImages/${replyPostSummary.mainMedia}`}
          alt="Post Thumbnail"
          className="h-full w-72 max-h-72 object-cover rounded"
        />
      )}
      <div className="text-gray-300 mt-2 md:font-[400] font-[500] font-sans max-md:text-[14.5px] text-[15.5px] leading-tight line-clamp-2 overflow-hidden">
        {replyPostSummary.title}
      </div>
    </div>
  ) : (
    <ReplyPostSkeleton/>
  )
        ) : originalMessage.isMedia ? (
          <img
            src={`${cloud}/cloudofscubiee/chatImages/${originalMessage.content}`}
            alt="Media"
            className="h-full max-h-48 max-w-48 object-cover rounded"
          />
        ) : (
          originalMessage.content.length > 100
            ? originalMessage.content.slice(0, 100) + "..."
            : originalMessage.content
        )}
      </div>
    </div>
  ) : (
    <div className="text-sm text-gray-400 ml-[-8px] mt-1 border-l-4 border-gray-500 pl-2 italic">
      The message has been deleted
    </div>
  )
)}
     {msg.isPost && !postSummary && (
  <PostSkeleton />
)}
      {msg.isPost && postSummary && (
  <div 
    className={`my-4 bg-[#121212] border border-gray-800 rounded-lg overflow-hidden cursor-pointer min-w-[320px] max-w-[400px] w-full shadow-sm ${
      postSummary.unavailable ? 'flex items-center justify-center py-6' : ''
    }`} 
   
    onContextMenu={(e) => e.preventDefault()}
  >
    {postSummary.unavailable ? (
      <div className="flex flex-col items-center justify-center text-center px-4 py-8">
        <div className="mb-2">
          <FiAlertCircle className="h-8 w-8 text-gray-500" />
        </div>
        <p className="text-gray-400 font-medium">This post is no longer available</p>
        <p className="text-gray-500 text-sm mt-1">The content may have been deleted or made private</p>
      </div>
    ) : (
      <>
        {/* Header with profile info - ALWAYS at the top for both shorts and posts */}
        <div className="flex items-center gap-3 px-3 py-3 border-b border-gray-800">
          <img
            src={
              postSummary.author.profilePicture ?
              `${cloud}/cloudofscubiee/profilePic/${postSummary.author.profilePicture}` : "/logos/DefaultPicture.png"}
            alt="Profile"
            className="w-9 h-9 bg-gray-300 rounded-full object-cover"
          />
          <div className="flex flex-col">
            <span className="text-[15px] font-medium text-gray-200 flex items-center gap-1">
              {postSummary.author.username}
              {postSummary.author.Verified && (
                <RiVerifiedBadgeFill className="text-blue-500 h-3.5 w-3.5" />
              )}
            </span>
            <span className="text-xs text-gray-400">@{postSummary.author.username}</span>
          </div>
        </div>
        
        {postSummary.isShort ? (
          <>
            {/* For shorts: Media first, then content */}
            {/* Media section */}
            {postSummary.mainMedia && (
              <div className="w-full">
                {postSummary.mediaType === "video" ? (
                  <div className="relative w-full aspect-[9/16] max-h-[210px]">
                    <video 
                      src={`${cloud}/cloudofscubiee/shortVideos/${postSummary.mainMedia}`}
                      className="w-full h-full object-cover"
                      preload="metadata"
                      muted
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent"></div>
                    <div className="absolute bottom-2 left-3">
                      <div className="flex items-center">
                        <div className="bg-black/70 rounded-full p-1">
                          <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M8 5v14l11-7z" />
                          </svg>
                        </div>
                        <span className="text-white text-xs ml-2">Short</span>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="relative w-full aspect-[9/16] max-h-[210px]">
                    <img 
                      src={`${cloud}/cloudofscubiee/shortImages/${postSummary.mainMedia}`}
                      alt={postSummary.title || "Image"}
                      className="w-full h-full object-cover"
                    />
                  </div>
                )}
              </div>
            )}
            
            {/* Content section below media for shorts */}
            {postSummary.title && (
              <div className="px-3 py-2">
                <p className="text-gray-300 text-[15px] line-clamp-3">
                  {postSummary.title}
                </p>
              </div>
            )}
          </>
        ) : (
          <>
            {/* For regular posts: Content after header, then media */}
            {/* Content section - show 3 lines max */}
            {postSummary.title && (
              <div className="px-3 py-2">
                <p className="text-gray-300 text-[15px] line-clamp-3">
                  {postSummary.title}
                </p>
              </div>
            )}
            
            {/* Media section */}
            {postSummary.mainMedia && (
              <div className="w-full">
                {postSummary.mediaType === "video" ? (
                  <div className="relative w-full aspect-video">
                    <video 
                      src={`${cloud}/cloudofscubiee/postVideos/${postSummary.mainMedia}`}
                      className="w-full h-full object-cover"
                      preload="metadata"
                      muted
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent"></div>
                    <div className="absolute bottom-2 left-3">
                      <div className="bg-black/70 rounded-full p-1">
                        <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
                          <path d="M8 5v14l11-7z" />
                        </svg>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="w-full aspect-[16/9]">
                    <img 
                      src={`${cloud}/cloudofscubiee/postImages/${postSummary.mainMedia}`}
                      alt={postSummary.title || "Image"}
                      className="w-full h-full object-cover"
                    />
                  </div>
                )}
              </div>
            )}
          </>
        )}
        
        {/* Footer with engagement stats - always at bottom */}
        <div className="px-3 py-2 flex items-center gap-4 text-gray-400 text-xs">
          <div className="flex items-center gap-1">
            <FiHeart size={14} />
            <span>{postSummary.likes || 0}</span>
          </div>
          <div className="flex items-center gap-1">
            <FiMessageSquare size={14} />
            <span>{postSummary.comments || 0}</span>
          </div>
          <a className="ml-auto text-[11px] px-[6px] p-1 bg-slate-300 text-black font-sans font-medium rounded-full"  onClick={() => {
       if (!postSummary.unavailable) {
        if (postSummary.isShort === true) {
          // Force a hard reload for TWA/WebView compatibility
          window.location.href = `/shorts/${msg.content}`;
        } else {
          window.location.href = `/viewpost/${msg.content}`;
        }
      }
    }}>
            {postSummary.isShort ? "View Short" : "View Post"}
          </a>
        </div>
      </>
    )}
  </div>
)}
      <div className="flex items-end relative">
       
             <div className="flex flex-col">
            <div className="message leading-normal">

            {msg.isMedia && (
  <div 
    className="relative group"
    onContextMenu={(e) => e.preventDefault()}
  >
    {isImageLoading && <ImageLoadingSkeleton />}
    <img
      src={msg.isTemp ? msg.content : `${cloud}/cloudofscubiee/chatImages/${msg.content}`}
      alt="chat media"
      onLoad={() => setIsImageLoading(false)}
      onError={() => setIsImageLoading(false)}
      onClick={(e) => {
        e.stopPropagation();
        console.log("Setting fullscreen image:", `${cloud}/cloudofscubiee/chatImages/${msg.content}`);
        setFullscreenImage(`${cloud}/cloudofscubiee/chatImages/${msg.content}`);
      }}
      // Increase z-index and add pointer-events-auto to ensure clicks are detected
      aria-label="View fullscreen"
      // Add this to prevent parent touch handlers from interfering
      onTouchStart={(e) => e.stopPropagation()}
      onTouchEnd={(e) => e.stopPropagation()}
      className={`max-w-[300px] md:max-w-[300px] lg:max-w-[340px] rounded-lg shadow-lg cursor-pointer ${
        msg.isTemp ? 'opacity-70' : ''
      } ${isImageLoading ? 'hidden' : 'block'}`}
    />
    

    {/* Existing: Hover overlay for desktop - keep as is */}
    <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-40 transition-all duration-200 flex items-center justify-center opacity-0 group-hover:opacity-100 max-xl:hidden">
      <div className="flex gap-4">
        <button 
          onClick={(e) => {
            e.stopPropagation();
            setFullscreenImage(msg.isTemp ? msg.content : `${cloud}/cloudofscubiee/chatImages/${msg.content}`);
          }}
          className="bg-black bg-opacity-60 hover:bg-opacity-80 p-2 rounded-full text-white"
        >
          <RiFullscreenLine size={22} />
        </button>
        
        {/* Only show download button for non-temporary images */}
        {!msg.isTemp && (
          <button 
            onClick={async (e) => {
              e.stopPropagation();
              try {
                e.currentTarget.classList.add('opacity-50');
                const imageUrl = `${cloud}/cloudofscubiee/chatImages/${msg.content}`;
                const fileName = msg.content.split('/').pop() || 'chat-image.jpg';
                const response = await fetch(imageUrl);
                const blob = await response.blob();
                const blobUrl = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = blobUrl;
                link.download = fileName;
                document.body.appendChild(link);
                link.click();
                setTimeout(() => {
                  window.URL.revokeObjectURL(blobUrl);
                  document.body.removeChild(link);
                  e.currentTarget.classList.remove('opacity-50');
                }, 100);
              } catch (error) {
                console.error('Download failed:', error);
                e.currentTarget.classList.remove('opacity-50');
              }
            }}
            className="bg-black bg-opacity-60 hover:bg-opacity-80 p-2 rounded-full text-white"
          >
            <MdOutlineFileDownload size={22} />
          </button>
        )}
      </div>
    </div>
    
    {msg.caption && (
      <div className="mt-1 mb-[-10px] font-sans pl-2 text-gray-300 text-[15px]">
        {msg.caption}
      </div>
    )}
  </div>
)}
              {!msg.isMedia && !msg.isPost && (
                <span>
                  {expanded || msg.content.length <= 100 ? (
                    <>
                      {msg.content}
                      {msg.content.length > 100 && (
                        <strong onClick={() => setExpanded(false)} style={{ cursor: 'pointer' }}>
                          {'  '}
                          <span style={{ transform: 'rotate(+90deg)', display: 'inline-block' }}>
                            &lt;
                          </span>{' '}
                          Less
                        </strong>
                      )}
                    </>
                  ) : (
                    <>
                      {msg.content.slice(0, 100) + '... '}
                      <strong onClick={() => setExpanded(true)} style={{ cursor: 'pointer' }}>
                        More
                      </strong>
                    </>
                  )}
                  <span className="inline-block mt-3 h-2 w-[53px]"></span>
                </span>
              )}
              <span className={`${msg.isMedia ? ' right-[4px] bg-black/80 rounded-md p-1 bottom-[5px]' : ' '} ${msg.isPost ? 'right-2 ' : ' -bottom-[5px]'} absolute -right-2 max-md:text-[10px] text-[10px] text-gray-300 whitespace-nowrap`}>
                {new Date(msg.createdAt).toLocaleTimeString('en-US', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            </div>
          </div>
  
{msg.reactions && msg.reactions.length > 0 && (
  <div
    className={`absolute bottom-[-27px] h-fit z-20 flex space-x-1 ${
      msg.senderId === currentUser.id 
        ? msg.isMedia || msg.isPost 
          ? "right-[4px]" // Adjusted positioning for media/post
          : "right-[-10px]" // Original positioning for text
        : msg.isMedia || msg.isPost
          ? "left-[4px]" // Adjusted positioning for media/post
          : "left-[-10px]" // Original positioning for text
    }`}
  >
    {msg.reactions.map((reactionItem, index) => (
      <div
        key={index}
        onClick={() => {
          // Determine type based on whether currentUser is the one who reacted
          const type = reactionItem.senderId === currentUser.id ? "sender" : "receiver";
          setSelectedReactionDetails({
            reaction: reactionItem.reaction,
            id: msg.id,
            senderId: reactionItem.senderId,
            type,
          });
          // Set different display flags as necessary (1 for currentUser, 2 for other)
          setDisplayReactionRemove(type === "sender" ? 1 : 2);
          setSelectedReaction(reactionItem.reaction);
        }}
        className="cursor-pointer bg-[#444] rounded-full w-6 h-6 flex items-center justify-center text-[18px]"
      >
        {reactionItem.reaction}
      </div>
    ))}
  </div>
)}
            </div>
          </div>
        </div>
      );
    }),   [selectedUser])

  
    const getLastSeenMessageIndex = (messages) => {
      for (let i = messages.length - 1; i >= 0; i--) {
        if (messages[i].read) {
          
          return i;
          console.log(i)
        }
      }
      console.log(-1)
      return -1;
    };
  
    
  
  
    useEffect(() => {
    
      const chatPanel = chatWindowRef.current;
      if (chatPanel) {
        chatPanel.addEventListener('scroll', handleScroll);
        chatPanel.addEventListener('contextmenu', (event) => {
          event.preventDefault();
        });
      }
  
      return () => {
        if (chatPanel) {
          chatPanel.removeEventListener('scroll', handleScroll);
          chatPanel.removeEventListener('contextmenu', (event) => {
            event.preventDefault();
          });
        }
      };
    }, []);
  
    useEffect(() => {
      if (!socket) return;
    
      socket.on('reactionUpdated', ({ messageId, senderId, reaction,roomId: realRoomId, }) => {
        // Determine roomId (depending on your room id generation logic)

        console.log('Reaction updated:', messageId, senderId, reaction,realRoomId);
        const roomId = [currentUser.id, selectedUser.id].sort().join('_');
        const isActive = activelyViewing.current.has(roomId);
        setMessages((prevMessages) => {
          const updatedMessages = { ...prevMessages };
          const msgs = updatedMessages[roomId] || [];
          const messageIndex = msgs.findIndex((msg) => msg.id === messageId);
          if (messageIndex !== -1) {
            const updatedMsg = { ...msgs[messageIndex] };
    
            // Initialize reactions array if not present
            if (!updatedMsg.reactions) {
              updatedMsg.reactions = [];
            }
    
            // Check if a reaction from this sender already exists
            const existingIndex = updatedMsg.reactions.findIndex(
              (r) => r.senderId === senderId
            );
    
            if (existingIndex !== -1) {
              // Update the existing reaction
              updatedMsg.reactions[existingIndex] = { senderId, reaction, messageId };
            } else {
              // Add new reaction
              updatedMsg.reactions.push({ senderId, reaction, messageId });
            }
    
            // Replace the message in the array with the updated one
            msgs[messageIndex] = updatedMsg;
            updatedMessages[roomId] = [...msgs];
          }
          return updatedMessages;
        });
           // Create a skeleton for the reaction lastActivity.
    const reactionSkeleton = {
      type: 'reaction',
      data: {
        id: Date.now(), // Using Date.now() as a temporary unique id
        reaction,
        senderId,
        messageId,
        read: isActive,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      }
    };

    // Update the recent chat using the reaction lastActivity skeleton.
    dispatch(updateRecentChat({
      chatRoomId: realRoomId,
      updates: {
        lastActivity: reactionSkeleton
      }
    }));
  });

  return () => socket.off('reactionUpdated');
}, [socket, currentUser, selectedUser, dispatch]);
  
    const handleEmojiSelect = async (emoji, message) => {
      if (!currentUser || !selectedUser) return;
    
      const isSender = (message.senderId === currentUser.id);
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    
      if(!socket){}
      // Optimistic update
      setMessages((prevMessages) => {
        const updatedMessages = { ...prevMessages };
        const msgs = updatedMessages[roomId] || [];
        const index = msgs.findIndex((m) => m.id === message.id);
    
        if (index !== -1) {
          const updatedMsg = { ...msgs[index] };
          if (isSender) {
            updatedMsg.sendersReaction = emoji;
          } else {
            updatedMsg.reciversReaction = emoji;
          }
          msgs[index] = updatedMsg;
          updatedMessages[roomId] = [...msgs];
        }
        return updatedMessages;
      });
    
      // Emit socket event
      socket.emit('reactionUpdated', {
        senderId: currentUser.id,
        reaction: emoji,
        messageId: message.id,
      });
    
      // Persist reaction
      try {
        await fetch(`${api}/chat/update-reaction`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            senderId: currentUser.id,
            reaction: emoji,
            messageId: message.id,
          }),
        });
      } catch (error) {
        console.error('Error updating reaction:', error);
      }
    };
    useEffect(() => {
      if (!socket) return;
    
      socket.on('receive_message', (message) => {
        const isActive = activelyViewing.current.has(message.chatRoomId);
        
        // Always update messages regardless of tab focus
        setMessages((prevMessages) => {
          const currentRoomMessages = prevMessages[message.chatRoomId] || [];
          
          const messageExists = currentRoomMessages.some(msg => 
            msg.id === message.id || (msg.isTemp && msg.content === message.content)
          );
          
          if (!messageExists) {
            return {
              ...prevMessages,
              [message.chatRoomId]: [
                ...currentRoomMessages,
                { ...message, read: isActive }
              ]
            };
          }
          
          return prevMessages;
        });
      
    
          // Update recent chats via socket
    dispatch(updateRecentChat({
      chatRoomId: message.chatRoomId, 
      updates: {
        lastMessage: message.isMedia ? 'Image' : message.content,
        lastMessageSenderId: message.senderId,
        lastMessageRead: isActive && message.senderId !== currentUser?.id
      }
    }));
        if (isActive) {
          socket.emit('messageSeen', { 
            messageId: message.id, 
            userId: currentUser?.id 
          });
        }
      });
    
      return () => socket.off('receive_message');
    }, [socket, currentUser, dispatch]);
    
  
  useEffect(() => {
    if (!socket) return;
  
    // Listen for new messages
    socket.on('receive_message', (message) => {
      const isActive = activelyViewing.current.has(message.chatRoomId);
      
      // Update messages for the current chat
      setMessages((prevMessages) => {
        const currentRoomMessages = prevMessages[message.chatRoomId] || [];
        
        if (message.senderId === currentUser?.id) {
          return {
            ...prevMessages,
            [message.chatRoomId]: currentRoomMessages.map(msg => 
              msg.isTemp && msg.content === message.tempContent
                ? { ...message, read: isActive }
                : msg
            )
          };
        }
        
        const messageExists = currentRoomMessages.some(msg => 
          msg.id === message.id || (msg.isTemp && msg.content === message.content)
        );
        
        if (!messageExists) {
          return {
            ...prevMessages,
            [message.chatRoomId]: [
              ...currentRoomMessages,
              { ...message, read: isActive }
            ]
          };
        }
        
        return prevMessages;
      });
  
 
  
      // Fetch updated recent chats to ensure all chats are current
      const fetchUpdatedChats = async () => {
        try {
          const response = await axios.get(`${api}/chat/recent-chats`, { withCredentials: true });
          dispatch(setRecentChats(response.data));
        } catch (error) {
          console.error('Error fetching recent chats:', error);
        }
      };
      fetchUpdatedChats();
  
      if (isActive && message.senderId !== currentUser?.id) {
        socket.emit('messageSeen', { 
          messageId: message.id, 
          userId: currentUser?.id 
        });
      }
    });

   
    // Add additional socket listeners for chat updates
    socket.on('chatUpdated', () => {
      // Fetch updated recent chats when any chat is updated
      const fetchUpdatedChats = async () => {
        try {
          const response = await axios.get(`${api}/chat/recent-chats`, { withCredentials: true });
          dispatch(setRecentChats(response.data));
        } catch (error) {
          console.error('Error fetching recent chats:', error);
        }
      };
      fetchUpdatedChats();
    });
  
    socket.on('messagesRead', ({ roomId, userId }) => {
      // Update recent chats when messages are read
      dispatch(updateRecentChat({
        chatRoomId: roomId,
        updates: {
          lastMessageRead: true
        }
      }));
  
      // Update messages read status
      setMessages((prevMessages) => {
        const updatedMessages = { ...prevMessages };
        if (updatedMessages[roomId]) {
          updatedMessages[roomId] = updatedMessages[roomId].map((msg) =>
            msg.senderId !== userId ? { ...msg, read: true } : msg
          );
        }
        return updatedMessages;
      });
    });
  
 
  }, [socket, currentUser, dispatch]);
  
  useEffect(() => {
    window.addEventListener('scroll', () => {
      console.log('User scrolled!');
  });
  }, []);
  
  const handleRemoveReaction = async (message) => {
    if (!currentUser || !selectedUser) return;
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
  
    // Optimistic update: remove the reaction from the message
    setMessages((prevMessages) => {
      const updatedMessages = { ...prevMessages };
      const msgs = updatedMessages[roomId] || [];
      const index = msgs.findIndex((m) => m.id === message.id);
      if (index !== -1) {
        const updatedMsg = { ...msgs[index] };
        if (message.senderId === currentUser.id) {
          updatedMsg.sendersReaction = null;
        } else {
          updatedMsg.reciversReaction = null;
        }
        if (updatedMsg.reactions) {
          updatedMsg.reactions = updatedMsg.reactions.filter(
            (r) => r.senderId !== currentUser.id
          );
        }
        msgs[index] = updatedMsg;
        updatedMessages[roomId] = [...msgs];
      }
      return updatedMessages;
    });
  
    // Emit reaction update with emoji as null
    socket.emit('reactionUpdated', {
      senderId: currentUser.id,
      reaction: null,
      messageId: message.id,
    });
  
    // Call backend API to remove the reaction
    try {
      await fetch(`${api}/chat/remove-reaction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messageId: message.id }),
      });
    } catch (error) {
      console.error('Error removing reaction:', error);
    }
  };

  console.log(recentChats)

  useEffect(() => {
    if (chatOpened && chatWindowRef.current) {
      // Use a short delay to allow the messages to render
      setTimeout(() => {
        chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
        setChatOpened(false); // Reset flag so further updates don't auto-scroll
      }, 100);
    }
  }, [chatOpened]);
  

  
  // Optimized message rendering with virtualization
  const renderMessages = useCallback(() => {
    if (!currentUser || !selectedUser) return null;
  
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    const messagesList = messages[roomId] || [];
  
    const Row = ({ index, style }) => {
      const msg = messagesList[index];
      if (!msg) return null;
  
      const showDate = index === 0 || 
        new Date(msg.createdAt).toDateString() !== 
        new Date(messagesList[index - 1].createdAt).toDateString();
  
      return (
        <div style={style} className="px-4">
          {showDate && (
            <div className="text-center text-gray-300 my-2">
              {new Date(msg.createdAt).toLocaleDateString()}
            </div>
          )}
          <MemoizedMessage msg={msg} currentUser={currentUser} />
          {index === getLastSeenMessageIndex(messagesList) && 
           msg.senderId === currentUser.id && (
            <div className="text-xs text-gray-400 text-right">Seen</div>
          )}
        </div>
      );
    };
  
    return messagesList.length > 0 ? (
      <List
        height={chatWindowRef.current?.clientHeight || 500}
        itemCount={messagesList.length}
        itemSize={100}
        width="100%"
        className="scrollbar-thin scrollbar-thumb-gray-600 scrollbar-track-transparent"
      >
        {Row}
      </List>
    ) : (
      <div className="flex items-center justify-center h-full text-gray-400">
        No messages yet
      </div>
    );
  }, [messages, currentUser, selectedUser, MemoizedMessage]);
  
  const handleScroll = useCallback(debounce(() => {
    setContextMenu(null);
    setEmojiContextMenu(null);
  }, 100), []);
  
  useEffect(() => {
    if (!chatWindowRef.current) return;
  
    const resizeObserver = new ResizeObserver(debounce(() => {
      if (chatWindowRef.current) {
        chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
      }
    }, 100));
  
    resizeObserver.observe(chatWindowRef.current);
  
    return () => resizeObserver.disconnect();
  }, []);
  
  const chatContent = (
    <div 
    className="chat-window flex-1 overflow-y-auto py-1 px-1 md:px-4 bg-[#0a0a0a] relative max-md:scrollbar-hidden"
    ref={chatWindowRef}
      onScroll={(e) => {
        setContextMenu(null);
        setEmojiContextMenu(null);
        if (e.target.scrollTop <= 100) {
          fetchMoreMessages();
        }
      }}
    >
      {/* Loading indicator at the top */}
      {isLoadingOlder && (
  <div className="sticky top-0 left-0 right-0 z-10 py-3 bg-[#0a0a0a] flex justify-center">
    <PulseLoader color="#4F46E5" size={8} margin={4} />
  </div>
)}
      {selectedReactionDetails && (
        <div className="fixed inset-0 flex items-center justify-center  z-50">
          <div className="bg-[#1b1c22] mx-2 mr-3 border-gray-700 border-[1px] shadow-sm shadow-[#666565] rounded-lg w-[400px] overflow-hidden">
            <div className="border-b border-gray-700 px-4 py-2 flex items-center justify-between">
              <h3 className="text-lg font-medium text-white">Reaction</h3>
              <IoClose 
                className="h-6 w-6 text-gray-400 hover:text-white cursor-pointer"
                onClick={() => setSelectedReactionDetails(null)}
              />
            </div>
            <div className="p-4 flex items-center justify-between">
              <span className="text-gray-300">
                {selectedReactionDetails.senderId === currentUser?.id ? 'You' : selectedUser?.username}
              </span>
              <div className="flex items-center gap-4">
                <span className="text-2xl">{selectedReactionDetails.reaction}</span>
                {selectedReactionDetails.senderId === currentUser?.id && (
  <button 
    onClick={() => {
      handleRemoveReaction({ id: selectedReactionDetails.id, senderId: currentUser.id });
      setSelectedReactionDetails(null);
    }}
    className="text-red-500 hover:text-red-400 text-sm"
  >
    Remove
  </button>
)}
              </div>
            </div>
          </div>
        </div>
      )}
      {messages[[currentUser?.id, selectedUser?.id].sort().join('_')]?.map((msg, index, arr) => {
        const showDate = index === 0 || 
          new Date(msg.createdAt).toDateString() !== new Date(arr[index - 1].createdAt).toDateString();
        return (
          <div key={msg.id} className="mb-2">
            {showDate && (
              <div className="text-center text-gray-300 my-2">
                {new Date(msg.createdAt).toLocaleDateString('en-US', {
                  day: 'numeric',
                  month: 'long',
                  year: 'numeric'
                })}
              </div>
            )}
            <MemoizedMessage msg={msg} currentUser={currentUser} />
            {index === getLastSeenMessageIndex(arr) && msg.senderId === currentUser?.id && (
              <div className="text-xs text-gray-400 text-right">Seen</div>
            )}
          </div>
        );
      })}
    </div>
  );
  
   useEffect(() => {
      if (!socket || !currentUser) return;  // Add early return if socket or currentUser is null
  
      // Listen for room joined events
      socket.on('roomJoined', ({ roomId, users }) => {
        if (users.includes(currentUser?.id)) {  // Add optional chaining
          setIsRoomJoined(true);
        }
      });
  
      // Listen for user inactivity
      socket.on('userInactive', ({ userId, roomId }) => {
        if (userId === currentUser?.id) {  // Add optional chaining
          setIsRoomJoined(false);
        }
      });
  
      return () => {
        socket.off('roomJoined');
        socket.off('userInactive');
      };
    }, [socket, currentUser]);
  
    // Add activity tracking with improved null checking
    useEffect(() => {
      // Early return if any required data is missing
      if (!socket || !selectedUser || !currentUser || !currentUser.id || !selectedUser.id) return;
  
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      const activityInterval = setInterval(() => {
        socket.emit('chatActivity', {
          roomId,
          userId: currentUser.id,
          type: 'active'
        });
      }, 120000); // Every 2 minutes
  
      return () => clearInterval(activityInterval);
    }, [socket, selectedUser, currentUser]);
  
    console.log(selectedReactionDetails)
    
    useEffect(() => {
      if (selectedUser && currentUser) {
        const roomId = [currentUser.id, selectedUser.id].sort().join('_');
        const recentChat = recentChats.find(chat => chat.chatRoomId === roomId);
        if (
          recentChat &&
       
          !recentChat.lastActivity.data.read
        ) {
          dispatch(updateRecentChat({
            chatRoomId: roomId,
            updates: {
              lastMessageRead: true,
              // Mark the reaction as read locally.
              lastActivity: {
                ...recentChat.lastActivity,
                data: { ...recentChat.lastActivity.data, read: true }
              }
            }
          }));
        }
      }
    }, [selectedUser, currentUser, recentChats, dispatch]);

    useEffect(() => {
      const handleOutsideClick = (e) => {
        if (window.innerWidth < 1280 && activeChatOptions) {
          // Check if the click happened outside the recent chats container.
          if (
            recentChatsContainerRef.current &&
            !recentChatsContainerRef.current.contains(e.target)
          ) {
            setActiveChatOptions(null);
          }
        }
      };
    
      document.addEventListener('click', handleOutsideClick);
      return () => document.removeEventListener('click', handleOutsideClick);
    }, [activeChatOptions]);

  // Add a ref to track if we've already initialized from URL
  const initializedFromUrl = useRef(false);

  // Replace the useEffect that handles URL userId parameter with this updated version
  useEffect(() => {
    // Clear debug logs to help diagnose the issue
    if (!userId || !currentUser) {
      return; // Exit early if we don't have required data
    }
    
    // Only proceed if we have a userId in the URL
    if (userId && currentUser) {
      // If we already have this user selected, don't fetch again
      if (selectedUser && selectedUser.id && selectedUser.id.toString() === userId.toString()) {
        console.log("User already selected, skipping fetch:", selectedUser.username);
        // Make sure to update loading state when using existing data
        setIsUrlUserLoading(false);
        return;
      }
      
      console.log("Fetching user by ID from URL:", userId);
      
      // Set loading state while we fetch
      setIsPageLoading(true);
      setIsUrlUserLoading(true);
      
      // Fetch the user by ID
      axios.get(`${api}/user/getUserById/${userId}`, {
        withCredentials: true
      })
      .then(response => {
        console.log("User data response:", response.data);
        
        if (response.data && response.data.user) {
          const user = response.data.user;
          console.log("Setting selected user from URL param:", user.username);
          
          // Close previous chat if any
          if (selectedUser) {
            const previousRoomId = [currentUser.id, selectedUser.id].sort().join('_');
            socket.emit('leftRoom', { roomId: previousRoomId, userId: currentUser.id });
            socket.emit('closeChat', { roomId: previousRoomId, userId: currentUser.id });
          }
          
          // Directly update the selectedUser state
          setSelectedUser(user);
          setSelectedGroup(null);
          setSearchQuery('');
          setSearchResults([]);
          setChatOpened(true);
          setNoMoreMessages(false);
          setIsInitialFetch(true);
          
          // Set up room and fetch messages
          const roomId = [currentUser.id, user.id].sort().join('_');
          socket.emit('joinRoom', { userId: currentUser.id, otherUserId: user.id });
          
          axios.get(`${api}/chat/messages/${roomId}`, { withCredentials: true })
            .then(msgResponse => {
              setMessages(prevMessages => ({
                ...prevMessages,
                [roomId]: msgResponse.data,
              }));
              
              if (document.visibilityState === 'visible') {
                socket.emit('enterRoom', { roomId, userId: currentUser.id });
                socket.emit('openChat', { roomId, userId: currentUser.id });
                dispatch(updateRecentChat({
                  chatRoomId: roomId,
                  updates: {
                    lastMessageRead: true
                  }
                }));
              }
              
              setIsPageLoading(false);
              // Reset loading flag after data is loaded
              setIsUrlUserLoading(false);
              
              // Make sure we scroll to bottom of chat when messages are loaded
              setTimeout(() => {
                if (chatWindowRef.current) {
                  chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
                }
              }, 100);
            })
            .catch(error => {
              console.error("Error fetching messages:", error);
              setIsPageLoading(false);
              setIsUrlUserLoading(false);
            });
        } else {
          console.error("Invalid user data received from API:", response.data);
          setIsPageLoading(false);
          setIsUrlUserLoading(false);
        }
      })
      .catch(error => {
        console.error("Error fetching user from URL parameter:", error);
        setIsPageLoading(false);
        setIsUrlUserLoading(false);
      });
    }
  }, [userId, currentUser, api, dispatch]); // Include all necessary dependencies
  
   return (
    <div className="h-screen scrollbar-hide flex flex-col md:flex-row bg-[#0a0a0a] text-white ml-[10px]">
    {/* Show loading indicator if user data isn't available yet */}
    {(!currentUser) ? (
      <div className="w-full h-full flex items-center justify-center">
        <PulseLoader color="#4F46E5" size={12} margin={4} />
      </div>
    ) : (
      <>
        {/* Sidebar: User List */}
        <div className={`w-full lg:w-1/4 md:w-2/5 border-r scrollbar-hide border-[#2c3117] bg-[#0a0a0a] flex flex-col ${
          (isSmallScreen && selectedUser) || (isSmallScreen && isUrlUserLoading) ? "hidden" : "" // Hide on mobile when a user is selected OR when loading from URL
        } ${isSmallScreen && isReturningFromPost ? "hidden" : ""}`}>
          <div className="flex items-center p-3 relative mt-3">
            <FiSearch className="absolute left-6 text-gray-400" size={20} />
            <input
              type="text"
              placeholder="Search chats"
              value={searchQuery}
              onChange={handleSearch}
              className="w-full p-2 pl-10 bg-[#272726] rounded-lg text-white placeholder-gray-500"
            />
          </div>
      
          {/* Independent Scroll for User List */}
          <div className="flex-1 overflow-y-auto pt-2 ">
            {isSmallScreen && isReturningFromPost ? (
              <div className="flex justify-center items-center h-full">
                <PulseLoader color="#4F46E5" size={12} margin={4} />
              </div>
            ) : searchResults.length > 0 ? (
              searchResults.map((user) => (
                <div
                  key={user.id}
                  onClick={() => handleUserClick(user)}
                  className="p-3 flex items-center space-x-4 md:hover:bg-[#181818] cursor-pointer transition ease-in-out"
                >
                  <div className="relative">
                    <img
                     
                      src={
                        user.profilePicture ?
                        `${cloud}/cloudofscubiee/profilePic/${user.profilePicture}` : "/logos/DefaultPicture.png"}
                      alt={user.username}
                      className="w-10 h-10 bg-gray-300 rounded-full min-h-10 min-w-10"
                    />
                    {onlineUsers.has(String(user.id)) && (
                      <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-400 rounded-full border-2 border-[#050505]"></div>
                    )}
                  </div>
                  <div>
                    <div className="font-semibold text-white">{user.username}</div>
                    <div className="text-gray-400">{user.firstName} {user.lastName}</div>
                  </div>
                </div>
              ))
            ) : (
              <div 
  className="overflow-y-auto pt-2 max-md:h-[calc(100vh-70px)] max-md:scrollbar-hide"
              ref={recentChatsContainerRef}
              onScroll={handleRecentChatsScroll}
            >
        {recentChats.map((chat) => (
      <div
        key={chat.chatRoomId}
        className="relative group p-3 flex items-center space-x-4 md:hover:bg-[#181818] scrollbar-hide max-md:hover:bg-[#0a0a0a] cursor-pointer transition ease-in-out"
        onClick={(e) => {
          if (window.innerWidth < 1280 && activeChatOptions === chat.chatRoomId) {
            e.stopPropagation();
            return setActiveChatOptions(null);
          }
          setActiveChatOptions(null);
          handleUserClick(chat.otherUser);
        }}
        onMouseLeave={() => {
          if (window.innerWidth >= 1280) {
            setActiveChatOptions(null);
          }
        }}    onTouchStart={(e) => {
          e.preventDefault();
          // Clear any previous timer
          if (pressTimerRef.current) clearTimeout(pressTimerRef.current);
          pressTimerRef.current = setTimeout(() => {
            setActiveChatOptions(chat.chatRoomId);
          }, LONG_PRESS_DELAY);
        }}
        onTouchEnd={(e) => {
          // Clear the timer when touch ends so that state isn't overridden later
          if (pressTimerRef.current) {
            clearTimeout(pressTimerRef.current);
          }
          // Do not hide the menu on touch end so that it remains visible
        }}
        onContextMenu={(e) => e.preventDefault()} 
    
      >
        {/* Existing chat item content */}
        <div className="relative">
          <img
          
            src={
              chat.otherUser?.profilePicture ?
              `${cloud}/cloudofscubiee/profilePic/${chat.otherUser?.profilePicture}` : "/logos/DefaultPicture.png"}
            alt={chat.otherUser?.username}
            className="w-10 h-10 rounded-full bg-gray-300 object-cover min-h-10 min-w-10"
          />
          {onlineUsers.has(String(chat.otherUser?.id)) && (
            <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-400 rounded-full border-2 border-[#050505]"></div>
          )}
        </div>
        <div>
          <div className="font-semibold text-white">{chat.otherUser?.username}</div>
          <div className="text-gray-400 truncate max-w-[200px]">
            {chat.lastActivity.type === 'reaction'
              ? (chat.lastActivity.data.senderId === currentUser?.id
                  ? `you reacted ${chat.lastActivity.data.reaction} to a message`
                  : `reacted ${chat.lastActivity.data.reaction} to a message`)
              : formatLastMessage(
                  chat.lastActivity.data,
                  chat.isMedia,
                  currentUser?.id,
                  chat.lastActivity.data.senderId,
                  chat.lastMessageRead,
                  chat.lastActivity
                )
            }
          </div>
       
        </div>
        {chat.lastActivity.data.senderId !== currentUser?.id && (
      ((chat.lastActivity.type === 'message' && !chat.lastActivity.data.read) ||
       (chat.lastActivity.type === 'reaction' && !chat.lastActivity.data.read)) && (
        <div className="absolute right-10 top-1/2 transform -translate-y-1/2">
          <div className="w-[9px] h-[9px] bg-blue-500 rounded-full"></div>
        </div>
      )
    )}
        <div
          className="absolute right-4 top-1/2 transform -translate-y-1/2 opacity-0 group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            // Toggle delete button visibility on click for non-touch devices
            setActiveChatOptions(chat.chatRoomId);
            if (activeChatOptions === chat.chatRoomId) {
              setActiveChatOptions(null);
            }
          }}
        >
          <IoMdMore className="cursor-pointer text-lg text-white" />
        </div>
        {activeChatOptions === chat.chatRoomId && (
          <div
            className="absolute right-10 hover:bg-white/10 border-gray-700 border-[1px] md:text-[17px] top-1/2 transform -translate-y-1/2 bg-[#1b1c22] font-semibold font-sans p-[6px] px-3 rounded-full shadow"
            onClick={(e) => {
              e.stopPropagation();
              setChatToDelete(chat.chatRoomId);
              setIsConfirmingDelete(true);
            }}
          >
            <button className="text-red-500 text-sm ">
              Delete
            </button>
          </div>
          
        )}
      </div>
      
    ))}
      {isLoadingMoreChats && (
        <div className="flex justify-center py-4">
          <PulseLoader color="#4F46E5" size={8} margin={4} />
        </div>
      )}
    
    </div>
            )}
          </div>
          
          
        </div>
       
      
      
        <div className={`w-full md:w-3/4 flex flex-col h-full ${
      isSmallScreen && selectedUser ? "absolute top-0 left-0 w-full h-screen z-20 bg-transparent" : ""
    }`}>
     {isPageLoading ? (
      <div className="flex-1 flex items-center justify-center">
        <PulseLoader color="#4F46E5" size={12} margin={4} />
      </div>
    ) : selectedUser ? (
        <>
        <div className="flex items-center px-4 py-2 max-md:p-3 border-b-[1px] border-[#2c3117] bg-[#0a0a0a]">
  {isSmallScreen && (
    <IoArrowBack
      onClick={() => setSelectedUser(null)}
      className="mr-3 cursor-pointer"
      size={24}
    />
  )}
  <div 
    className="flex items-center flex-1  md:p-2 max-md:py-1 max-md:px-2 rounded-lg transition-colors"
    onClick={() => navigate(`/${selectedUser.username}`)}
  >
    <div className="relative cursor-pointer ">
      <img
        src={
          selectedUser.profilePicture ?
          `${cloud}/cloudofscubiee/profilePic/${selectedUser.profilePicture}` : "/logos/DefaultPicture.png"}
        alt={selectedUser.username}
        className="w-10 bg-gray-300 h-10 max-md:h-[32px] max-md:w-[32px] rounded-full object-cover"
      />
    </div>
    <div className="ml-4 cursor-pointer">
      <div className="font-semibold text-white">
        {selectedUser.username}
      </div>
    </div>
  </div>
</div>
    
          {imagePreview ? (
            <ScrollToBottom className="chat-window flex-1 overflow-y-auto py-1 px-4 bg-[#0a0a0a]  relative" ref={chatWindowRef}>
              <div className="absolute inset-0 bg-[#0a0a0a] z-50 flex flex-col">
                <div className="flex justify-between items-center  ">
                  <button 
                    onClick={() => setImagePreview(null)} 
                    className="text-gray-200 hover:text-white p-4"
                  >
                    <IoClose size={32} />
                  </button>
                </div>
    
                <div className="flex-1 flex items-center justify-center p-4 pt-0">
                  <img 
                    src={URL.createObjectURL(imagePreview)} 
                    alt="Preview" 
                    className="max-h-[60vh] max-w-full object-contain "
                  />
                </div>
    
                <div className="p-4 pt-1 flex items-center gap-4">
                  <input
                    type="text"
                    value={imageCaption}
    
                    onChange={(e) => setImageCaption(e.target.value.slice(0, 100))}
                    placeholder="Add a caption..."
                    className="flex-1 p-3 max-md:p-2 border-gray-700 border-2 bg-[#272726] rounded-full text-white"
                  />
                  <button 
                    onClick={handleSendImage}
                    className="text-gray-400 hover:text-gray-600 p-2"
                  >
                    <FiSend size={28} />
                  </button>
                </div>
              </div>
            </ScrollToBottom>
          ) : (
            <>
          {chatContent}
          {replyToMessage && (
      <div className="reply-preview flex items-center p-2 border-l-4 border-cyan-600 mb-2 bg-[#353535] rounded">
        <div className="flex-1">
          <div className="text-sm font-semibold">
            Replying to: {replyToMessage.senderUsername === currentUser?.username ? "You" : replyToMessage.senderUsername}
          </div>
          <div className="italic text-xs">
          {replyToMessage.isPost ? (
      replyPostSummary ? (
        <div className="flex flex-col">
          {replyPostSummary.isShort ? (
            replyPostSummary.mediaType === "video" ? (
              // Video short - use video element
              <video 
                src={`${cloud}/cloudofscubiee/shortVideos/${replyPostSummary.mainMedia}`}
                className="h-16 max-w-[120px] object-cover rounded"
                preload="metadata"
                muted
              />
            ) : (
              // Image short - use img element
              <img 
                src={`${cloud}/cloudofscubiee/shortImages/${replyPostSummary.mainMedia}`}
                alt={replyPostSummary.title}
                className="h-16 max-w-[120px] object-cover rounded"
              />
            )
          ) : (
            // Regular post
            <video 
              src={`${cloud}/cloudofscubiee/postVideos/${replyPostSummary.mainMedia}`}
              className="h-16 max-w-[120px] object-cover rounded"
              preload="metadata"
              muted
            />
          )}
          <div className="text-xs mt-1 line-clamp-1">{replyPostSummary.title}</div>
        </div>
      ) : (
        <ReplyPostSkeleton/>
      )
            ) : replyToMessage.isMedia ? (
              <img
                src={`${cloud}/cloudofscubiee/chatImages/${replyToMessage.content}`}
                alt="Media"
                className="h-16 max-w-[120px] object-cover rounded"
              />
            ) : (
              replyToMessage.content.length > 100
                ? replyToMessage.content.slice(0, 100) + "..."
                : replyToMessage.content
            )}
          </div>
        </div>
        <button
          onClick={() => setReplyToMessage(null)}
          className="ml-2 text-gray-300 hover:text-white text-3xl"
        >
          &times;
        </button>
      </div>
    )}
    
    <div className="md:px-4 md:py-2 max-md:px-3 mb-2 mx-2 max-md:rounded-full max-md:border max-md:border-gray-400 md:border-t border-[#2c3117] bg-[#0a0a0a] flex items-center relative">
    {missedCount > 0 && (
    <div
      onClick={handleScrollToBottom}
      className="absolute -top-12 left-10 bg-blue-800 rounded-full cursor-pointer z-40 flex justify-center items-center  text-white p-1"
      style={{ width: '34px', height: '34px' }}
    >
      <span className="text-[16px] font-semibold font-sans leading-none">{missedCount}</span>
    
    </div>
    )}
    <label htmlFor="file-upload" className=" text-gray-400 hover:text-gray-600 cursor-pointer">
    {isImageUploading ? (
      <div className="flex items-center justify-center">
        <PulseLoader color="#4F46E5" size={8} margin={2} />
      </div>
    ) : (
      <FaPlus className='w-[22px] h-[22px] max-md:w-[20px] max-md:h-[20px]' />
    )}
    <input 
      id="file-upload" 
      type="file" 
      accept="image/jpeg, image/jpg, image/png"
      className="hidden" 
      onChange={handleImageUpload}
      disabled={isImageUploading}
    />
    </label>
    <button onClick={() => setShowEmojiPicker(!showEmojiPicker)} className="text-gray-400 hover:text-gray-600 md:ml-3">
    <BsEmojiSmile className='w-[22px] h-[22px] max-md:hidden' />
    </button>
    {showEmojiPicker && (
    <div 
          ref={emojiPickerContainerRef}
    
      className="absolute bottom-16 left-4">
      <Picker onEmojiClick={handleEmojiClick} theme='dark'/>
    </div>
    )}
    
    <input
      type="text"
      value={newMessage}
      onChange={(e) => setNewMessage(e.target.value)}
      onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
      placeholder="Type a message"
      className="flex-1 mx-4 p-[10px] md:p-3 md:py-[10px] border-gray-600 md:border-2 font-sans max-md:mx-2 md:bg-[#272726] bg-[#0a0a0a] max-md:focus:ring-0  max-md:focus:outline-none max-md:focus:border-transparent rounded-full text-white"
    />
    <button onClick={handleSendMessage} className="text-gray-400 hover:text-gray-600">
    <FiSend size={24} />
    </button>
    </div>
            </>
          )}
        </>
      ) : (
        <div className="flex-1 max-md:hidden flex items-center justify-center text-gray-400">
          Select a user to start chatting
        </div>
      )}
    </div>
      </>
    )}
  {contextMenu && (
    <div
      ref={contextMenuRef}
      className={`fixed max-md:z-[1000] ${
          contextMenu.isSender
            ? ' ml-2'
            : '-ml-[200px]'
        }  bg-[#131418] max-md:mt-2 border-gray-700 border-[1px] shadow-sm shadow-[#666565] text-white rounded-lg  p-2 animate-fadeIn`}
      style={{ top: contextMenu.mouseY, left: contextMenu.mouseX }}
    >
      <button onClick={() => handleReplyMessage(contextMenu.message)} 
        className="block border-b-[1px] border-gray-700 px-4 py-2 hover:bg-[#333]  w-full text-left flex items-center gap-3">
        <FaReply size={18}/> Reply
      </button>
      <button onClick={() => handleCopyMessage(contextMenu.message)} 
        className="block border-b-[1px] border-gray-700 px-4 py-2 hover:bg-[#333] w-full text-left flex items-center gap-3">
        <MdContentCopy size={18}/> Copy
      </button>
      {contextMenu.isSender ? (
        <>
          <button onClick={() => handleDeleteFromMe(contextMenu.message)} 
            className="block border-b-[1px] border-gray-700 px-4 py-2 hover:bg-[#333]  w-full text-left flex items-center gap-3">
            <RiDeleteBin6Line size={18}/> Delete from me
          </button>
          <button onClick={() => handleDeleteMessage(contextMenu.message.id, contextMenu.message.chatRoomId, true)} 
            className="block px-4 py-2 hover:bg-[#333]  w-full text-left flex items-center gap-3">
            <AiOutlineUsergroupDelete size={21}/> Delete from everyone
          </button>
        </>
      ) : (
        <button onClick={() => handleDeleteFromMe(contextMenu.message)} 
          className="block  px-4 py-2 hover:bg-[#333]  w-full text-left flex items-center gap-3">
          <RiDeleteBin6Line size={18}/> Delete from me
        </button>
      )}
    </div>
  )}
      {emojiContextMenu && (
        <div
          ref={emojiPickerRef}
          className={`fixed max-md:z-[1000] ${
            emojiContextMenu.isSender
            ? 'ml-2 ' // Correct
            : 'ml-[32px]'
          }  max-md:-mt-[90px] top-50  bg-[#1b1c22] border-gray-700 border-[1px] shadow-[#666565] rounded-3xl px-2 pb-1 flex space-x-2 text-[27px] cursor-pointer animate-fadeIn`}
          style={{ top: emojiContextMenu.mouseY, left: emojiContextMenu.mouseX }}
        >
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('😂', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            😂
          </div>
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('✨', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            ✨
          </div>
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('❤️', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            ❤️
          </div>
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('🙏', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            🙏
          </div>
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('🥺', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            🥺
          </div>
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('👍', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            👍
          </div>
          <div
            className="text-white"
            onClick={() => {
              handleEmojiSelect('🔥', emojiContextMenu.message, emojiContextMenu.message.senderId === currentUser.id);
              setEmojiContextMenu(false);
            }}
          >
            🔥
          </div>
        </div>
      )}
      {isConfirmingDelete && (
  <div className="fixed inset-0  flex items-center justify-center z-50">
    <div className="bg-[#1b1c22] border-gray-700 border-[1px] shadow-[#666565] rounded-lg p-4 max-w-[480px] max-md:mx-3 mx-auto">
      <p className="text-md font-sans max-md:text-[14px]">
        Are you sure you want to delete this chatroom? This action cannot be undone.
      </p>
      <button
        onClick={() => {
          handleDeleteChatroom(chatToDelete); // call the delete route
          setIsConfirmingDelete(false);
          setChatToDelete(null);
        }}
        className="mt-4 bg-red-900 hover:bg-red-600 border-2 border-red-700 rounded-full text-white px-4 py-[6px]"
      >
        Confirm
      </button>
      <button
        onClick={() => {
          setIsConfirmingDelete(false);
          setChatToDelete(null);
        }}
        className="mt-4 ml-6 border-2 border-gray-300 hover:border-white rounded-full text-gray-300 hover:text-white px-4 py-[5px]"
      >
        Cancel
      </button>
    </div>
  </div>
)}
{/* Updated Fullscreen Image Viewer with mobile-friendly controls */}
{fullscreenImage && (
  <div 
    className="fixed inset-0 bg-black bg-opacity-95 z-50 flex flex-col"
    onContextMenu={(e) => e.preventDefault()}
  >
    {/* Header with controls for mobile */}
    <div className="flex justify-between items-center p-3 bg-black bg-opacity-70 xl:hidden">
      <button 
        onClick={async () => {
          try {
            const imageUrl = fullscreenImage;
            const fileName = imageUrl.split('/').pop() || 'chat-image.jpg';
            const response = await fetch(imageUrl);
            const blob = await response.blob();
            const blobUrl = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = blobUrl;
            link.download = fileName;
            document.body.appendChild(link);
            link.click();
            setTimeout(() => {
              window.URL.revokeObjectURL(blobUrl);
              document.body.removeChild(link);
            }, 100);
          } catch (error) {
            console.error('Download failed:', error);
          }
        }}
        className="text-white bg-transparent flex items-center gap-1"
      >
        <MdOutlineFileDownload size={28} />
      </button>
      
      <button 
        onClick={() => setFullscreenImage(null)}
        className="text-white bg-transparent"
      >
        <IoClose size={30} />
      </button>
    </div>
    
    {/* Image container - fills remaining space */}
    <div 
      className="flex-1 flex items-center justify-center" 
      onClick={() => setFullscreenImage(null)}
      onContextMenu={(e) => e.preventDefault()}
    >
      <img 
        src={fullscreenImage} 
        alt="Fullscreen view" 
        className="max-w-full max-h-[85vh] object-contain"
        onContextMenu={(e) => e.preventDefault()}
      />
    </div>

    {/* Desktop version controls - hidden on mobile */}
    <div className="hidden xl:block absolute top-4 right-4">
      <button 
        onClick={() => setFullscreenImage(null)} 
        className="text-white bg-black bg-opacity-50 hover:bg-opacity-70 rounded-full p-2"
      >
        <IoClose size={28} />
      </button>
    </div>
  </div>
)}
    </div>
  );
  };
  
  export default React.memo(Chat);