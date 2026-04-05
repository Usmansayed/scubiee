import React, { useState, useEffect } from 'react';

const NetworkIssue = ({ onRetry }) => {
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  
  // Keep track of online status
  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);
  
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
      width: '100vw',
      background: '#0a0a0a'
    }}>
      {/* Using the provided SVG warning icon */}
      <div style={{
        marginBottom: '16px',
        color: '#ff4655' // Red color
      }}>
        <svg xmlns="http://www.w3.org/2000/svg" 
             style={{ width: '64px', height: '64px' }} 
             fill="none" 
             viewBox="0 0 24 24" 
             stroke="currentColor">
          <path strokeLinecap="round" 
                strokeLinejoin="round" 
                strokeWidth={2} 
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>
      
      {/* Error Message */}
      <h3 style={{ 
        fontSize: '18px', 
        fontWeight: '600',
        color: 'white',
        margin: '0 0 8px 0'
      }}>
        Network Error
      </h3>
      
      <p style={{ 
        fontSize: '14px', 
        color: '#aaa',
        margin: '0 0 24px 0',
        maxWidth: '300px',
        textAlign: 'center'
      }}>
        {isOnline ? 
          "Unable to reach our servers. Please try again." : 
          "Please check your internet connection."}
      </p>
      
      {/* Retry Button */}
      <button 
        onClick={onRetry}
        style={{
          backgroundColor: 'white',
          color: '#0a0a0a',
          border: 'none',
          borderRadius: '20px',
          padding: '8px 24px',
          fontSize: '14px',
          fontWeight: '600',
          cursor: 'pointer',
          transition: 'all 0.2s',
          outline: 'none'
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.transform = 'scale(1.05)';
          e.currentTarget.style.boxShadow = '0 0 10px rgba(255,255,255,0.2)';
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.transform = 'scale(1)';
          e.currentTarget.style.boxShadow = 'none';
        }}
      >
        Retry
      </button>
    </div>
  );
};

export default NetworkIssue;
