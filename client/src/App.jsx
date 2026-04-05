import React, { useEffect, useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Provider, useDispatch, useSelector } from 'react-redux';
import { setSocket, setMessages, updateOnlineUsers, setRecentChats } from './Slices/ChatSlice';
import { checkAuth, setSocketUserId } from './Slices/UserSlice';
import { fetchUnreadNotificationCount, fetchNotifications } from './Slices/NotificationSlice';
import VerticalNavbar from './components/VerticalNavbar';
import ScrollToTop from './components/ScrollToTop';
import store from './Store';
import MainLayout from './Layout/MainLayout';
import Chat from './Chat';
import Home from './pages/Home';
import Registration from './pages/Registration';
import Login from './pages/Login';
import CreatePost from './pages/CreatePost';
import ViewPost from './pages/ViewPost';
import ProtectedProfileRoute from './components/ProtectedProfileRoute';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import axios from 'axios';
import Feed from './pages/Feed';
import Editor from './pages/Editor';
import Search from './pages/Search';
import Notification from './pages/Notification';
import ImageEditor from './components/CreateStory';
import CuisineSelector from './components/selection';
import EditProfile from './pages/EditProfile';
import Shorts from './pages/Shorts';
import CreateShort from './pages/CreateShort';
import { useNavigate, useLocation } from 'react-router-dom';
import socket, { updateSocketWithUserId } from './socket';
import UsersPosts from './components/UsersPosts';
import HelpSupport from './pages/HelpSupport';
import PrivacyPolicy from './pages/PrivacyPolicy';
import TermsOfService from './pages/TermsOfService';
import AboutUs from './pages/AboutUs';
import GlobalDataFetcher from './components/GlobalDataFetcher';
import MyPaper from './pages/MyPapers';
import CreatePaper from './pages/CreatePaper';
import Paper from './pages/Paper';
import ManagePapers from './pages/ManagePapers';
import Communities from './pages/Communities';
import CreateCommunity from './pages/CreateCommunity';
import EditCommunity from './pages/EditCommunity';
import CommunityDetail from './pages/CommunityDetail';

const api = import.meta.env.VITE_API_URL;
const cloud = import.meta.env.VITE_CLOUD_URL;

function HistoryReplacingRoute({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  
  useEffect(() => {
    // Replace the current entry in history stack when component mounts
    navigate(location.pathname, { replace: true });
  }, []);
  
  return children;
}


const App = () => {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const { userData, socketUserId, isPosting } = useSelector((state) => state.user);
  const [loading, setLoading] = useState(true); // Set initial loading to true
  const [tempUserDataExists, setTempUserDataExists] = useState(false);
  const [tempUserDataChecked, setTempUserDataChecked] = useState(false);
  const isLoggedIn = useSelector(state => !!state.user.userData);
  const [notificationsInitialized, setNotificationsInitialized] = useState(false);
  
  // Offline state for PWA support
  const [isOffline, setIsOffline] = useState(!navigator.onLine);
  
  // Define truly public routes that never require authentication checks
  const publicRoutes = ['/privacy-policy', '/terms', '/help-support', '/about-us', 
  ];
  const isPublicRoute = publicRoutes.includes(location.pathname);
  const isSignInRoute = location.pathname === '/sign-in';
  const isCompleteRoute = location.pathname === '/complete';

  

  // Offline support - listen to browser online/offline events
  useEffect(() => {
    const handleOnline = () => {
      console.log('App is now online');
      setIsOffline(false);
    };
    
    const handleOffline = () => {
      console.log('App is now offline');
      setIsOffline(true);
    };
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // SEPARATE cookie check - only run if online
  useEffect(() => {
    // Skip if we're offline
    if (isOffline) return;
    
    const checkTempUserData = async () => {
      try {
        console.log('Checking for temp_user_data cookie...');
        const response = await axios.get(`${api}/user/check-temp-data`, { 
          withCredentials: true 
        });
        console.log('Temp user data check result:', response.data);
        setTempUserDataExists(response.data.exists);
      } catch (error) {
        console.error('Error checking temp_user_data:', error);
        setTempUserDataExists(false);
      } finally {
        setTempUserDataChecked(true);
      }
    };
    
    checkTempUserData();
  }, [api, isOffline]); // Add offline dependency

  // Authentication check - now depends on tempUserDataChecked and offline status
  useEffect(() => {
    // Skip if we're offline or loading is already false
    if (isOffline || !loading) return;
    
    // Don't proceed until temp data check is complete
    if (!tempUserDataChecked && isCompleteRoute) {
      console.log('Waiting for temp data check to complete...');
      return;
    }

    // Skip auth check for truly public routes
    if (isPublicRoute) {
      setLoading(false);
      return;
    }

    // Skip auth check for complete route if temp data exists
    if (isCompleteRoute && tempUserDataExists) {
      console.log('Allowing access to /complete with temp user data');
      setLoading(false);
      return;
    }

    dispatch(checkAuth())
      .unwrap()
      .then((response) => {
        // If user is authenticated and on sign-in page, redirect to their profile
        if (response.username && isSignInRoute) {
          navigate(`/${response.username}`);
        }
        
        // Store user ID in Redux instead of localStorage
        if (response && response.id) {
          dispatch(setSocketUserId(response.id));
          console.log('Saved user ID to Redux state:', response.id);
          
          // Only fetch unread notifications once on app initialization
          if (!notificationsInitialized) {
            console.log('Initializing notifications count...');
            dispatch(fetchUnreadNotificationCount());
            setNotificationsInitialized(true);
          }
        }
      })
      .catch((error) => {
        // Handle auth check failure
        if (!isSignInRoute && !isPublicRoute && !(isCompleteRoute && tempUserDataExists)) {
          navigate('/sign-in');
        }
      })
      .finally(() => {
        if (!isOffline) {
          setLoading(false);
        }
      });
  }, [dispatch, navigate, location, notificationsInitialized, isPublicRoute, isSignInRoute, 
      isCompleteRoute, tempUserDataExists, tempUserDataChecked, isOffline, loading]);

  // Show offline indicator if needed (optional)
  const OfflineIndicator = () => (
    isOffline ? (
      <div style={{
        position: 'fixed',
        top: '10px',
        left: '50%',
        transform: 'translateX(-50%)',
        background: '#ff4655',
        color: 'white',
        padding: '8px 16px',
        borderRadius: '20px',
        fontSize: '14px',
        zIndex: 9999,
        fontWeight: '500'
      }}>
        📡 You're offline - some features may be limited
      </div>
    ) : null
  );

  // Show uploading indicator when user is posting
  const UploadingIndicator = () => (
    isPosting ? (
      <div style={{
        position: 'fixed',
        top: '10px',
        left: '50%',
        transform: 'translateX(-50%)',
        background: '#111',
        color: 'white',
        padding: '8px 16px',
        borderRadius: '20px',
        fontSize: '14px',
        zIndex: 9999,
        fontWeight: '500',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <div style={{
          width: '16px',
          height: '16px',
          border: '2px solid transparent',
          borderTop: '2px solid white',
          borderRadius: '50%',
          animation: 'spin 1s linear infinite'
        }}></div>
        📤 Your post is being uploaded
        <style>{`
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    ) : null
  );

  // Loading screen component with the logo
  const LoadingScreen = () => (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      width: '100vw',
      background: '#0a0a0a' // Or your preferred background color
    }}>
      <img src="/scubiee2.svg" alt="Scubiee Logo" style={{
        maxWidth: '120px', // Adjust size as needed
        animation: 'pulse 1.5s infinite ease-in-out'
      }} />
      <style>{`
        @keyframes pulse {
          0% { opacity: 0.6; transform: scale(0.95); }
          50% { opacity: 1; transform: scale(1.05); }
          100% { opacity: 0.6; transform: scale(0.95); }
        }
      `}</style>
    </div>
  );

  if (loading && (!tempUserDataChecked || !isPublicRoute)) {
    return <LoadingScreen />;
  }

  return (
    <Provider store={store}>
      <OfflineIndicator />
      <UploadingIndicator />
      <ScrollToTop />
      <GlobalDataFetcher />
      <VerticalNavbar />
    
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={
            isLoggedIn ? <Home /> : <Navigate to="/sign-in" replace />
          } />
          <Route path="/sign-in" element={
            isLoggedIn ? <Navigate to={`/${userData.username}`} replace /> : <Registration />
          } />
          {/* Complete route without redirection logic in element - handled by our effects */}
          <Route path="/complete" element={tempUserDataExists ? 
  <HistoryReplacingRoute><Login /></HistoryReplacingRoute> : 
  <Navigate to="/sign-in" replace />} />          {/* Public routes - no auth required */}
          <Route path="/privacy-policy" element={<HistoryReplacingRoute><PrivacyPolicy /></HistoryReplacingRoute>} />
<Route path="/terms" element={<HistoryReplacingRoute><TermsOfService /></HistoryReplacingRoute>} />
<Route path="/help-support" element={<HistoryReplacingRoute><HelpSupport /></HistoryReplacingRoute>} />
          
          {/* Protected routes - require authentication */}
          <Route path="/chat" element={isLoggedIn ? <Chat /> : <Navigate to="/sign-in" />} />
          <Route path="/chat/:userId" element={isLoggedIn ? <Chat /> : <Navigate to="/sign-in" />} />
          <Route path="/create-post" element={isLoggedIn ? <HistoryReplacingRoute><CreatePost /></HistoryReplacingRoute> : <Navigate to="/sign-in" />} />
          <Route path="/create-post/:communityId" element={isLoggedIn ? <HistoryReplacingRoute><CreatePost /></HistoryReplacingRoute> : <Navigate to="/sign-in" />} />
          <Route path="/create-short" element={isLoggedIn ? <HistoryReplacingRoute><CreateShort /></HistoryReplacingRoute> : <Navigate to="/sign-in" />} />
          
          {/* Digital Papers routes */}
          <Route path="/my-papers" element={isLoggedIn ? <MyPaper /> : <Navigate to="/sign-in" />} />
          <Route path="/manage-papers" element={isLoggedIn ? <ManagePapers /> : <Navigate to="/sign-in" />} />
          <Route path="/create-paper" element={isLoggedIn ? <HistoryReplacingRoute><CreatePaper /></HistoryReplacingRoute> : <Navigate to="/sign-in" />} />
          <Route path="/paper/:id" element={isLoggedIn ? <Paper /> : <Navigate to="/sign-in" />} />
          
          {/* Communities routes */}
          <Route path="/communities" element={isLoggedIn ? <Communities /> : <Navigate to="/sign-in" />} />
          <Route path="/create-community" element={isLoggedIn ? <HistoryReplacingRoute><CreateCommunity /></HistoryReplacingRoute> : <Navigate to="/sign-in" />} />
          <Route path="/edit-community/:id" element={isLoggedIn ? <HistoryReplacingRoute><EditCommunity /></HistoryReplacingRoute> : <Navigate to="/sign-in" />} />
          <Route path="/community/:id" element={isLoggedIn ? <CommunityDetail /> : <Navigate to="/sign-in" />} />
          
          {/* Separate routes for shorts feed and single short */}
          <Route path="/shorts" element={<Shorts />} />
          <Route path="/shorts/:shortId" element={<Shorts />} />
          {/* Add new route to handle shorts with notification parameters */}
          <Route path="/shorts/:shortId/notification" element={<Shorts />} />
          
          {/* Add new routes for UsersPosts */}
          <Route path="/posts/:type" element={<UsersPosts />} />
          <Route path="/about-us" element={<HistoryReplacingRoute><AboutUs /></HistoryReplacingRoute>} />



          
          <Route path="/viewpost/:id" element={<ViewPost />} />
          <Route path="/:username" element={<ProtectedProfileRoute />} />
          <Route path="/search" element={<Search />} />
          <Route path="/story" element={<ImageEditor />} />
          <Route path="/notifications" element={<Notification />} />
          <Route path="/edit-profile" element={<EditProfile />} />
        </Route>
      </Routes>
    </Provider>
  );
}
export default App;


