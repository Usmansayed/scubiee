import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
const cloud = import.meta.env.VITE_CLOUD_URL;

const ScrollToTop = () => {
  const { pathname } = useLocation();

  useEffect(() => {
    // Only scroll to top if not on Home page ("/")
    if (pathname === "/") return;
    window.scrollTo(0, 0);
  }, [pathname]);

  return null; // This component doesn't render anything
};

export default ScrollToTop;
