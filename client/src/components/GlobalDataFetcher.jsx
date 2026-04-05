import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import axios from 'axios';
import { setRecentChats } from '../Slices/ChatSlice';
import { fetchNotifications } from '../Slices/NotificationSlice';

const GlobalDataFetcher = () => {
  const dispatch = useDispatch();
  const userData = useSelector(state => state.user.userData);
  const api = import.meta.env.VITE_API_URL;
  const isAuthenticated = !!userData?.id;

  useEffect(() => {
    // Only fetch data if user is authenticated
    if (!isAuthenticated) return;
    
    // Fetch recent chats using the same API call used in Chat.jsx
    const fetchRecentChats = async () => {
      try {
        const response = await axios.get(`${api}/chat/recent-chats`, { withCredentials: true });
        dispatch(setRecentChats(response.data));
      } catch (error) {
        console.error('Error fetching recent chats globally:', error);
      }
    };

    // Fetch notifications using the existing thunk in NotificationSlice.js
    const loadNotifications = () => {
      dispatch(fetchNotifications(1, { skipIfDataExists: false }));
    };

    // Execute both fetches when component mounts
    fetchRecentChats();
    loadNotifications();
    
    // Set up periodic refresh every 2 minutes if user stays on the site
    const intervalId = setInterval(() => {
      if (document.visibilityState === 'visible') {
        fetchRecentChats();
        loadNotifications();
      }
    }, 120000); // 2 minutes
    
    return () => clearInterval(intervalId);
  }, [dispatch, isAuthenticated, api]);

  // This component doesn't render anything
  return null;
};

export default GlobalDataFetcher;
