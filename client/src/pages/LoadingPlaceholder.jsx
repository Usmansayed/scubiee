import React, { forwardRef, useEffect, useState } from 'react';
import Skeleton from 'react-loading-skeleton';
import 'react-loading-skeleton/dist/skeleton.css';

// Enhanced loading placeholder component with precise size matching and smooth transitions
const LoadingPlaceholder = forwardRef(({ visible = true, style, className = "" }, ref) => {
  const [fadeIn, setFadeIn] = useState(false);
  
  // Control fade-in animation for smoother appearance
  useEffect(() => {
    const timer = setTimeout(() => {
      setFadeIn(true);
    }, 10);
    
    return () => clearTimeout(timer);
  }, []);
  
  if (!visible) return null;
  
  return (
    <div 
      ref={ref} 
      className={`overflow-hidden md:rounded-2xl max-md:border-b-4 md:border-2 border-[#111111] md:border-[#181818] bg-[#0a0a0a] md:bg-[#0c0c0c] backdrop-blur-sm py-2 max-md:py-2 max-md:px-[4px] mb-4 transition-opacity duration-300 ${fadeIn ? 'opacity-100' : 'opacity-70'} ${className}`}      style={{
        // Important for consistent layout behavior and proper scroll position maintenance
        minHeight: '450px', 
        height: 'auto',
        // Add a slight scaling animation for smoother transitions
        transform: fadeIn ? 'scale(1)' : 'scale(0.99)',
        transition: 'opacity 0.3s ease, transform 0.3s ease',
        ...style
      }}
      data-testid="loading-placeholder"
    >
      <div className="flex items-center px-3 max-md:px-2 mb-3">
        <Skeleton circle width={40} height={40} className="mr-3" highlightColor="#333" />
        <div>
          <Skeleton width={120} height={16} className="mb-1" />
          <Skeleton width={80} height={12} />
        </div>
      </div>
      <div className="px-4 max-md:px-2">
        <Skeleton count={3} className="mb-4" />
        
        {/* Use a consistent height for the content area to ensure reliable scroll position */}
        <Skeleton height={220} className="rounded-lg mb-4" />
        
        <div className="flex">
          <Skeleton width={70} height={24} className="mr-4" />
          <Skeleton width={70} height={24} className="mr-4" />
          <Skeleton width={24} height={24} className="ml-auto mr-4" />
          <Skeleton width={24} height={24} />
        </div>
      </div>
    </div>
  );
});

LoadingPlaceholder.displayName = 'LoadingPlaceholder';

export default LoadingPlaceholder;
