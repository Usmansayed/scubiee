import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { FiHome, FiSearch, FiMessageCircle, FiBell, FiUser, FiPlusSquare, FiLogOut } from 'react-icons/fi';
import { HiOutlineUserGroup } from "react-icons/hi";

import { RxGrid } from "react-icons/rx";
import { BiBookContent } from "react-icons/bi";
import { BsGrid1X2 } from "react-icons/bs";
import { IoNewspaperOutline } from 'react-icons/io5';
import axios from 'axios';
import { CgFeed } from "react-icons/cg";
const api = import.meta.env.VITE_API_URL;
import { setShowWidget } from '../Slices/WidgetSlice';
import './VerticalNavbar.css';
import { useEffect, useState, useRef } from 'react';
import { FaPlus } from "react-icons/fa6";
import ReactDOM from 'react-dom';
import { Plus, FileText, Video } from "lucide-react";
import { BsPostcard,BsFilePost } from "react-icons/bs";
import { TiDocumentText } from "react-icons/ti";
import { BsLayoutTextWindow } from "react-icons/bs";
const cloud = import.meta.env.VITE_CLOUD_URL;

const VerticalNavbar = () => {
  const dispatch = useDispatch();
  const location = useLocation();
  const isHomePage = location.pathname === '/name';


  
  const hideMobileNavbar = [
    '/login', 
    '/sign-in', 
    '/complete', 
    '/edit-profile', 
    '/privacy-policy', 
    '/terms', 
    '/help-support',
    '/about-us'
  ].includes(location.pathname) || location.pathname.startsWith('/chat') || 
    location.pathname === '/create-post' || location.pathname === '/create-short';
    
  const ScubieeLogoB = "/logos/Logo121.svg";
  const Scubiee = "/logos/scubiee.svg";
  
  const hideNavbar = [
    '/sign-in', 
    '/login', 
    '/complete', 
    '/edit-profile', 
    '/privacy-policy', 
    '/terms', 
    '/help-support',
    '/about-us'

  ].includes(location.pathname);
  
  const userData = useSelector((state) => state.user.userData);
  const [windowWidth, setWindowWidth] = useState(window.innerWidth);
  const [showCreateDropdown, setShowCreateDropdown] = useState(false);
  const [showMobileDropdown, setShowMobileDropdown] = useState(false);
  const desktopDropdownRef = useRef(null);
  const desktopButtonRef = useRef(null);
  const mobileDropdownRef = useRef(null);
  const mobileButtonRef = useRef(null);
  const navigate = useNavigate();
  
  const [user, setUser] = useState(null);
  const [chatDataLoaded, setChatDataLoaded] = useState(false);
  const [validatedUnreadCount, setValidatedUnreadCount] = useState(0);
  const [isInitialRender, setIsInitialRender] = useState(true);
  
  const recentChats = useSelector(state => state.chat.recentChats);
  const unreadCount = useSelector(state => {
    const currentUserId = state.user.userData?.id;
    if (!currentUserId || !state.chat.recentChats || state.chat.recentChats.length === 0) {
      return 0;
    }


    return state.chat.recentChats.reduce((count, chat) => {
      if (
        chat.lastActivity?.type === 'message' &&
        chat.lastActivity.data.senderId !== currentUserId &&
        !chat.lastActivity.data.read
      ) {
        return count + 1;
      }
      return count;
    }, 0);
  });

  const unreadNotifications = useSelector(state => state.notification?.unreadCount || 0);

  // Also fix the next line to safely check if notification state exists:
  const notificationsLoaded = useSelector(state => state.notification?.lastFetched !== null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsInitialRender(false);
    }, 500);
    
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (isInitialRender || !recentChats || recentChats.length === 0) {
      return;
    }

    const hasValidStructure = recentChats.some(chat => 
      chat && chat.lastActivity && chat.lastActivity.data && 
      typeof chat.lastActivity.data.read !== 'undefined'
    );

    if (!hasValidStructure) {
      return;
    }
    
    const timer = setTimeout(() => {
      setChatDataLoaded(true);
    }, 0);
    
    return () => clearTimeout(timer);
  }, [recentChats, isInitialRender]);

  useEffect(() => {
    if (!chatDataLoaded || isInitialRender) {
      return;
    }
    
    setValidatedUnreadCount(prev => {
      if (unreadCount === 0) return 0;
      if (unreadCount > prev) return unreadCount;
      return prev;
    });
  }, [unreadCount, chatDataLoaded, isInitialRender]);


  useEffect(() => {
    const handleDesktopClickOutside = (event) => {
      if (
        desktopDropdownRef.current && 
        !desktopDropdownRef.current.contains(event.target) &&
        desktopButtonRef.current && 
        !desktopButtonRef.current.contains(event.target)
      ) {
        setShowCreateDropdown(false);
      }
    };

    const handleScroll = () => {
      setShowCreateDropdown(false);
    };

    const handlePopState = () => {
      setShowCreateDropdown(false);
    };

    if (showCreateDropdown) {
      document.addEventListener('mousedown', handleDesktopClickOutside);
      window.addEventListener('scroll', handleScroll, true);
      window.addEventListener('popstate', handlePopState);
    }
    
    return () => {
      document.removeEventListener('mousedown', handleDesktopClickOutside);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('popstate', handlePopState);
    };
  }, [showCreateDropdown]);

  useEffect(() => {
    const handleMobileClickOutside = (event) => {
      if (
        mobileDropdownRef.current && 
        !mobileDropdownRef.current.contains(event.target) &&
        mobileButtonRef.current && 
        !mobileButtonRef.current.contains(event.target)
      ) {
        setShowMobileDropdown(false);
      }
    };

    const handleScroll = () => {
      setShowMobileDropdown(false);
    };

    const handlePopState = () => {
      setShowMobileDropdown(false);
    };

    if (showMobileDropdown) {
      document.addEventListener('mousedown', handleMobileClickOutside);
      window.addEventListener('scroll', handleScroll, true);
      window.addEventListener('popstate', handlePopState);
    }
    
    return () => {
      document.removeEventListener('mousedown', handleMobileClickOutside);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('popstate', handlePopState);
    };
  }, [showMobileDropdown]);

  useEffect(() => {
    const handleResize = () => setWindowWidth(window.innerWidth);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const { data } = await axios.get(`${api}/search/user-check`, {
          withCredentials: true
        });
        setUser(data);
      } catch (error) {
        console.error('Auth check failed:', error);
        setUser(null);
      }
    };
    
    checkAuth();
  }, []);

  return (
    <div className="theindex">
      {!hideNavbar && (
        <div className="hidden md:flex z-[40] fixed top-0 left-0 mb-4 h-full theindex pl">
          <nav
            className={`flex flex-col h-full pb-3 bg-[#0a0a0a] text-white ${
              isHomePage ? 'navbar-expanded' : 'navbar-collapsed'
            }`}
          >
            <div className="logo-wrapper mt-5 flex justify-end sm:justify-start">
              <div className="relative w-[80%] h-14 pl-5">
                <img
                                onClick={() => navigate('/')}

                  src={ScubieeLogoB}
                  alt="Logo"
                  className={`absolute transition-all duration-500 h-10 cursor-pointer ${
                    isHomePage ? 'opacity-0 scale-0 rotate-90' : 'opacity-100 scale-100 rotate-0'
                  }`}
                />
                <img
                onClick={() => navigate('/')}
                  src={Scubiee}
                  alt="Logo"
                  className={`transition-all duration-500 cursor-pointer ${
                    isHomePage ? 'opacity-100 scale-100' : 'opacity-0 scale-0'
                  }`}
                />
              </div>
            </div>

            <div className="flex-grow flex items-center justify-center mt-[-40px]">
              <div className="text-gray-400">                <NavItem icon={<FiHome />} label="Home" to="/" isHomePage={isHomePage} />
                <NavItem icon={<TiDocumentText  className='h-[29px] w-[30px]' />} label="Feed" to="/shorts" isHomePage={isHomePage} />
          
                <NavItem icon={<FiSearch />} label="Search" to="/search" isHomePage={isHomePage} />

                <div className="nav-item-container">
                  <div ref={desktopButtonRef} onClick={() => setShowCreateDropdown(prev => !prev)} className="cursor-pointer">
                    <NavItem
                      icon={<FaPlus className="bg-[#1b1d22] h-9 w-9 p-2 rounded-lg" />}
                      label="Create"
                      to="#"
                      isHomePage={isHomePage}
                    />
                  </div>
                  {showCreateDropdown && (
                    <div
                      ref={desktopDropdownRef}
                      className="dropdown-menu text-[17px] mt-3 font-semibold space-y-2 font-sans w-[140px] bg-[#0f0f0f] border-[2px] border-[#2e2e2e] absolute left-[85%] top-1/2 transform -translate-y-1/2 ml-8 p-2 rounded-xl shadow-lg"
                    >   
                      <div
                        onClick={() => {
                          setShowCreateDropdown(false);
                          navigate("/create-post");
                        }}
                        className="flex flex-col-2 cursor-pointer gap-4 px-4 py-2 hover:bg-[#22252b] rounded-lg text-white"
                      >
                        <BsPostcard className="w-5 h-5" />
                        <span className='mt-[-3px]'>Post</span>
                      </div>
                      <div className='h-[1px] w-full mr-2 bg-gray-700'></div>
                      <div
                        onClick={() => {
                          setShowCreateDropdown(false);
                          navigate("/create-short");
                        }}
                        className="flex flex-col-2 cursor-pointer gap-4 px-4 py-2 hover:bg-[#22252b] rounded-lg text-white"
                      >
                        <TiDocumentText  className='h-[23px] w-[23px]'/>
                        <span className='mt-[-3px]'>Short</span>
                      </div>
                    </div>
                  )}
                </div>

                <div className="relative">
               
                  {chatDataLoaded && !isInitialRender && validatedUnreadCount > 0 && (
                    <div className="absolute top-[10px] right-[3px] bg-red-500 border-2 border-[#111] text-white font-semibold text-xs rounded-full h-[18px] w-[18px] flex items-center justify-center">
                      {validatedUnreadCount}
                    </div>
                  )}
                </div>
                <div className="relative">
                  <NavItem 
                    icon={<FiBell />} 
                    to="/notifications" 
                  />
                  {notificationsLoaded && unreadNotifications > 0 && (
                    <div className="absolute top-[10px] right-[3px] bg-red-500 border-2 border-[#111] text-white font-semibold text-xs rounded-full h-[18px] w-[18px] flex items-center justify-center">
                      {unreadNotifications > 9 ? '9+' : unreadNotifications}
                    </div>
                  )}
                </div>      <NavItem icon={<IoNewspaperOutline className='h-[24px] w-[23px]' />} label="Paper" to="/my-papers" isHomePage={isHomePage} />
                          <NavItem icon={<HiOutlineUserGroup className="w-[26px] h-[26px]"/>} to="/communities" />

              </div>
            </div>
            <NavItem to={userData ? `/${userData.username}` : '/sign-in'} icon={<FiUser />} />
          </nav>
        </div>
      )}

{!hideMobileNavbar && (
  <div className="md:hidden fixed left-0 w-full bg-[#0a0a0a] mb-[-20px] text-gray-400 p-0 border-t-[1px] border-[#272727] flex justify-around" style={{
    bottom: 0,
    paddingBottom: 'env(safe-area-inset-bottom, 0px)',
    height: 'var(--navbar-height, 70px)',
    zIndex: 50
  }}>          <NavItem icon={<FiHome />} to="/" />
          <NavItem icon={<TiDocumentText  className='h-[30px] w-[29px] mt-[-3px]' />} to="/shorts" />
        
          <div className="relative">
            <div ref={mobileButtonRef} onClick={() => setShowMobileDropdown(prev => !prev)} className="cursor-pointer">
              <NavItem icon={<FaPlus className="bg-[#1d2025] mt-[-6px] h-[34px] w-[34px] p-2 rounded-lg" />} to="#" />
            </div>
            {showMobileDropdown && (
              <div 
                ref={mobileDropdownRef}
                className="dropdown-menu mb-1 text-[17px] font-semibold space-y-2 font-sans w-[140px] bg-[#0f0f0f] border-[2px] border-[#2e2e2e] absolute md:left-full md:top-1/2 md:transform md:-translate-y-1/2 md:ml-8 top-auto left-1/2 -translate-x-1/2 bottom-[70px] p-2 rounded-xl shadow-lg"
              >  
                <div
                  onClick={() => {
                    setShowMobileDropdown(false);
                    navigate("/create-post");
                  }}
                  className="flex flex-col-2 cursor-pointer gap-4 px-4 py-2 hover:bg-[#22252b] rounded-lg text-white"
                >
                  <BsPostcard className="w-5 h-5" />
                  <span className='mt-[-3px]'>Post</span>
                </div>
                <div className='h-[1px] w-full mr-2 bg-[#333333]'></div>
                <div
                  onClick={() => {
                    setShowMobileDropdown(false);
                    navigate("/create-short");
                  }}
                  className="flex flex-col-2 cursor-pointer gap-4 px-4 py-2 hover:bg-[#22252b] rounded-lg text-white"
                >
                  <TiDocumentText className="w-[24px] h-[23px]" />
                  <span className='mt-[-3px]'>Short</span>
                </div>
              </div>
            )}
          </div>
          <NavItem icon={<HiOutlineUserGroup className="w-[27px] h-[27px]"/>} to="/communities" />
        
          <NavItem to={userData ? `/${userData.username}` : '/sign-in'} icon={<FiUser />} />
        </div>
      )}
    </div>
  );
};

function NavItem({ icon, label, to, isHomePage }) {
  const navigate = useNavigate();
  const location = useLocation();
  const isActive = location.pathname === to || 
                  (to === "/" && location.pathname === "") || 
                  (to !== "/" && location.pathname.startsWith(to));
  
  // Define special routes that should always replace history
  const specialRoutes = [
    '/complete',
    '/about-us',
    '/privacy-policy', 
    '/help-support',
    '/terms',
    '/create-post',
    '/create-short',
    '/create-paper'

  ];
  
  // Check if current route is a special route
  const isSpecialRoute = specialRoutes.some(route => to === route);
  
  // Check if we're currently ON a special route
  const isCurrentlyOnSpecialRoute = specialRoutes.some(route => location.pathname === route);
  
  // Check if we're navigating to the same route
  const isSameRoute = to === location.pathname;
  
  // Handle navigation with better history management
  const handleNavigation = (e) => {
    e.preventDefault();
    
    // Always replace for special routes
    if (isSpecialRoute) {
      navigate(to, { replace: true });
      return;
    }
    
    // Don't navigate if already on the page
    if (isSameRoute) {
      return;
    }
    
    // Check if we're coming from a special route - always replace history
    if (isCurrentlyOnSpecialRoute) {
      navigate(to, { replace: true });
      return;
    }
    
    try {
      // Track visited routes in a simple way - just a flat list of routes
      const visitedRoutes = JSON.parse(sessionStorage.getItem('visitedRoutes') || '[]');
      
      // We're going to:
      // 1. Check if this is a recently visited route (not the first visit)
      // 2. If yes, replace history (avoids duplicates)
      // 3. If no, navigate normally but update our tracker
      
      // Check if we've seen this route before
      const hasVisited = visitedRoutes.includes(to);
      
      if (hasVisited) {
        // We've visited this route before, so replace the current entry
        navigate(to, { replace: true });
        
        // Update the position of this route in our list (move to the end)
        const newVisited = visitedRoutes.filter(route => route !== to);
        newVisited.push(to);
        sessionStorage.setItem('visitedRoutes', JSON.stringify(newVisited));
      } else {
        // First visit to this route, navigate normally
        navigate(to);
        
        // Add to our visited routes (limited to last 10 routes)
        visitedRoutes.push(to); 
        if (visitedRoutes.length > 10) {
          visitedRoutes.shift(); // Remove oldest
        }
        sessionStorage.setItem('visitedRoutes', JSON.stringify(visitedRoutes));
      }
    } catch (e) {
      console.error('Navigation error:', e);
      navigate(to);
    }
  };
  
  return (
    <a href={to} onClick={handleNavigation}>
      <div className="flex items-center justify-center hover:text-gray-100 space-x-4 px-1 py-[15px] rounded-lg cursor-pointer">
        <div className={`text-2xl ${isActive ? 'text-white' : 'text-gray-400'}`}>{icon}</div>
        {isHomePage && (
          <span className={`hidden md:inline-block text-[17px] ${isActive ? 'text-white' : ''}`}>
            {label}
          </span>
        )}
      </div>
    </a>
  );
}
export default VerticalNavbar;