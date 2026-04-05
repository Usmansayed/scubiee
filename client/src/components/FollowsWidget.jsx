import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { RiVerifiedBadgeFill, RiCloseLine } from 'react-icons/ri';
import Skeleton, { SkeletonTheme } from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

const FollowsWidget = ({ isOpen, onClose, userId, initialTab = 'followers', username }) => {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(0);
  const navigate = useNavigate();
  const modalRef = useRef(null);
  const observerRef = useRef(null);
  const pendingFollowOperations = useRef(new Map());
  const followLoadingStates = useRef(new Map());

  // Handle click outside to close modal
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (modalRef.current && !modalRef.current.contains(event.target)) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen, onClose]);

  // Prevent body scroll when modal is open - enhanced to fully disable scrolling
  useEffect(() => {
    if (isOpen) {
      const scrollY = window.scrollY;
      document.body.style.position = 'fixed';
      document.body.style.top = `-${scrollY}px`;
      document.body.style.width = '100%';
      document.body.style.overflow = 'hidden';
    } else {
      const scrollY = document.body.style.top;
      document.body.style.position = '';
      document.body.style.top = '';
      document.body.style.width = '';
      document.body.style.overflow = '';
      window.scrollTo(0, parseInt(scrollY || '0') * -1);
    }

    return () => {
      document.body.style.position = '';
      document.body.style.top = '';
      document.body.style.width = '';
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  // Keyboard handler for ESC key
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  // Fetch users data
  const fetchUsers = async (reset = false) => {
    try {
      if (loading) return;

      const currentPage = reset ? 0 : page;

      if (reset) {
        setUsers([]);
        setPage(0);
        setInitialLoading(true);
        setHasMore(true);
      } else {
        setLoading(true);
      }

      const { data } = await axios.get(`${api}/user/follows`, {
        withCredentials: true,
        params: {
          userId,
          username,
          fetchType: activeTab,
          page: currentPage,
          limit: currentPage === 0 ? 15 : 10,
        },
      });

      if (data.users) {
        if (reset) {
          setUsers(data.users);
        } else {
          setUsers((prev) => [...prev, ...data.users]);
        }

        setHasMore(data.hasMore);
        setPage(currentPage + 1);
      }
    } catch (error) {
      console.error('Error fetching users:', error);
    } finally {
      setLoading(false);
      setInitialLoading(false);
    }
  };

  // Initial fetch and refetch when tab changes
  useEffect(() => {
    if (isOpen && userId) {
      fetchUsers(true);
    }
  }, [isOpen, userId, activeTab]);

  // Set up intersection observer for infinite scrolling
  const lastElementRef = useCallback(
    (node) => {
      if (initialLoading || loading) return;

      if (observerRef.current) observerRef.current.disconnect();

      observerRef.current = new IntersectionObserver((entries) => {
        if (entries[0].isIntersecting && hasMore) {
          fetchUsers();
        }
      });

      if (node) observerRef.current.observe(node);
    },
    [initialLoading, loading, hasMore]
  );

  // Handle tab change
  const handleTabChange = (tab) => {
    if (tab !== activeTab) {
      setActiveTab(tab);
    }
  };

  // Navigate to user profile
  const navigateToProfile = (username) => {
    navigate(`/${username}`);
    onClose();
  };

  // Enhanced debounced handleFollowToggle
  const handleFollowToggle = async (userId, isFollowing, e) => {
    e.stopPropagation();

    if (pendingFollowOperations.current.has(userId)) {
      clearTimeout(pendingFollowOperations.current.get(userId));
    }

    followLoadingStates.current.set(userId, true);
    setUsers((prev) => [...prev]);

    setUsers((prev) =>
      prev.map((user) =>
        user.id === userId ? { ...user, followedByMe: !isFollowing } : user
      )
    );

    const timeoutId = setTimeout(async () => {
      try {
        if (isFollowing) {
          await axios.delete(`${api}/user/follow/${userId}`, {
            withCredentials: true,
          });
        } else {
          await axios.post(`${api}/user/follow/${userId}`, {}, {
            withCredentials: true,
          });
        }

        followLoadingStates.current.delete(userId);
        pendingFollowOperations.current.delete(userId);
        setUsers((prev) => [...prev]);
      } catch (error) {
        setUsers((prev) =>
          prev.map((user) =>
            user.id === userId ? { ...user, followedByMe: isFollowing } : user
          )
        );

        followLoadingStates.current.delete(userId);
        pendingFollowOperations.current.delete(userId);

        console.error('Error toggling follow status:', error);
      }
    }, 500);

    pendingFollowOperations.current.set(userId, timeoutId);
  };

  useEffect(() => {
    return () => {
      pendingFollowOperations.current.forEach((timeoutId) => {
        clearTimeout(timeoutId);
      });
    };
  }, []);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 px-4 backdrop-blur-sm">
      <div
        ref={modalRef}
        className="bg-[#111111] border border-gray-800 rounded-xl w-full max-w-[500px] min-h-[500px] max-h-[700px] md:h-auto h-[92%] flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <h3 className="text-xl font-semibold text-white">
            {activeTab === 'followers' ? 'Followers' : 'Following'}
          </h3>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-gray-800">
            <RiCloseLine size={24} className="text-gray-400 hover:text-white" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800">
          <button
            className={`flex-1 py-3 text-center font-medium text-sm ${
              activeTab === 'followers'
                ? 'text-white border-b-2 border-white'
                : 'text-gray-400 hover:text-gray-200'
            }`}
            onClick={() => handleTabChange('followers')}
          >
            Followers
          </button>
          <button
            className={`flex-1 py-3 text-center font-medium text-sm ${
              activeTab === 'following'
                ? 'text-white border-b-2 border-white'
                : 'text-gray-400 hover:text-gray-200'
            }`}
            onClick={() => handleTabChange('following')}
          >
            Following
          </button>
        </div>

        {/* User List */}
        <div className="flex-1 overflow-y-auto">
          {initialLoading ? (
            <SkeletonTheme baseColor="#333" highlightColor="#444">
              <div className="px-4 py-2">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex items-center py-2">
                    <Skeleton circle width={50} height={50} />
                    <div className="ml-3 flex-1">
                      <Skeleton width={120} height={15} />
                      <Skeleton width={80} height={12} className="mt-1" />
                    </div>
                    <Skeleton width={80} height={30} borderRadius={20} />
                  </div>
                ))}
              </div>
            </SkeletonTheme>
          ) : users.length > 0 ? (
            <div className="px-3">
              {users.map((user, index) => (
                <div
                  key={user.id}
                  ref={index === users.length - 1 ? lastElementRef : null}
                  className="flex items-center justify-between py-3 hover:bg-gray-800/30 px-2 rounded-lg cursor-pointer transition-colors"
                  onClick={() => navigateToProfile(user.username)}
                >
                  <div className="flex items-center">
                    <img
                      src={
                        user.profilePicture
                          ? `${cloud}/cloudofscubiee/profilePic/${user.profilePicture}`
                          : '/logos/DefaultPicture.png'
                      }
                      className="w-[50px] bg-gray-300 h-[50px] rounded-full object-cover border border-gray-700"
                      alt={`${user.username}'s profile`}
                    />
                    <div className="ml-3">
                      <div className="flex items-center gap-1">
                        <p className="text-white text-[15px] font-semibold">
                          {user.username}
                        </p>
                        {user.verified && (
                          <RiVerifiedBadgeFill className="text-blue-500 h-[14px] w-[14px]" />
                        )}
                      </div>
                      <p className="text-gray-400 text-sm">
                        {user.firstName} {user.lastName}
                      </p>
                      {user.mutualFollowers > 0 && (
                        <p className="text-xs text-gray-500 mt-0.5">
                          {user.mutualFollowers} mutual follower
                          {user.mutualFollowers > 1 ? 's' : ''}
                        </p>
                      )}
                    </div>
                  </div>
                  {user.isCurrentUser ? (
                    <span className="text-gray-500 text-sm px-3">You</span>
                  ) : (
                    <button
                      onClick={(e) => handleFollowToggle(user.id, user.followedByMe, e)}
                      className={`px-4 py-1.5 rounded-full text-sm font-medium min-w-[90px] flex justify-center items-center ${
                        user.followedByMe
                          ? 'border border-gray-600 text-white hover:bg-gray-700'
                          : 'bg-white text-black hover:bg-gray-200'
                      }`}
                      disabled={followLoadingStates.current.get(user.id)}
                    >
                      {followLoadingStates.current.get(user.id) ? (
                        <span
                          className={`h-4 w-4 border-2 border-t-transparent ${
                            user.followedByMe ? 'border-white' : 'border-black'
                          } border-solid rounded-full inline-block animate-spin mr-1.5`}
                        ></span>
                      ) : null}
                      {user.followedByMe ? 'Following' : 'Follow'}
                    </button>
                  )}
                </div>
              ))}
              {loading && (
                <div className="flex flex-col items-center justify-center py-4">
                  <div className="h-6 w-6 border-2 border-t-transparent border-white rounded-full animate-spin"></div>
                  <p className="text-gray-400 text-sm mt-2">Loading more users...</p>
                </div>
              )}
            </div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center py-10 text-gray-400">
              <p className="text-lg font-medium">
                No {activeTab === 'followers' ? 'followers' : 'following'} yet
              </p>
              <p className="text-sm mt-1">
                {activeTab === 'followers'
                  ? "When people follow this account, you'll see them here."
                  : "When this account follows people, you'll see them here."}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default FollowsWidget;
