import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux'; // Add Redux hooks
import axios from 'axios';
import { RiVerifiedBadgeFill } from "react-icons/ri";
import { fetchSuggestedUsers } from '../Slices/HomeSlice'; // Import the action

const api = import.meta.env.VITE_API_URL;
const cloud = import.meta.env.VITE_CLOUD_URL;

const SuggestedUsers = () => {
  const [followLoading, setFollowLoading] = useState({});
  const navigate = useNavigate();
  const dispatch = useDispatch(); // Add dispatch
  
  // Get suggested users from Redux state
  const { 
    suggestedUsers: users,
    suggestionsLoading: loading,
    suggestionsLastFetched
  } = useSelector(state => state.home);
  
  useEffect(() => {
    // Only fetch suggestions if they haven't been fetched before or it's been more than 5 minutes
    const shouldFetchSuggestions = !suggestionsLastFetched || 
      (Date.now() - suggestionsLastFetched > 5 * 60 * 1000) || 
      users.length === 0;
    
    if (shouldFetchSuggestions) {
      console.log("Fetching suggested users...");
      dispatch(fetchSuggestedUsers(5));
    } else {
      console.log("Using cached suggested users");
    }
  }, [dispatch, suggestionsLastFetched, users.length]);
  
  const handleFollowToggle = async (userId) => {
    // Set loading state for this specific user
    setFollowLoading(prev => ({ ...prev, [userId]: true }));
    
    try {
      // Send follow request
      await axios.post(`${api}/user/follow/${userId}`, {}, {
        withCredentials: true
      });
      
      // Update local state to show the followed status
      // We're modifying the Redux state by dispatching a custom action
      dispatch({
        type: 'home/updateSuggestedUserFollowStatus',
        payload: { userId, followedByMe: true }
      });
    } catch (error) {
      console.error('Error following user:', error);
    } finally {
      // Clear loading state
      setFollowLoading(prev => ({ ...prev, [userId]: false }));
    }
  };
  
  const navigateToProfile = (username) => {
    navigate(`/${username}`);
  };
  
  if (loading) {
    return (
        <div className="bg-[#0a0a0a] md:border-1 border-[#111]  max-md:border-b-4  md:rounded-xl p-4">
        <h3 className="text-white font-semibold mb-4">Suggested for you</h3>
        <div className="animate-pulse">
          {[...Array(3)].map((_, index) => (
            <div key={index} className="flex items-center mb-4">
              <div className="w-10 h-10 bg-gray-700 rounded-full"></div>
              <div className="ml-3 flex-1">
                <div className="h-4 bg-gray-700 rounded w-3/4 mb-2"></div>
                <div className="h-3 bg-gray-700 rounded w-1/2"></div>
              </div>
              <div className="w-16 h-8 bg-gray-700 rounded-full"></div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  
  if (users.length === 0) {
    return null;
  }
  
  return (
    <div className="bg-[#0a0a0a] xl:mr-[-70px] md:mr-[-20px] md:border-1 border-[#111]  max-md:border-b-4  md:rounded-xl p-4">
      <h3 className="text-white font-semibold text-[17.4px] mb-6">Suggested for you</h3>
      
      <div className="space-y-5">
        {users.map(user => (
          <div key={user.id} className="flex items-center justify-between">
            <div 
              className="flex items-center cursor-pointer"
              onClick={() => navigateToProfile(user.username)}
            >
              <img 
                src={user.profilePictureUrl || 
                  (user.profilePicture
                    ? `${cloud}/cloudofscubiee/profilePic/${user.profilePicture}`
                    : "/logos/DefaultPicture.png")}
                alt={user.username}
                className="w-[45px] h-[45px] bg-gray-300 rounded-full object-cover"
              />
              <div className="ml-3">
                <div className="flex items-center gap-1">
                  <p className="text-white font-sans text-[] font-medium">{user.username}</p>
                  {!!user.Verified && (
                    <RiVerifiedBadgeFill className="text-blue-500 h-[14px] w-[14px]" />
                  )}
                </div>
                <p className="text-gray-400 text-xs">
                  {user.reason || `${user.firstName} ${user.lastName}`}
                </p>
              </div>
            </div>
            
            <button
              onClick={() => handleFollowToggle(user.id)}
              disabled={followLoading[user.id] || user.followedByMe}
              className={`px-4 py-1 max-md:px-[12px] text-sm max-md:text-[13.5] font-sans font-medium rounded-full transition-colors ${
                user.followedByMe 
                  ? 'bg-transparent text-gray-400 border border-gray-700' 
                  : 'bg-gray-200 text-black hover:bg-gray-400'
              }`}
            >
              {followLoading[user.id] ? (
                <span className="h-4 w-4 border-2 border-t-transparent border-black border-solid rounded-full inline-block animate-spin"></span>
              ) : user.followedByMe ? (
                'Following'
              ) : (
                'Follow'
              )}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

export default SuggestedUsers;