import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';

const NewUserCallback = () => {
  const location = useLocation();
  const [closingAttempted, setClosingAttempted] = useState(false);
  const [countdown, setCountdown] = useState(5);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const redirectUrl = params.get('redirectUrl') || '/complete';
    const isFirstTimeUser = params.get('isFirstTimeUser') === 'true';
    let closeAttempts = 0;
    let messageSent = false;

    const sendMessageToParent = () => {
      if (!window.opener) return false;
      try {
        window.opener.postMessage(
          { type: 'oauth-new-user', url: redirectUrl, isFirstTimeUser: true, timestamp: Date.now() },
          '*'
        );
        messageSent = true;
        return true;
      } catch {
        return false;
      }
    };

    const attemptCloseWindow = () => {
      closeAttempts++;
      setClosingAttempted(true);
      if (!messageSent) sendMessageToParent();
      try {
        window.close();
        setTimeout(() => {
          if (!window.closed) {
            window.close();
            if (closeAttempts >= 3 && !window.closed) {
              window.location.href = 'about:blank';
            }
          }
        }, closeAttempts * 300);
      } catch {}
    };

    sendMessageToParent();
    const messagingInterval = setInterval(() => {
      if (messageSent) clearInterval(messagingInterval);
      else sendMessageToParent();
    }, 500);

    setTimeout(() => {
      attemptCloseWindow();
      const countdownInterval = setInterval(() => {
        setCountdown(prev => {
          if (prev <= 1) {
            clearInterval(countdownInterval);
            if (!window.closed) window.close();
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }, 800);

    window.addEventListener('load', attemptCloseWindow);

    return () => {
      clearInterval(messagingInterval);
      window.removeEventListener('load', attemptCloseWindow);
    };
  }, [location]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-[#0a0a0a] text-white">
      <div className="text-center p-8 max-w-md">
        <div className="mb-6">
          <div className="w-16 h-16 border-4 border-t-blue-500 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin mx-auto"></div>
        </div>
        <h1 className="text-2xl font-semibold mb-2">Welcome to Scubiee!</h1>
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

export default NewUserCallback;