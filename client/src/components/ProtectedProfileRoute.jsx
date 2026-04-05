import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { useSelector } from 'react-redux';
import MyProfile from '../pages/MyProfile';
import Profile from '../pages/Profile';
import { toast } from 'react-toastify';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

const ProtectedProfileRoute = () => {
  const { username } = useParams();
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(true);
  const [isOwnProfile, setIsOwnProfile] = useState(false);
  
  // Get current user data from Redux store
  const userData = useSelector(state => state.user.userData);
  
  useEffect(() => {
    const checkProfile = async () => {
      try {
        // CRITICAL IMPROVEMENT: First check Redux store for current user data
        if (userData) {
          console.log("User data found in Redux store:", userData);
          
          // If the profile being viewed matches the logged-in user's profile, show MyProfile
          if (userData.username === username) {
            console.log("This is the user's own profile - using Redux data");
            setIsOwnProfile(true);
            setIsLoading(false);
            return;
          }
        }
        
        // If not the user's own profile or no Redux data, check with the server
        console.log("Not user's profile or no Redux data, checking with server...");
        
        // First, check if this is the user's own profile
        const userResponse = await axios.get(`${api}/auth/check-username/${username}`, {
          withCredentials: true
        });
        
        if (userResponse.data.isCurrentUser) {
          console.log("Server confirms this is the user's own profile");
          setIsOwnProfile(true);
        } else {
          console.log("This is someone else's profile");
          setIsOwnProfile(false);
        }
        
        // Also verify the requested profile exists
        const profileExists = userResponse.data.exists;
        if (!profileExists) {
          console.log("Profile does not exist");
          toast.error("User not found");
          navigate('/');
          return;
        }
      } catch (error) {
        console.error("Error checking profile:", error);
        
        // IMPROVED ERROR HANDLING: Check if we have Redux data to fall back on
        if (userData && userData.username === username) {
          console.log("Error, but falling back to Redux data for own profile");
          setIsOwnProfile(true);
        } else if (error.response?.status === 401) {
          // Only redirect to login if unauthorized and trying to access own profile
          console.log("Unauthorized - redirecting to login");
          navigate('/sign-in');
          return;
        } else {
          // For other errors on other profiles, we'll still try to render the public profile
          console.log("Error, treating as other user's profile");
          setIsOwnProfile(false);
        }
      } finally {
        setIsLoading(false);
      }
    };

    checkProfile();
  }, [username, navigate, userData]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex justify-center items-center bg-[#0a0a0a] text-white">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-white"></div>
      </div>
    );
  }

  return isOwnProfile ? <MyProfile /> : <Profile username={username} />;
};

export default ProtectedProfileRoute;