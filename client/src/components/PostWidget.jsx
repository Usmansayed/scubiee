import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaShareSquare } from 'react-icons/fa';
import { MoreHorizontal } from 'lucide-react';
import axios from 'axios';
import CommentWidget from '../components/CommentWidget';
import { useDispatch, useSelector } from 'react-redux';
import { setIsCommentOpen } from '../Slices/WidgetSlice';
import ReportWidget from './ReportWidget';
import { IoCloseSharp } from "react-icons/io5";
import { BsBookmark,BsSend ,BsBookmarkFill   } from "react-icons/bs";
import { BiUpvote, BiSolidUpvote } from "react-icons/bi";
import { IoMdMore} from "react-icons/io";
import { TfiCommentAlt } from "react-icons/tfi";
import ShareDialog from "./shareWidget"; // import ShareDialog
import { current } from '@reduxjs/toolkit';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

const PostWidget = ({ postId, onClose ,userId}) => {
  const [post, setPost] = useState(null);
  const [showOptions, setShowOptions] = useState(false);
  const isCommentOpen = useSelector(state => state.widget.isCommentOpen);
  const [CommentPostId, setCommentPostId] = useState(null);
  const dispatch = useDispatch();

  const [showReportWidget, setShowReportWidget] = useState(false);
  const [reportType, setReportType] = useState(null);
  const [reportTargetId, setReportTargetId] = useState(null);
  const reportWidgetRef = useRef(null);
  const [showShareWidget, setShowShareWidget] = useState(false);
  const CurrentUserId = useSelector((state) => state.user.userData.id);
  const [interactions, setInteractions] = useState({
    liked: false,
    saved: false,
    likesCount: 0 , // Add this
    commentsCount: 0
  });
    const optionsRef = useRef(null);

      // Add handlers
  const handleReportPost = () => {
    setReportType('post');
    setReportTargetId(postId);
    setShowReportWidget(true);
    setShowOptions(false);
  };

  const handleReportUser = () => {
    setReportType('user');
    setReportTargetId(userId);
    setShowReportWidget(true);
    setShowOptions(false);
  };

  useEffect(() => {
    function handleClickOutside(event) {
      // Ignore clicks inside the ReportWidget if it’s open
      if (showReportWidget && reportWidgetRef.current && reportWidgetRef.current.contains(event.target)) {
        return;
      }
      // Ignore clicks inside the CommentWidget if it’s open
      if (isCommentOpen && commentWidgetRef.current && commentWidgetRef.current.contains(event.target)) {
        return;
      }
      // Otherwise, if outside the main post widget, close
      if (widgetRef.current && !widgetRef.current.contains(event.target)) {
        onClose();
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose, showReportWidget, isCommentOpen]);
  

  useEffect(() => {
    if (post?.interactions) {
      setInteractions({
        liked: post.interactions.liked || false,
        saved: post.interactions.saved || false,
        likesCount: post.likes || 0
      });
    }
  }, [post]);
  

  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const widgetRef = useRef();
  const commentWidgetRef = useRef();

  const toggleOptions = () => setShowOptions(!showOptions);

  const handleCommentClick = () => {
    dispatch(setIsCommentOpen(true));
    setCommentPostId(post.id);

  };

  const handleLikeToggle = async () => {
    if (isLoading) return;
    setIsLoading(true);
  
    const prevState = { ...interactions };
    setInteractions(prev => ({
      ...prev,
      liked: !prev.liked,
      likesCount: prev.liked ? prev.likesCount - 1 : prev.likesCount + 1
    }));
  
    try {
      const response = await axios.post(
        `${api}/user-interactions/like/${post.id}`,
        {},
        {
          withCredentials: true,
          headers: {
            accessToken: localStorage.getItem("accessToken")
          }
        }
      );
  
      if (!response.data.success) {
        setInteractions(prevState);
      }
    } catch (error) {
      console.error('Like toggle error:', error);
      setInteractions(prevState);
    } finally {
      setIsLoading(false);
    }
  };
  
  const handleSaveToggle = async () => {
    if (isLoading) return;
    setIsLoading(true);
  
    const prevState = { ...interactions };
    setInteractions(prev => ({
      ...prev,
      saved: !prev.saved
    }));
  
    try {
      const response = await axios.post(
        `${api}/user-interactions/save/${post.id}`,
        {},
        {
          withCredentials: true,
          headers: {
            accessToken: localStorage.getItem("accessToken")
          }
        }
      );
  
      if (!response.data.success) {
        setInteractions(prevState);
      }
    } catch (error) {
      console.error('Save toggle error:', error);
      setInteractions(prevState);
    } finally {
      setIsLoading(false);
    }
  };
  // Update initial fetch
  useEffect(() => {
    const fetchPostDetails = async () => {
      try {
        const { data } = await axios.get(`${api}/post/details/${postId}`, {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") },
        });
        setPost(data);
        setInteractions({
          liked: Boolean(data.interactions?.liked),
          saved: Boolean(data.interactions?.saved),
          likesCount: data.likes || 0,
          commentsCount: data.comments || 0
        });
      } catch (error) {
        console.error("Error fetching post details:", error);
      }
    };
  
    if (postId) fetchPostDetails();
  }, [postId]);


  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        !isCommentOpen && 
        widgetRef.current && 
        !widgetRef.current.contains(event.target) &&
        reportWidgetRef.current && 
        !reportWidgetRef.current.contains(event.target)
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose, isCommentOpen]);

  if (!post) {
    return <div>Loading...</div>;
  }

  const handleOverlayClick = () => {
    onClose();
  }; 


  const handleNavigateToPost = () => {
    // Reset body styles before navigation
    document.body.style.overflow = 'auto';
    document.body.style.paddingRight = '0px';
    
    onClose(); 
    navigate(`/viewpost/${post.id}`);
  };
  
 
  return (
    <>
 
    <div
     className={`fixed inset-0 z-50 flex items-center justify-center ${
      showShareWidget ? "bg-black/70 " : "bg-black/70"
    }`}
    onClick={showShareWidget ? (e) => e.stopPropagation() : onClose}
    
  >   {showShareWidget && (
      <ShareDialog 
        postId={postId} 
        onClose={() => setShowShareWidget(false)} 
      />
    )}
     {isCommentOpen && (
        <CommentWidget
          postId={postId}
          isOpen={isCommentOpen}
          onClose={() => dispatch(setIsCommentOpen(false))}
          userId={userId}
        />
      )}
      <div
      onClick={(e) => e.stopPropagation()}
      className="space-y-6 max-sm:w-[98%] sm:w-[500px]  max-md:mb-4 md:w-[580px] bg-black rounded-xl "
    >
        <article className="overflow-hidden rounded-xl bg-white/5 border-gray-800 border-[1px] py-2 pb-4 max-md:py-1  backdrop-blur-md text-gray-200">
          {/* Header */}
          <div className="flex items-center justify-between mb-4 px-3">
            <div className="flex items-center gap-3">
              <div className="relative h-10 w-10 max-md:w-9 max-md:h-9 rounded-full overflow-hidden">
                <img
              
                  src={
                    post.author.profilePicture ?
                    `${cloud}/cloudofscubiee/profilePic/${post.author.profilePicture}` : "/logos/DefaultPicture.png"}
                  alt={post.author.username}
                  className="w-full h-full bg-gray-300 object-cover"
                />
              </div>
              <div>
                <h3 className="font-semibold font-sans">{post.author.username}</h3>
                <p className="text-xs font-sans font-semibold text-gray-400">
                  {new Date(post.createdAt).toLocaleDateString()}
                </p>
              </div>
            </div>
            <div className="relative" ref={optionsRef}>
        <button 
          className="text-gray-400 hover:text-white" 
          onClick={(e) => {
            e.stopPropagation();
            toggleOptions();
          }}
        >
          <IoMdMore className="h-6 w-6" />
        </button>
        
        {showOptions && (
          <div 
            className="absolute right-0 mt-2 w-48 bg-[#14161b] rounded-md shadow-lg z-50"
            onClick={(e) => e.stopPropagation()}
          >
            <ul className="py-1 text-gray-200">
                <li 
                  className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-600"
                  onClick={handleReportPost}
                >
                  Report Post
                </li>
                <li 
                  className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer text-red-600"
                  onClick={handleReportUser}
                >
                  Report User
                </li>
              <li className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer">Copy Link</li>
              <li className="block px-4 py-2 text-sm hover:bg-gray-800 cursor-pointer" onClick={toggleOptions}>Cancel</li>
            </ul>
          </div>
        )}
      </div>
          </div>
          {/* Post Content */}
          <div className="relative mb-4 w-full [aspect-ratio:9/6] max-md:mx-auto max-md:w-full" onClick={handleNavigateToPost}>
            <img
              src={`${cloud}/cloudofscubiee/Postthumbnail/${post.thumbnail}`}
              alt={post.title}
              className="absolute inset-0 h-full w-full object-cover"
            />
          </div>
          <div className='px-3 max-md:px-1'>
            <h2 className="mb-2 text-[19px] max-md:text-[17.5px] font-semibold">{post.title}</h2>
          </div>

          {/* Icons Section */}
         
          <div className="flex mt-4 max-md:mb-4 max-sm:mb-2 px-4 max-md:px-2">
            <button
              className={`flex items-center mt-[-2px] gap-1 ${interactions.liked ? 'text-gray-300' : 'text-gray-300'}`}
              onClick={handleLikeToggle}
              disabled={isLoading}
            >
              {interactions.liked ? 
                <BiSolidUpvote className="h-6 w-6 mr-[2px] text-blue-500" /> : 
                <BiUpvote className="h-6 w-6 mr-[2px]" />
              }
              <span className='mr-2 mb-[2px]'>{interactions.likesCount}</span>
            </button>

            <button 
              className="flex items-center gap-1 text-gray-300 ml-4"
              onClick={handleCommentClick}
            >    
              <TfiCommentAlt className="h-[19px] w-[19px]" />
              <span className="pb-[4px] ml-[2px] mb-[2px]">{post.comments}</span>
            </button>

            <button 
            className="flex items-center gap-1 text-gray-300 ml-auto"
            onClick={() => setShowShareWidget(true)}  // Open share widget
          >
                      

            <BsSend className="h-5 w-5" />
          </button>

            <button
              className={`flex items-center gap-1 ml-6 ${interactions.saved ? 'text-gray-200' : 'text-gray-300'}`}
              onClick={handleSaveToggle}
              disabled={isLoading}
            >
              {interactions.saved ? 
                <BsBookmarkFill className="h-5 w-5" /> : 
                <BsBookmark className="h-5 w-5" />
              }
            </button>
          </div>
        </article>
      </div>
      {showReportWidget && (
      <div className="fixed inset-0 flex items-center justify-center"
           onClick={(e) => e.stopPropagation()}>
        <div
          ref={reportWidgetRef}
          className="bg-[#1a1a1a] p-4 rounded-md w-[90%] sm:w-[400px] text-white"
        >
          <ReportWidget
            onClose={() => setShowReportWidget(false)}
            type={reportType}
            targetId={reportTargetId}
          />
            <button
              onClick={() => setShowReportWidget(false)}
              className="absolute top-2 right-2 text-gray-400 hover:text-gray-200"
            >
              <IoCloseSharp size={24} />
            </button>
          </div>
        </div>
      )}
    </div></>
  );
};

export default PostWidget;