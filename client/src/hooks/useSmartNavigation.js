import { useNavigate, useLocation } from 'react-router-dom';
import { useRef, useEffect } from 'react';

/**
 * Custom hook for smarter navigation that prevents excessive history buildup
 * when navigating between primary app pages
 */
export default function useSmartNavigation() {
  const navigate = useNavigate();
  const location = useLocation();
  
  // Only include the main navigation destinations here
  // Creation routes like /create-post and /create-short should NOT be here
  // because users expect the back button to work normally after content creation
  const mainRoutes = ['/shorts', '/', '/search', '/notifications', '/chat'];
  
  // Secondary routes that might be navigated to from main routes but should keep normal history
  const contentCreationRoutes = ['/create-post', '/create-short'];
  
  const visitedRoutesRef = useRef(new Set());
  
  // Track current path in history
  useEffect(() => {
    visitedRoutesRef.current.add(location.pathname);
  }, [location.pathname]);

  // Smart navigation function
  const smartNavigate = (to, options = {}) => {
    // If navigating to a main route that's already been visited, replace history
    if (mainRoutes.includes(to) && visitedRoutesRef.current.has(to)) {
      navigate(to, { ...options, replace: true });
      console.log(`Smart navigation: Replacing history with ${to}`);
    } else {
      // For first visits, non-main routes, or content creation routes, use normal navigation
      navigate(to, options);
      console.log(`Smart navigation: Adding ${to} to history`);
    }
    
    // Special handling for content creation routes - we want back button to work normally
    if (contentCreationRoutes.includes(to)) {
      console.log(`Content creation route: ensuring normal back button behavior for ${to}`);
    }
  };

  return { smartNavigate };
}
