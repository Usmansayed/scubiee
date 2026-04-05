import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import axios from 'axios';
import Picker from 'emoji-picker-react';
import { FiSend, FiSearch } from 'react-icons/fi';
import { BsEmojiSmile } from 'react-icons/bs';
import io from 'socket.io-client';
import ScrollToBottom from 'react-scroll-to-bottom';
import { useSelector, useDispatch } from 'react-redux';
import { IoClose } from "react-icons/io5";
import { IoMdMore } from "react-icons/io";
import { ImageUp, LogIn } from 'lucide-react';

import imageCompression from 'browser-image-compression';

import './App.css'; // Import the CSS file
import { MdGroups } from "react-icons/md";
import { use } from 'react';
import { FaReply } from "react-icons/fa";
import { MdContentCopy } from "react-icons/md";
import { RiDeleteBin6Line } from "react-icons/ri";
import { AiOutlineUsergroupDelete } from "react-icons/ai";
import { FaPlus } from "react-icons/fa6";
import { setRecentChats, updateRecentChat } from './Slices/ChatSlice';
import { debounce } from 'lodash';
import VirtualScroller from 'virtual-scroller'
import { FixedSizeList as List } from 'react-window';

const Chat = () => {

  const dispatch = useDispatch();
  const api = import.meta.env.VITE_API_URL;
  const Domain = import.meta.env.Domain;
  const [tempBlobMessages, setTempBlobMessages] = useState(new Map());
  

  const [highlightedMessageId, setHighlightedMessageId] = useState(null);

  const createGroupBoxRef = useRef(null)
  const [showCreateGroupBox, setShowCreateGroupBox] = useState(false)

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


  const [socket, setSocket] = useState(null);
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

  const reactionRemoveRef = useRef(null);
  const [chatType, setChatType]= useState(0)
  const [ displayReactionRemove,setDisplayReactionRemove ] = useState(null)
  const [isRoomJoined, setIsRoomJoined] = useState(false);

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
            className="flex-1 p-2 bg-[#272726] rounded-lg text-white"
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
  
  // Modify handleImageUpload:
  const handleImageUpload = useCallback(async (e) => {
    const file = e.target.files[0];
    if (!file) return;
  
    // Validate file type
    const fileType = file.type;
    if (!['image/jpeg', 'image/png'].includes(fileType)) {
      alert('Only JPEG and PNG files are allowed.');
      return;
    }
  
    if (file.size > 10 * 1024 * 1024) {
      alert('File too large (max 10MB).');
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
    }
  }, []);
  
  const handleSendImage = async () => {
    if (!imagePreview || !currentUser?.id || !selectedUser?.id) return;
  
    try {
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      const tempMsgId = `temp_${Date.now()}`;
  
      setImagePreview(null);
      setImageCaption('');
  
      const options = {
        maxSizeMB: 1,
        maxWidthOrHeight: 1920,
        useWebWorker: true,
        fileType: imagePreview.type,
        initialQuality: 0.8
      };
      
      const compressedFile = await imageCompression(imagePreview, options);
      const formData = new FormData();
      formData.append('image', compressedFile);
      formData.append('senderId', currentUser.id);
      formData.append('receiverId', selectedUser.id);
      formData.append('caption', imageCaption);
  
      const response = await axios.post(`${api}/chat/upload-image`, formData, {
        withCredentials: true
      });
  
      if (response.data.success) {
        // Update recent chats immediately with correct read status
        dispatch(updateRecentChat({
          chatRoomId: roomId,
          updates: {
            lastMessage: 'Image',
            lastMessageSenderId: currentUser.id,
            lastMessageRead: activelyViewing.current.has(roomId)
          }
        }));
  
       
      }
    } catch (error) {
      console.error('Error sending image:', error);
    }
  };
  
  // Modify handleScrollToMessage
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
    const newSocket = io(`${api}`, { withCredentials: true });
    setSocket(newSocket);

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

    return () => newSocket.close();
  }, [currentUser]);

  const formatLastMessage = (message, isMedia, currentUserId, senderId , read) => {
    console.log('Message:', isMedia, message , currentUserId, senderId, read);
    if (isMedia || (message && message.includes('.jpg') || message.includes('.png') || message.includes('.jpeg'))) {
      return currentUserId === senderId ? 'You sent an image' : 'Sent an image';
    }
    return message?.length > 30 ? `${message.substring(0, 30)}...` : message;
  };

  useEffect(() => {
    const handleVisibilityChange = () => {
      const roomId = selectedUser ? [currentUser.id, selectedUser.id].sort().join('_') : null;
      
      if (document.visibilityState === 'visible') {
        if (selectedUser && currentUser && socket) {
          socket.emit('enterRoom', { roomId, userId: currentUser.id });
          socket.emit('openChat', { roomId, userId: currentUser.id });
          // Fetch latest messages when tab becomes visible
          fetchCurrentChatMessages();
        }
      } else if (document.visibilityState === 'hidden') {
        if (selectedUser && currentUser && socket) {
          socket.emit('leftRoom', { roomId, userId: currentUser.id });
          socket.emit('closeChat', { roomId, userId: currentUser.id });
        }
      }
    };
  
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
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
    const menuHeight = availableSpaceBelow < 180 ? (isSender ? 280 : 200) : 0;
  
   
  
    let adjustedX = isSender ? elementRect.left - menuWidth - 90 : elementRect.right + 12;
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
  if (selectedUser ) {
    const previousRoomId = selectedUser
      ? [currentUser.id, selectedUser.id].sort().join('_')
      : selectedGroup.chatRoomId;
    socket.emit('leftRoom', { roomId: previousRoomId, userId: currentUser.id });
    socket.emit('closeChat', { roomId: previousRoomId, userId: currentUser.id });
  }

  setSelectedUser(user);
  setSelectedGroup(null);
  setSearchQuery('');
  setSearchResults([]);

  console.log(selectedUser)

  if (!currentUser) {
    console.error('Current user not found');
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
      
      // Update local recent chats to mark messages as read immediately
      dispatch(updateRecentChat({
        chatRoomId: roomId,
        updates: {
          lastMessageRead: true
        }
      }));
    }
  } catch (error) {
    console.error('Error fetching messages:', error);
  }
};


  

//--this is the handle send message which manages the sending of messages in the frontend , it also classifies whether a message is for group
//--and if yes it sends the messag to the handle send message in group fuction 

  const handleSendMessage = () => {
    if (!newMessage.trim() || !currentUser) return;
  
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    const UserDetails = [currentUser.id, selectedUser.id];
  
    // Update activity and send message
    socket.emit('sendMessage', {
      roomId,
      UserDetails,
      content: newMessage,
      replyToMessageId: replyToMessage?.id || null,
      createdAt: new Date()
    }, (ackMessage) => {
      // Handle message acknowledgment
      if (ackMessage) {
        setMessages((prevMessages) => ({
          ...prevMessages,
          [roomId]: [
            ...(prevMessages[roomId] || []),
            { ...ackMessage, fromMe: true, read: false },
          ],
        }));
      }
    });
  
    // Update UI immediately
    dispatch(updateRecentChat({
      chatRoomId: roomId,
      updates: { 
        lastMessage: newMessage,
        lastMessageSenderId: currentUser.id,
        lastMessageRead: false
      }
    }));
  
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
        const response = await axios.post(`${api}/chat/search`, { username: query });
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
    socket.emit('deleteMessage', { messageId, roomId, deleteForEveryone });
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
    setReplyToMessage(message);
    handleCloseContextMenu();
    console.log('Replying to message:', message);
  };

  const handleCopyMessage = (message) => {
    navigator.clipboard.writeText(message.content);
    handleCloseContextMenu();
  };

  const defaultProfilePicture = 'https://placehold.co/40x40';
  
  // Memoized Message component
  const MemoizedMessage = useMemo(() => React.memo(({ msg, currentUser }) => {
    const originalMessage = messages[msg.chatRoomId]?.find(m => m.id === msg.replyToMessageId);
    const originalSenderUsername = originalMessage?.senderId === currentUser?.id 
      ? 'You' 
      : selectedUser?.username || 'User';  // Add fallback value
  
    const isSender = msg.senderId === currentUser?.id;
    const senderReaction = msg.sendersReaction;
    const receiverReaction = msg.reciversReaction;
  
    const hasReaction = senderReaction || receiverReaction;
    const thisMessageRef = useRef(null);

    useEffect(() => {
      if (thisMessageRef.current) {
        messageRefs.current[msg.id] = thisMessageRef.current;
      }
    }, [msg.id]);

    
  
    return (
      <div ref={thisMessageRef}
      className={`flex flex-col rounded-xl relative group 
        ${hasReaction ? 'mb-6' : 'mb-1'}
        ${msg.id === highlightedMessageId ? 'bg-[#3f3d3d] opacity-80' : ''}`} 
      onContextMenu={(event) => { event.stopPropagation(); }}>
        {!isSender  && (
          <div className="flex items-center ">
           
            <div className="text-sm text-gray-400">{msg.senderUsername}</div>
          </div>
        )}
            <div
              className={`${
                isSender
                  ? `self-end text-white ${
                     ( msg.caption || !msg.isMedia)
                        ? 'bg-gradient-to-r from-indigo-800 from-1% to-blue-900 to-99%'
                        : 'bg-transparent'
                    }`
                  :`self-start text-white ${
                     ( msg.caption || !msg.isMedia)
                        ? 'bg-[#2c2c2c]'
                        : 'bg-transparent'
                    }`
              } ${msg.isMedia ? 'py-1 px-1' : 'py-2 px-4'} rounded-lg max-w-lg transition-all duration-300 min-w-[100px] relative`}
            >      
              {msg.replyToMessageId && originalMessage && (
            <div           onClick={() => handleScrollToMessage(msg.replyToMessageId)}
            className={`${isSender ? ' bg-[#20496e] text-white' : ' bg-[#353535] text-white'} hover:cursor-pointer text-sm mt-1 ml-[-8px] pl-[9px] pb-2 rounded mb-1 border-l-4 border-cyan-600`}>
              <div className="font-semibold">{originalSenderUsername}</div>
              <div className="italic">{originalMessage.content}</div>
            </div>
          )}
          <div className="flex items-end relative">
          {isSender ? (
                <div
                  className={`absolute top-2 left-[-80px] ${
                    (contextMenu?.message?.id === msg.id || emojiContextMenu?.message?.id === msg.id)
                      ? 'flex bg-slate-100'
                      : 'hidden group-hover:flex'
                  } space-x-2 cursor-pointer`}
                >
                  <div
                    onClick={(event) => handleOptionsClick(event, msg)}
                    className="three-dots-btn text-white hover:text-gray-600 text-[16px] font-bold mt-[-7.2px]"
                  >
                    <IoMdMore className='h-6 w-6'/>
                  </div>
                  <div
                    onClick={(event) => handleEmojiPickerClick(event, msg)}
                    className="text-gray-400 hover:text-gray-600 mt-[-5px] mr-[-5px]"
                  >
                    <BsEmojiSmile size={18} />
                  </div>
                </div>
              ) : (
                <div
                  className={`absolute top-2 right-[-80px] ${
                    (contextMenu?.message?.id === msg.id || emojiContextMenu?.message?.id === msg.id)
                      ? 'flex'
                      : 'hidden group-hover:flex'
                  } space-x-2 cursor-pointer`}
                >
                  <div
                    onClick={(event) => handleEmojiPickerClick(event, msg)}
                    className="text-gray-400 hover:text-gray-600 mt-[-5px] ml-4 pr-1"
                  >
                    <BsEmojiSmile size={18} />
                  </div>
                  <div
                    onClick={(event) => handleOptionsClick(event, msg)}
                    className="three-dots-btn text-white hover:text-gray-600 text-[16px] font-bold mt-[-8.2px]"
                  >
                    <IoMdMore className='h-6 w-6'/>
                  </div>
                </div>
              )}
   <div className="flex flex-col">
   <div className="break-word whitespace-pre-wrap">
   {msg.isMedia && (
  <>
    <img
      src={msg.isTemp ? msg.content : `${cloud}/cloudofscubiee/chatImages/${msg.content}`}
      alt="chat media"
      className={`max-w-xs md:max-w-sm rounded-lg shadow-lg cursor-pointer ${
        msg.isTemp ? 'opacity-70' : ''
      }`}
    />
    {msg.caption && (
      <div className="mt-1 mb-[-10px] font-sans pl-2 text-gray-300 text-[15px]">
        {msg.caption}
      </div>
    )}
  </>
)} {!msg.isMedia && msg.content}
    {/* Timestamp */}
    <span className={`${msg.isMedia ? 'mr-[5px] pb-[4px]' : 'mr-[-10px]'} float-right text-[11px] text-gray-300 ml-5  whitespace-nowrap mt-3 mb-[-4px]`}>
      {new Date(msg.createdAt).toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
      })}
    </span>
  </div>
</div>

            {hasReaction && (
              <div className={`${isSender ? "right-[-10px]" : "left-[-10px]"} absolute bottom-[-27px] flex space-x-1`}>
                {/* Sender's Reaction */}
                {senderReaction && (
                  <div
                  onClick={() => {
                    if (msg.senderId === currentUser.id) {
                      setSelectedReactionDetails({
                        reaction: senderReaction,
                        id: msg.id,
                        senderId: currentUser.id,
                        type: 'sender',
                      });
                      setDisplayReactionRemove(1); // For sender
                    } else {
                      setSelectedReactionDetails({
                        reaction: senderReaction,
                        id: msg.id,
                        senderId: selectedUser.id,
                        type: 'sender',
                      });
                      setDisplayReactionRemove(2); // For receiver
                    }
                    setSelectedReaction(senderReaction);
                  }}
                  className="cursor-pointer bg-[#444] rounded-full w-6 h-6 flex items-center justify-center text-[18px]"
                >
                    {senderReaction}
                  </div>
                )}
  
                {/* Receiver's Reaction */}
                {receiverReaction && (
  <div
  onClick={() => {
    if (msg.senderId === currentUser.id) {
      setSelectedReactionDetails({
        reaction: receiverReaction,
        id: msg.id,
        senderId: selectedUser.id,
        type: 'receiver',
      });
      setDisplayReactionRemove(2);
    } else {
      setSelectedReactionDetails({
        reaction: receiverReaction,
        id: msg.id,
        senderId: currentUser.id,
        type: 'receiver',
      });
      setDisplayReactionRemove(1);
    }
    setSelectedReaction(receiverReaction);
  }}
  className="cursor-pointer bg-[#444] rounded-full w-6 h-6 flex items-center justify-center text-[18px]"
>
    {receiverReaction}
  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }), [messages, selectedUser, currentUser]); // Add dependencies

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
  
    socket.on('reactionUpdated', ({ messageId, senderId, reaction }) => {
      const roomId = [currentUser.id, selectedUser.id].sort().join('_');
      setMessages((prevMessages) => {
        const updatedMessages = { ...prevMessages };
        const msgs = updatedMessages[roomId] || [];
        const messageIndex = msgs.findIndex(msg => msg.id === messageId);
        if (messageIndex !== -1) {
          if (senderId === currentUser.id) {
            msgs[messageIndex].sendersReaction = reaction;
          } else {
            msgs[messageIndex].reciversReaction = reaction;
          }
          updatedMessages[roomId] = [...msgs];
        }
        return updatedMessages;
      });
    });
  
    return () => {
      socket.off('reactionUpdated');
    };
  }, [socket, currentUser, selectedUser, setMessages]);

  const handleEmojiSelect = async (emoji, message, isSender) => {

    console.log("Emoji:", emoji);
    console.log("Message ID:", message.id);
    console.log("Is Sender:", isSender);
    if (!currentUser || !selectedUser) return;
  
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    const UserDetails = [currentUser.id, selectedUser.id];
  
    // Emit the reactionUpdated event
    socket.emit('reactionUpdated', {
      senderId: currentUser.id,
      reaction: emoji ,
      messageId: message.id
    });
  

  
    // Make a POST request to update the reaction in the database
    await fetch('/chat/update-reaction', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        senderId: currentUser.id,
        reaction: emoji,
        messageId: message.id
      }),
    });
  };

  const fetchCurrentChatMessages = async () => {
    if (!selectedUser || !currentUser) return;
    
    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    try {
      const response = await axios.get(`${api}/chat/messages/${roomId}`, { 
        withCredentials: true 
      });
      setMessages(prevMessages => ({
        ...prevMessages,
        [roomId]: response.data
      }));
    } catch (error) {
      console.error('Error fetching messages:', error);
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
    
  
      // Update recent chats
      dispatch(updateRecentChat({
        chatRoomId: message.chatRoomId,
        updates: {
          lastMessage: message.isMedia ? 'Image' : message.content,
          lastMessageSenderId: message.senderId, 
          lastMessageRead: false
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

    // Update recent chats for all users
    dispatch(updateRecentChat({
      chatRoomId: message.chatRoomId,
      updates: {
        lastMessage: message.isMedia ? 'Image' : message.content,
        lastMessageSenderId: message.senderId,
        lastMessageRead: isActive && message.senderId !== currentUser?.id
      }
    }));

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

  return () => {
    socket.off('receive_message');
    socket.off('chatUpdated');
    socket.off('messagesRead');
  };
}, [socket, currentUser, dispatch]);

useEffect(() => {
  window.addEventListener('scroll', () => {
    console.log('User scrolled!');
});
}, []);

console.log(recentChats)
console.log(contextMenu?.message?.id);

useEffect(() => {
  if (chatWindowRef.current) {
    // scroll to bottom on messages change
    chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
  }
}, [messages]);

console.log(selectedReactionDetails)

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

// Optimized scroll handler
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
    className="chat-window flex-1 overflow-y-auto py-1 px-4 bg-[#0a0a0a] relative"
    ref={chatWindowRef}
    onScroll={(e) => {
      setContextMenu(null);
      setEmojiContextMenu(null);
    }}
  >
    {selectedReactionDetails && (
      <div className="absolute inset-0 flex items-center justify-center z-50">
        <div className="bg-[#1b1c22] border-gray-700 border-[1px] shadow-sm shadow-[#666565] rounded-lg w-[400px] overflow-hidden">
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
                    handleEmojiSelect(null, { id: selectedReactionDetails.id }, true);
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
    if (!socket) return;

    // Listen for room joined events
    socket.on('roomJoined', ({ roomId, users }) => {
      if (users.includes(currentUser?.id)) {
        setIsRoomJoined(true);
      }
    });

    // Listen for user inactivity
    socket.on('userInactive', ({ userId, roomId }) => {
      if (userId === currentUser?.id) {
        setIsRoomJoined(false);
      }
    });

    return () => {
      socket.off('roomJoined');
      socket.off('userInactive');
    };
  }, [socket, currentUser]);

  // Add activity tracking
  useEffect(() => {
    if (!socket || !selectedUser || !currentUser) return;

    const roomId = [currentUser.id, selectedUser.id].sort().join('_');
    const activityInterval = setInterval(() => {
      socket.emit('chatActivity', {
        roomId,
        userId: currentUser.id,
        type: 'active'
      });
    }, 120000); // Every minute

    return () => clearInterval(activityInterval);
  }, [socket, selectedUser, currentUser]);

  console.log(selectedReactionDetails)
  

 return (
  <div className="h-screen flex flex-col md:flex-row bg-[#0a0a0a] text-white ml-[10px]">
  {/* Sidebar: User List */}
  <div className="w-full md:w-1/4 border-r border-[#2c3117] bg-[#0a0a0a] flex flex-col ">
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
      {searchResults.length > 0 ? (
        searchResults.map((user) => (
          <div
            key={user.id}
            onClick={() => handleUserClick(user)}
            className="p-3 flex items-center space-x-4 hover:bg-[#181818] cursor-pointer transition ease-in-out"
          >
            <div className="relative">
              <img
                src={
                  user.profilePicture?.startsWith('https')
                    ? user.profilePicture
                    : `${cloud}/cloudofscubiee/profilePic/${user.profilePicture}`
                }
                alt={user.username}
                className="w-10 h-10 rounded-full"
              />
              {onlineUsers.has(user.id) && (
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
        recentChats.map((chat) => (
          <div
            key={chat.chatRoomId}
            onClick={() => handleUserClick(chat.otherUser)}
            className="p-3 flex items-center space-x-4 hover:bg-[#181818] cursor-pointer transition ease-in-out"
          >
            <div className="relative">
              <img
                src={
                  chat.otherUser?.profilePicture?.startsWith('https')
                    ? chat.otherUser.profilePicture
                    : `${cloud}/cloudofscubiee/profilePic/${chat.otherUser?.profilePicture}`
                }
                alt={chat.otherUser?.username}
                className="w-10 h-10 rounded-full object-cover"
              />
              {onlineUsers.has(chat.otherUser?.id) && (
                <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-400 rounded-full border-2 border-[#050505]"></div>
              )}
            </div>
            <div>
              <div className="font-semibold text-white">{chat.otherUser?.username}</div>
              <div className="text-gray-400 truncate max-w-[200px]">
              <div className="flex items-center gap-2">
  <div className="text-gray-400 text-sm truncate max-w-[200px]">
    {formatLastMessage(
      chat.lastMessage, 
      chat.isMedia,
      currentUser?.id,
      chat.lastMessageSenderId,
      chat.lastMessageRead // Pass the read status

    )}
  </div>
  {chat.lastMessageSenderId !== currentUser?.id && !chat.lastMessageRead && (
    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
  )}
</div>
  </div>            </div>
          </div>
        ))
      )}
    </div>
  </div>
 


  <div className="w-full md:w-3/4 flex flex-col h-full">
  {selectedUser ? (
    <>
      {/* Header */}
      <div className="flex items-center p-4 border-b-[1px] border-[#2c3117] bg-[#0a0a0a]">
        <div className="relative">
          <img
            src={selectedUser.profilePicture?.startsWith('https') 
              ? selectedUser.profilePicture 
              : `${cloud}/cloudofscubiee/profilePic/${selectedUser.profilePicture}`}
            alt={selectedUser.username}
            className="w-10 h-10 rounded-full object-cover"
          />
        </div>
        <div className="ml-4">
          <div className="font-semibold text-white">
            {selectedUser.username}
          </div>
        </div>
      </div>

      {imagePreview ? (
        // Image Upload Widget
        <ScrollToBottom className="chat-window flex-1 overflow-y-auto py-1 px-4 bg-[#0a0a0a] relative" ref={chatWindowRef}>
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
                className="flex-1 p-3 bg-[#272726] rounded-lg text-white"
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
            <div className="p-2 bg-[#222329] text-white border-cyan-400 flex items-center justify-between border-l-4 rounded-md m-2">
              <div>
                <div className="text-sm">Replying to:</div>
                <div className="text-sm font-semibold">{replyToMessage.content}</div>
              </div>
              <button onClick={() => setReplyToMessage(null)} className="text-red-500 pr-5">
                <IoClose size={28} />
              </button>
            </div>
          )}

          <div className="p-4 border-t border-[#2c3117] bg-[#0a0a0a] flex items-center">
          <label htmlFor="file-upload" className=" text-gray-400 hover:text-gray-600 cursor-pointer">
              <FaPlus size={23} />
              <input 
                id="file-upload" 
                type="file" 
  accept="image/png, image/jpeg"
                className="hidden" 
                onChange={handleImageUpload}
              />
            </label>
            <button onClick={() => setShowEmojiPicker(!showEmojiPicker)} className="text-gray-400 hover:text-gray-600 ml-3">
              <BsEmojiSmile size={22} />
            </button>
            {showEmojiPicker && (
              <div className="absolute bottom-16 left-4">
                <Picker onEmojiClick={handleEmojiClick} />
              </div>
            )}
          
            <input
              type="text"
              value={newMessage}
              onChange={(e) => setNewMessage(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
              placeholder="Type a message"
              className="flex-1 mx-4 p-2 bg-[#272726] rounded-lg text-white"
            />
            <button onClick={handleSendMessage} className="text-gray-400 hover:text-gray-600">
              <FiSend size={24} />
            </button>
          </div>
        </>
      )}
    </>
  ) : (
    <div className="flex-1 flex items-center justify-center text-gray-400">
      Select a user to start chatting
    </div>
  )}
</div>
{contextMenu && (
  <div
    ref={contextMenuRef}
    className="absolute bg-[#1b1c22] border-gray-700 border-[1px] shadow-sm shadow-[#666565] text-white rounded-lg  p-2 animate-fadeIn"
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
        className="absolute bg-[#1b1c22] border-gray-700 border-[1px] shadow-[#666565] rounded-3xl px-2 pb-1 flex space-x-2 text-[27px] cursor-pointer animate-fadeIn"
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
  </div>
);
};

export default React.memo(Chat);