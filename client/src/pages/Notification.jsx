import React, { useEffect, useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatDistanceToNow, isToday, isYesterday, format, parseISO } from 'date-fns';
import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
import { useDispatch, useSelector } from 'react-redux';
import { 
  fetchNotifications, 
  markAllNotificationsAsRead,
  setPage,
  markNotificationsAsRead
} from '../Slices/NotificationSlice';
import axios from 'axios';

const Notification = () => {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const api = import.meta.env.VITE_API_URL;
  const DefaultPicture = "/logos/DefaultPicture.png";
  const cloud = import.meta.env.VITE_CLOUD_URL;

  // Get notifications from Redux instead of local state
  const { 
    notifications, 
    fetchLoading, 
    fetchError, 
    hasMore, 
    page,
    unreadCount
  } = useSelector(state => state.notification);

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);
  
  // Track if initial fetch has been done
  const [initialFetchComplete, setInitialFetchComplete] = useState(false);
  
  // Ref for infinite scrolling
  const observer = useRef();
  const lastNotificationRef = useRef();

  // Clear unread notification count when viewing notifications page
  useEffect(() => {
    dispatch(markNotificationsAsRead());
  }, [dispatch]);

  // Initial fetch - only if needed
  useEffect(() => {
    console.log('Notification component mounted, checking for existing data...');
    
    // Always fetch fresh notifications when the component mounts initially
    // This ensures we get new notifications on page refresh
    console.log('Fetching fresh notifications on page load/refresh...');
    dispatch(fetchNotifications(1, { forceRefresh: true }))
      .then(() => {
        setInitialFetchComplete(true);
        // Mark all as read when first opening the page
        dispatch(markAllNotificationsAsRead());
      });
    
    // Set flag that we're on the notification page
    window.isOnNotificationPage = true;
    
    // Cleanup
    return () => {
      window.isOnNotificationPage = false;
    };
  }, [dispatch]);

  // Setup intersection observer for infinite scroll
  useEffect(() => {
    const currentObserver = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && hasMore && !fetchLoading) {
        console.log(`Loading more notifications, page ${page + 1}`);
        dispatch(setPage(page + 1));
      }
    }, { threshold: 0.1 });
    
    observer.current = currentObserver;
    
    return () => {
      if (currentObserver) {
        currentObserver.disconnect();
      }
    };
  }, [hasMore, fetchLoading, page, dispatch]);

  // Connect observer to last element
  useEffect(() => {
    const lastElement = lastNotificationRef.current;
    if (lastElement && observer.current) {
      console.log("Connecting observer to last notification element");
      observer.current.disconnect();
      observer.current.observe(lastElement);
    } else {
      console.log("Could not connect observer - missing ref or observer");
    }
  }, [notifications]);

  // Fetch more notifications when page changes
  useEffect(() => {
    if (page > 1 && initialFetchComplete) {
      console.log(`Fetching page ${page} of notifications`);
      dispatch(fetchNotifications(page));
    }
  }, [page, dispatch, initialFetchComplete]);

  // Group notifications by date categories
  const groupNotificationsByDate = (notifications) => {
    const groups = {
      today: [],
      yesterday: [],
      thisWeek: [],
      thisMonth: [],
      earlier: []
    };
    
    notifications.forEach(notification => {
      if (!notification.createdAt) return;
      
      const date = parseISO(notification.createdAt);
      
      if (isToday(date)) {
        groups.today.push(notification);
      } else if (isYesterday(date)) {
        groups.yesterday.push(notification);
      } else {
        // Check if it's within the last 7 days
        const dayDifference = Math.floor((new Date() - date) / (1000 * 60 * 60 * 24));
        
        if (dayDifference < 7) {
          groups.thisWeek.push(notification);
        } else if (dayDifference < 30) {
          groups.thisMonth.push(notification);
        } else {
          groups.earlier.push(notification);
        }
      }
    });
    
    // Sort each group by createdAt (newest first)
    const sortByNewest = (a, b) => new Date(b.createdAt) - new Date(a.createdAt);
    
    groups.today.sort(sortByNewest);
    groups.yesterday.sort(sortByNewest);
    groups.thisWeek.sort(sortByNewest);
    groups.thisMonth.sort(sortByNewest);
    groups.earlier.sort(sortByNewest);
    
    return groups;
  };

  // Get notification message based on type
  const getNotificationMessage = (notification) => {
    const username = notification.sender?.username || 'Someone';
    
    switch(notification.type) {
      case 'like':
        return notification.isShort 
          ? `${username} liked your short`
          : `${username} liked your post`;
      case 'comment':
        return notification.isShort 
          ? `${username} commented on your short`
          : `${username} commented on your post`;
      case 'follow':
        return `${username} started following you`;
      case 'reply':
        return `${username} replied to your comment`;
      case 'comment_like':
        return `${username} liked your comment`;
      case 'reply_like':
        return `${username} liked your reply`;
      default:
        return notification.message || 'sent you a notification';
    }
  };

  // Format time as relative
  const formatRelativeTime = (dateString) => {
    try {
      return formatDistanceToNow(new Date(dateString), { addSuffix: true });
    } catch (err) {
      return '';
    }
  };

  // Function to navigate to sender's profile
  const navigateToSenderProfile = (e, username) => {
    e.stopPropagation(); // Prevent parent notification click handler from firing
    if (username) {
      navigate(`/${username}`);
    }
  };

  // Handle notification click
  const handleNotificationClick = (notification) => {
    if (!notification) return;

    // Mark notification as read if it's not
    if (!notification.isRead) {
      axios.post(`${api}/notification/mark-as-read/${notification.id}`, {}, { withCredentials: true })
        .catch(error => console.error('Error marking notification as read:', error));
    }

    // Handle different notification types
    switch (notification.type) {
      case 'follow':
        navigate(`/${notification.sender?.username}`);
        break;
      case 'like':
        // Check if the liked post is a short
        if (notification.isShort) {
          navigate(`/shorts/${notification.post_id}`);
        } else {
          navigate(`/viewpost/${notification.post_id}`);
        }
        break;
      case 'comment':
      case 'reply':
      case 'comment_like':
      case 'reply_like':
        // Check if the notification is related to a short or a regular post
        if (notification.isShort) {
          // For shorts: navigate to shorts page with query parameters
          navigate(`/shorts/${notification.post_id}?notificationType=${notification.type}&referenceId=${notification.reference_id}`);
        } else {
          // For regular posts: navigate to viewpost page with query parameters
          navigate(`/viewpost/${notification.post_id}?notificationType=${notification.type}&referenceId=${notification.reference_id}`);
        }
        break;
      case 'mention':
        if (notification.post_id) {
          // Check if the mentioned post is a short
          if (notification.isShort) {
            navigate(`/shorts/${notification.post_id}`);
          } else {
            navigate(`/viewpost/${notification.post_id}`);
          }
        } else {
          navigate(`/${notification.sender?.username}`);
        }
        break;
      default:
        if (notification.post_id) {
          // Check if the default notification is for a short
          if (notification.isShort) {
            navigate(`/shorts/${notification.post_id}`);
          } else {
            navigate(`/viewpost/${notification.post_id}`);
          }
        } else if (notification.sender?.username) {
          navigate(`/${notification.sender.username}`);
        }
    }
  };

  // Force refresh notifications
  const handleRefresh = () => {
    dispatch(fetchNotifications(1, { forceRefresh: true }))
      .then(() => {
        // After fresh fetch, mark all as read
        dispatch(markAllNotificationsAsRead());
      });
  };

  // Loading skeleton
  const NotificationSkeleton = () => (
    <div className="max-w-2xl mx-auto pb-20 px-4 bg-[#0a0a0a] min-h-screen">
      <div className="flex items-center justify-between py-4 mb-4">
        <Skeleton width={160} height={28} className="ml-3" />
      </div>
      
      <div className="bg-[#0a0a0a] rounded-xl overflow-hidden mb-4">
        {Array(5).fill().map((_, index) => (
          <div key={`skeleton-${index}`} className="flex items-center p-4 border-b border-[#222222]">
            <Skeleton circle width={40} height={40} className="mr-3" />
            <div className="flex-1">
              <Skeleton width={index % 2 ? "70%" : "85%"} height={16} />
              <Skeleton width="40%" height={12} className="mt-1" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );

  // Show skeleton during loading
  if (fetchLoading && notifications.length === 0) {
    return (
      <SkeletonTheme baseColor="#202020" highlightColor="#444">
        <NotificationSkeleton />
      </SkeletonTheme>
    );
  }

  // Show error message if fetch failed
  if (fetchError && notifications.length === 0) {
    return (
      <div className="max-w-2xl mx-auto pb-20 px-4 bg-[#0a0a0a] min-h-screen">
        <div className="flex items-center justify-between py-4 mb-2">
          <h1 className="text-2xl ml-3 font-medium font-sans text-white">Notifications</h1>
        </div>
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-8 text-center">
          <p className="text-red-400 mb-4">{fetchError}</p>
          <button 
            onClick={handleRefresh}
            className="py-[6px] px-3 bg-gray-300 hover:bg-gray-400 text-black rounded-full"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  // Group notifications
  const groupedNotifications = groupNotificationsByDate(notifications);

  return (
    <div className="max-w-2xl mx-auto pb-20 px-4 bg-[#0a0a0a] min-h-screen">
      <div className="flex items-center justify-between py-4 mb-2">
        <h1 className="text-2xl ml-3 font-medium font-sans text-white">Notifications</h1>
        
      </div>
      
      {notifications.length === 0 && !fetchLoading ? (
        <div className="bg-[#0a0a0a] border border-[#222222] rounded-xl p-10 text-center">
          <p className="text-gray-400">No notifications yet</p>
        </div>
      ) : (
        <div className="bg-[#0a0a0a] rounded-xl overflow-hidden">
          {/* Today Section */}
          {groupedNotifications.today.length > 0 && (
            <>
              <div className="px-4 py-2 bg-[#0e0e0e] border-b border-[#222222]">
                <h2 className="text-sm font-medium text-gray-400">Today</h2>
              </div>
              {groupedNotifications.today.map((notification, index) => (
                <div 
                  key={notification.id || `notification-today-${index}`}
                  className={`flex items-center p-4 cursor-pointer hover:bg-[#1a1a1a] transition-colors  last:border-b-0 ${
                    !notification.is_read ? 'bg-[#121212]' : 'bg-[#0a0a0a]'
                  }`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div 
                    className="h-10 w-10 rounded-full overflow-hidden mr-3 cursor-pointer"
                    onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                  >
                    <img
                      className={`w-full h-full object-cover ${!notification.sender?.profilePicture ? 'bg-gray-300' : ''}`}
                      src={
                        notification.sender?.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${notification.sender.profilePicture}`
                          : DefaultPicture
                      }
                      alt={notification.sender?.username || 'User'}
                    />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-200">
                      <span 
                        className="font-medium cursor-pointer hover:underline"
                        onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                      >
                        {notification.sender?.username || 'Someone'}
                      </span>{' '}
                      {getNotificationMessage(notification).replace(notification.sender?.username || 'Someone', '')}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatRelativeTime(notification.createdAt)}
                    </p>
                  </div>
                </div>
              ))}
            </>
          )}
          
          {/* Yesterday Section */}
          {groupedNotifications.yesterday.length > 0 && (
            <>
              <div className="px-4 py-2 bg-[#0e0e0e] border-b border-[#222222]">
                <h2 className="text-sm font-medium text-gray-400">Yesterday</h2>
              </div>
              {groupedNotifications.yesterday.map((notification, index) => (
                <div 
                  key={notification.id || `notification-yesterday-${index}`}
                  className={`flex items-center p-4 cursor-pointer hover:bg-[#1a1a1a] transition-colors  border-[#222222] last:border-b-0 ${
                    !notification.is_read ? 'bg-[#121212]' : 'bg-[#0a0a0a]'
                  }`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div 
                    className="h-10 w-10 rounded-full overflow-hidden mr-3 cursor-pointer"
                    onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                  >
                    <img
                      className={`w-full h-full object-cover ${!notification.sender?.profilePicture ? 'bg-gray-300' : ''}`}
                      src={
                        notification.sender?.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${notification.sender.profilePicture}`
                          : DefaultPicture
                      }
                      alt={notification.sender?.username || 'User'}
                    />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-200">
                      <span 
                        className="font-medium cursor-pointer hover:underline"
                        onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                      >
                        {notification.sender?.username || 'Someone'}
                      </span>{' '}
                      {getNotificationMessage(notification).replace(notification.sender?.username || 'Someone', '')}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatRelativeTime(notification.createdAt)}
                    </p>
                  </div>
                </div>
              ))}
            </>
          )}
          
          {/* This Week Section */}
          {groupedNotifications.thisWeek.length > 0 && (
            <>
              <div className="px-4 py-2 bg-[#0e0e0e] border-y border-[#222222]">
                <h2 className="text-sm font-medium text-gray-400">This Week</h2>
              </div>
              {groupedNotifications.thisWeek.map((notification, index) => (
                <div 
                  key={notification.id || `notification-week-${index}`}
                  className={`flex items-center p-4 cursor-pointer hover:bg-[#1a1a1a] transition-colors  last:border-b-0 ${
                    !notification.is_read ? 'bg-[#121212]' : 'bg-[#0a0a0a]'
                  }`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div 
                    className="h-10 w-10 rounded-full overflow-hidden mr-3 cursor-pointer"
                    onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                  >
                    <img
                      className={`w-full h-full object-cover ${!notification.sender?.profilePicture ? 'bg-gray-300' : ''}`}
                      src={
                        notification.sender?.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${notification.sender.profilePicture}`
                          : DefaultPicture
                      }
                      alt={notification.sender?.username || 'User'}
                    />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-200">
                      <span 
                        className="font-medium cursor-pointer hover:underline"
                        onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                      >
                        {notification.sender?.username || 'Someone'}
                      </span>{' '}
                      {getNotificationMessage(notification).replace(notification.sender?.username || 'Someone', '')}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatRelativeTime(notification.createdAt)}
                    </p>
                  </div>
                </div>
              ))}
            </>
          )}
          
          {/* This Month Section */}
          {groupedNotifications.thisMonth.length > 0 && (
            <>
              <div className="px-4 py-2 bg-[#0e0e0e] border-y border-[#222222]">
                <h2 className="text-sm font-medium text-gray-400">This Month</h2>
              </div>
              {groupedNotifications.thisMonth.map((notification, index) => (
                <div 
                  key={notification.id || `notification-month-${index}`}
                  className={`flex items-center p-4 cursor-pointer hover:bg-[#1a1a1a] transition-colorsborder-[#222222] last:border-b-0 ${
                    !notification.is_read ? 'bg-[#121212]' : 'bg-[#0a0a0a]'
                  }`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div 
                    className="h-10 w-10 rounded-full overflow-hidden mr-3 cursor-pointer"
                    onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                  >
                    <img
                      className={`w-full h-full object-cover ${!notification.sender?.profilePicture ? 'bg-gray-300' : ''}`}
                      src={
                        notification.sender?.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${notification.sender.profilePicture}`
                          : DefaultPicture
                      }
                      alt={notification.sender?.username || 'User'}
                    />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-200">
                      <span 
                        className="font-medium cursor-pointer hover:underline"
                        onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                      >
                        {notification.sender?.username || 'Someone'}
                      </span>{' '}
                      {getNotificationMessage(notification).replace(notification.sender?.username || 'Someone', '')}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatRelativeTime(notification.createdAt)}
                    </p>
                  </div>
                </div>
              ))}
            </>
          )}
          
          {/* Earlier Section */}
          {groupedNotifications.earlier.length > 0 && (
            <>
              <div className="px-4 py-2 bg-[#0e0e0e] border-b border-[#222222]">
                <h2 className="text-sm font-medium text-gray-400">Earlier</h2>
              </div>
              {groupedNotifications.earlier.map((notification, index) => (
                <div 
                  key={notification.id || `notification-earlier-${index}`}
                  className={`flex items-center p-4 cursor-pointer hover:bg-[#1a1a1a] transition-colors border-b border-[#222222] last:border-b-0 ${
                    !notification.is_read ? 'bg-[#121212]' : 'bg-[#0a0a0a]'
                  }`}
                  onClick={() => handleNotificationClick(notification)}
                >
                  <div 
                    className="h-10 w-10 rounded-full overflow-hidden mr-3 cursor-pointer"
                    onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                  >
                    <img
                      className={`w-full h-full object-cover ${!notification.sender?.profilePicture ? 'bg-gray-300' : ''}`}
                      src={
                        notification.sender?.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${notification.sender.profilePicture}`
                          : DefaultPicture
                      }
                      alt={notification.sender?.username || 'User'}
                    />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm text-gray-200">
                      <span 
                        className="font-medium cursor-pointer hover:underline"
                        onClick={(e) => navigateToSenderProfile(e, notification.sender?.username)}
                      >
                        {notification.sender?.username || 'Someone'}
                      </span>{' '}
                      {getNotificationMessage(notification).replace(notification.sender?.username || 'Someone', '')}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatRelativeTime(notification.createdAt)}
                    </p>
                  </div>
                </div>
              ))}
            </>
          )}
          
          {/* Add a dedicated loading indicator and sentinel for intersection observer */}
          {fetchLoading && (
            <div className="flex justify-center py-4">
              <div className="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-blue-500"></div>
            </div>
          )}
          
          {/* Add a dedicated sentinel element at the bottom for infinite scrolling */}
          {hasMore && !fetchLoading && (
            <div 
              ref={lastNotificationRef}
              className="py-4 text-center text-xs text-gray-500"
            >
             
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Notification;