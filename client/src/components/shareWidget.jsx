//// filepath: /c:/Users/usman/Videos/Real Projects/client/src/components/shareWidget.jsx
import React, { useEffect, useState, useRef, useCallback } from 'react';
import CreateStory from './CreateStory';
import { Search, Link2, X, Check } from "lucide-react";
import { FaWhatsapp, FaInstagram, FaFacebook, FaFacebookF } from "react-icons/fa";
import { IoMdAdd } from "react-icons/io";
import { MdOutlineMail } from "react-icons/md";
import { useDispatch ,useSelector } from 'react-redux';
import { size } from 'lodash';
import { FaSquareFacebook } from "react-icons/fa6";
import { setShowWidget, setStoryPostId } from '../Slices/WidgetSlice';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { debounce } from 'lodash';
const cloud = import.meta.env.VITE_CLOUD_URL;

import socket from '../socket';
const api = import.meta.env.VITE_API_URL;
const Domain = import.meta.env.VITE_DOMAIN;

export function ShareDialog({ postId, onClose }) {
  const currentUser = useSelector((state) => state.user.userData);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const recentChats = useSelector((state) => state.chat.recentChats);
  const dialogRef = useRef(null);
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);

  // New state for displaying CreateStory with a postId
  const [showCreateStory, setShowCreateStory] = useState(false);
  const [createStoryPostId, setCreateStoryPostId] = useState(null);
  const dispatch = useDispatch();
  const openCreateStoryWithPost = (id) => {
    setCreateStoryPostId(id);
    setShowCreateStory(true);
  };

  const handleUserSelect = (userId) => {
    setSelectedUsers((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    );
  };

  // Debounced search function - updated to use the search/users endpoint
  const debouncedSearch = useCallback(
    debounce(async (query) => {
      if (!query.trim()) {
        setSearchResults([]);
        setIsSearching(false);
        return;
      }
      
      setIsSearching(true);
      try {
        const response = await axios.post(`${api}/search/users`, { username: query }, { withCredentials: true });
        setSearchResults(response.data);
      } catch (error) {
        console.error('Error searching users:', error);
        setSearchResults([]);
      } finally {
        setIsSearching(false);
      }
    }, 300),
    []
  );

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  const handleSearch = (e) => {
    setSearchQuery(e.target.value);
    debouncedSearch(e.target.value);
  };

  // Add state for sent notification
  const [showSentNotification, setShowSentNotification] = useState(false);

  const sendPost = () => {
    if (!socket || !selectedUsers.length) return;
    
    selectedUsers.forEach((roomId) => {
      const message = {
        chatRoomId: roomId,
        content: `Shared a post: ${postId}`,
        isSharePost: true,
        senderId: currentUser.id,
      };
      
      const [user1, user2] = roomId.split('_');
      const receiverId = user1 === currentUser.id ? user2 : user1;
      socket.emit('sendMessage', { 
        roomId, 
        UserDetails: [currentUser.id, receiverId],
        content: postId,
        isSharePost: true,
        isPost: true,
      });
    });
    
    // Close widget immediately
    onClose();
    
    // Show sent notification AFTER widget is closed
    document.body.insertAdjacentHTML(
      'beforeend',
      `<div id="sent-notification" class="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
        Sent
      </div>`
    );
    
    // Remove the notification after delay
    setTimeout(() => {
      const notification = document.getElementById('sent-notification');
      if (notification) {
        notification.remove();
      }
    }, 1500);
  };

  const handleSearchUserSelect = (user) => {
    // Create room ID by sorting the IDs
    const roomId = [currentUser.id, user.id].sort().join('_');
    handleUserSelect(roomId);
  };

  const handleShare = async (app) => {
    const url = `${Domain}/viewpost/${postId}`;

    if (navigator.share) {
      try {
        await navigator.share({
          title: 'Check this out',
          text: 'Take a look at this post',
          url,
        });
        return;
      } catch (error) {
        console.error('Error with native share', error);
      }
      onClose();
    }

    switch (app) {
      case 'whatsapp': {
        const encodedURL = encodeURIComponent(url);
        if (/Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)) {
          window.location.href = `whatsapp://send?text=${encodedURL}`;
        } else {
          window.open(`https://web.whatsapp.com/send?text=${encodedURL}`, '_blank');
        }
        break;
      }
      case 'facebook': {
        const encodedURL = encodeURIComponent(url);
        window.open(`https://www.facebook.com/sharer/sharer.php?u=${encodedURL}`, '_blank');
        break;
      }
      case 'instagram': {
        const encodedURL = encodeURIComponent(url);
        window.open(`https://www.instagram.com/?url=${encodedURL}`, '_blank');
        break;
      }
      case 'email': {
        window.location.href = `mailto:?subject=Check this out&body=${encodeURIComponent(url)}`;
        break;
      }
      default:
        window.open(url, '_blank');
        break;
    }
  };

  // Add state for copy notification
  const [showCopyNotification, setShowCopyNotification] = useState(false);

  // Function to show notification temporarily
  const showCopyNotice = () => {
    setShowCopyNotification(true);
    setTimeout(() => setShowCopyNotification(false), 2000);
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dialogRef.current && !dialogRef.current.contains(event.target)) {
        onClose && onClose();
      }
    };

    // Add wheel event listener for closing on scroll
    const handleWheel = (event) => {
      if (dialogRef.current && !dialogRef.current.contains(event.target)) {
        onClose && onClose();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("wheel", handleWheel);
    
    // Prevent scroll on body when dialog is open
    document.body.style.overflow = 'hidden';
    
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("wheel", handleWheel);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  // Handle touch events to detect scroll attempts
  const handleTouchStart = useRef({ y: 0 });
  
  const onTouchStart = (e) => {
    handleTouchStart.current.y = e.touches[0].clientY;
  };
  
  const onTouchMove = (e) => {
    const touchY = e.touches[0].clientY;
    const diff = touchY - handleTouchStart.current.y;
    
    // If user attempts to scroll (moved finger more than 10px), close the widget
    if (Math.abs(diff) > 10) {
      onClose && onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-2">
      {/* Add transparent overlay to catch touch events */}
      <div 
        className="fixed inset-0 bg-black opacity-20 z-40" 
        onClick={onClose}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
      />
      <div 
        ref={dialogRef} 
        className="w-full max-w-md border border-gray-700 bg-gradient-to-b from-[#141414] to-[#131313] rounded-lg overflow-hidden h-[500px] flex flex-col animate-fadeIn z-50"
      >
        <div className="pt-4 px-4 space-y-4 flex-1 flex flex-col overflow-hidden">
          {/* Search Section */}
          <div className="relative pb-1 flex-shrink-0">
            <Search className="absolute left-3 top-3 h-4 w-4 text-gray-500" />
            <input
              placeholder="Search"
              value={searchQuery}
              onChange={handleSearch}
              className="w-full pl-9 pr-3 py-2 bg-[#141414] text-gray-200 rounded-md border border-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-600"
            />
          </div>
          
          {/* Loading indicator */}
          {isSearching && (
            <div className="flex justify-center py-2 flex-shrink-0">
              <div className="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-gray-300"></div>
            </div>
          )}
          
          {/* Search Results or Recent Chats Grid - with flex-1 to take remaining space */}
          <div className="grid grid-cols-2 380:grid-cols-3 scrollbar-hide xl:grid-cols-4 gap-4 overflow-y-auto flex-1">
            {searchQuery.trim() && searchResults.length > 0 ? (
              // Display search results
              searchResults.map((user) => {
                const roomId = [currentUser.id, user.id].sort().join('_');
                return (
                  <button
                    key={user.id}
                    className="flex flex-col ml-1 items-center space-y-1 hover:opacity-80 transition-opacity"
                    onClick={() => handleSearchUserSelect(user)}
                  >
                    <div className="relative">
                      <img
                        src={
                          user.profilePicture ?
                          `${cloud}/cloudofscubiee/profilePic/${user.profilePicture}` : "/logos/DefaultPicture.png"}
                        alt={user.username}
                        className="h-16 w-16 bg-gray-300 max-md:w-15 max-md:h-15 rounded-full object-cover border-2 border-gray-700"
                      />
                      {selectedUsers.includes(roomId) && (
                        <div className="absolute bottom-0 right-0 h-5 w-5 rounded-full bg-blue-500 flex items-center justify-center">
                          <Check className="h-3 w-3 text-white" />
                        </div>
                      )}
                    </div>
                    <span className="text-sm max-md:text-[13.5px] text-center line-clamp-1 text-gray-300">
                      {user.username}
                    </span>
                  </button>
                );
              })
            ) : !searchQuery.trim() || (searchQuery.trim() && searchResults.length === 0 && !isSearching) ? (
              // Display recent chats when no search query or when search returns no results
              recentChats.map((chat) => {
                const user = chat.otherUser;
                return (
                  <button
                    key={chat.chatRoomId}
                    className="flex flex-col items-center space-y-1 hover:opacity-80 transition-opacity"
                    onClick={() => handleUserSelect(chat.chatRoomId)}
                  >
                    <div className="relative">
                      <img
                        src={
                          user?.profilePicture ?
                          `${cloud}/cloudofscubiee/profilePic/${user?.profilePicture}` : "/logos/DefaultPicture.png"}
                        alt={user?.username}
                        className="h-16 w-16 bg-gray-300 max-md:w-15 max-md:h-15 rounded-full object-cover border-2 border-gray-700"
                      />
                      {selectedUsers.includes(chat.chatRoomId) && (
                        <div className="absolute bottom-0 right-0 h-5 w-5 rounded-full bg-blue-500 flex items-center justify-center">
                          <Check className="h-3 w-3 text-white" />
                        </div>
                      )}
                    </div>
                    <span className="text-sm max-md:text-[13.5px] text-center line-clamp-1 text-gray-300">
                      {user?.username}
                    </span>
                  </button>
                );
              })
            ) : null}
            
            {/* No results message */}
            {searchQuery.trim() && searchResults.length === 0 && !isSearching && (
              <div className="col-span-full text-center text-gray-400 py-4">
                No users found
              </div>
            )}
          </div>
        </div>
        {/* Share Options - fixed at bottom */}
        <div className="flex items-center justify-between p-4 max-md:p-3 border-t border-gray-800 flex-shrink-0">
          {selectedUsers.length > 0 ? (
            <button
              onClick={sendPost}
              className="flex-1 flex flex-col items-center space-y-1 bg-white text-black hover:bg-gray-200 py-2 rounded-md"
            >
              <div className="h-6 w-8 flex items-center justify-center">
                <span className="text-md font-bold font-sans">Share</span>
              </div>
            </button>
          ) : (
            [
              { app: "whatsapp", icon: FaWhatsapp, label: "WhatsApp", color: "bg-[#1b221e]" },
              { app: "facebook", icon: FaFacebookF, label: "Facebook", color: "bg-[#1b221e]" },
              { app: "instagram", icon: FaInstagram, label: "Instagram", color: "bg-[#1b221e]" },
              { app: "copy", icon: Link2, label: "Copy link", color: "bg-[#1b221e]" },
              { app: "email", icon: MdOutlineMail, label: "Email", color: "bg-[#1b221e]" },
            ].map(({ app, icon: Icon, label, color }) => (
              <button
                key={label}
                onClick={() => {
                  if (app === "copy") {
                    navigator.clipboard.writeText(`${Domain}/${postId}`);
                    showCopyNotice(); // Show the notification
                  } else if (app === "story") {
                    // Store the postId into widgetSlice's storyPostId, then close the share widget
                    dispatch(setStoryPostId(postId));
                    dispatch(setShowWidget(false));
                    onClose();
                    navigate('/story'); // navigate to the story route
                  } else {
                    handleShare(app);
                  }
                }}
                className="flex-1 flex flex-col items-center space-y-1 text-gray-300 hover:bg-[#171a18] py-1 rounded-md"
              >
                <div className={`h-10 w-10 rounded-full ${color} flex items-center justify-center`}>
                  <Icon className="h-5 w-5 text-white" />
                </div>
                <span className="text-xs">{label}</span>
              </button>
            ))
          )}
        </div>
      </div>
      
      {/* Copy Link Notification */}
      {showCopyNotification && (
        <div className="fixed top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-black bg-opacity-60 text-white px-4 py-2 rounded-md z-[60] font-medium">
          Link copied
        </div>
      )}
      
      {/* Note: The Sent notification is now created dynamically in the DOM */}
      
      {/* Conditionally render the CreateStory component as a modal */}
      {showCreateStory && (
        <CreateStory
          postId={createStoryPostId}
          onClose={() => setShowCreateStory(false)}
        />
      )}
    </div>
  );
}

export default ShareDialog;