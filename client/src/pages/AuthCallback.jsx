import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';

const AuthCallback = () => {
  const location = useLocation();
  const [closingAttempted, setClosingAttempted] = useState(false);
  const [countdown, setCountdown] = useState(5);

  useEffect(() => {
    // Get the redirect URL from URL parameters
    const params = new URLSearchParams(location.search);
    const redirectUrl = params.get('redirectUrl') || '/';
    const status = params.get('status') || 'success';
    const error = params.get('error');
    let closeAttempts = 0;
    let messageSent = false;
    
    // Function to send message to parent window with multiple retries
    const sendMessageToParent = () => {
      if (!window.opener) return false;
      
      try {
        console.log("Sending auth message to parent window");
        
        // Send message based on status
        if (status === 'success') {
          window.opener.postMessage(
            { type: 'oauth-success', url: redirectUrl, timestamp: Date.now() },
            '*'  // Using * for better compatibility
          );
        } else {
          window.opener.postMessage(
            { type: 'oauth-failure', error: error || 'Authentication failed', timestamp: Date.now() },
            '*'
          );
        }
        
        messageSent = true;
        return true;
      } catch (err) {
        console.error('Error sending message to parent window:', err);
        return false;
      }
    };

    // Function to attempt to close the window multiple times
    const attemptCloseWindow = () => {
      closeAttempts++;
      setClosingAttempted(true);
      console.log(`Attempt ${closeAttempts} to close window`);
      
      // Always try to send the message before closing
      if (!messageSent) {
        sendMessageToParent();
      }
      
      try {
        window.close();
        
        // Schedule additional close attempts with increasing delays
        setTimeout(() => {
          if (!window.closed) {
            console.log("Window still open, trying again");
            window.close();
            
            // Last resort - redirect to blank page which might be easier to close
            if (closeAttempts >= 3 && !window.closed) {
              console.log("Final attempt: redirecting to blank page");
              window.location.href = "about:blank";
            }
          }
        }, closeAttempts * 300); // Increasing delay with each attempt
      } catch (err) {
        console.error("Error closing window:", err);
      }
    };

    // Try sending the message immediately
    sendMessageToParent();
    
    // Schedule multiple sending attempts in case the first one fails
    const messagingInterval = setInterval(() => {
      if (messageSent) {
        clearInterval(messagingInterval);
      } else {
        sendMessageToParent();
      }
    }, 500);
    
    // Start the closing sequence after a short delay to ensure message is sent
    setTimeout(() => {
      attemptCloseWindow();
      
      // Start countdown for manual closing if automatic closing fails
      const countdownInterval = setInterval(() => {
        setCountdown(prev => {
          if (prev <= 1) {
            clearInterval(countdownInterval);
            // One last closing attempt
            if (!window.closed) {
              window.close();
            }
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }, 800);
    
    // Additional attempts on document load events
    window.addEventListener('load', attemptCloseWindow);
    
    return () => {
      clearInterval(messagingInterval);
      window.removeEventListener('load', attemptCloseWindow);
    };
  }, [location]);

  // Show a simple loading screen with manual close button if automatic closing fails
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-[#0a0a0a] text-white">
      <div className="text-center p-8 max-w-md">
        <div className="mb-6">
          <div className="w-16 h-16 border-4 border-t-blue-500 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin mx-auto"></div>
        </div>
        <h1 className="text-2xl font-semibold mb-2">Authentication Complete</h1>
        <p className="text-zinc-400 mb-6">
          {!closingAttempted 
            ? "Redirecting you back to the application..." 
            : "This window should close automatically."}
        </p>
        
        {closingAttempted && (
          <>
            <p className="text-sm text-zinc-400 mb-4">
              {countdown > 0 
                ? `Window will attempt to close again in ${countdown} seconds.` 
                : "Window couldn't close automatically."}
            </p>
            <button 
              onClick={() => window.close()} 
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 transition-colors rounded text-white"
            >
              Close this window manually
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default AuthCallback;