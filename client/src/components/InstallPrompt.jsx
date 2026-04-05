import React, { useState, useEffect, useRef } from 'react';

const InstallPrompt = ({ onClose }) => {
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isVisible, setIsVisible] = useState(false);
  const promptRef = useRef(null);

  useEffect(() => {
    // Capture and prevent the default beforeinstallprompt event
    const handleBeforeInstallPrompt = (event) => {
      event.preventDefault();
      console.log('🔔 beforeinstallprompt event captured');
      setDeferredPrompt(event);
      setIsVisible(true);
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);

    // Check if we've previously dismissed the prompt in this session
    if (sessionStorage.getItem('installPromptDismissed') === 'true') {
      setIsVisible(false);
    }

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    };
  }, []);

  // Handle click outside the prompt
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (promptRef.current && !promptRef.current.contains(event.target)) {
        handleClose();
      }
    };

    if (isVisible) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('touchstart', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
    };
  }, [isVisible]);

  const handleInstall = async () => {
    if (!deferredPrompt) return;

    // Show the browser's install prompt
    deferredPrompt.prompt();

    // Wait for the user to respond
    const { outcome } = await deferredPrompt.userChoice;
    console.log(`User ${outcome} the installation prompt`);

    // Reset the deferred prompt variable
    setDeferredPrompt(null);
    setIsVisible(false);

    if (onClose) onClose();
  };

  const handleClose = () => {
    setIsVisible(false);
    // Remember that we've dismissed the prompt in this session
    sessionStorage.setItem('installPromptDismissed', 'true');
    if (onClose) onClose();
  };

  if (!isVisible) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-[999] px-4 pb-4">
      {/* Semi-transparent overlay */}
      <div 
        className="fixed inset-0 bg-black opacity-30 z-[-1]" 
        onClick={handleClose}
      />
      
      {/* Google-style prompt box */}
      <div 
        ref={promptRef}
        className="bg-[#1d1d1d] border border-gray-700 rounded-t-xl shadow-xl flex items-center p-4"
      >
        {/* App Icon */}
        <div className="mr-3 flex-shrink-0">
          <img 
            src="/scubiee2.svg" 
            alt="Scubiee Logo" 
            className="w-12 h-12"
          />
        </div>

        {/* App Info */}
        <div className="flex-grow">
          <div className="font-medium text-white">Scubiee</div>
          <div className="text-sm text-gray-400">scubiee.com</div>
        </div>

        {/* Install Button */}
        <button 
          onClick={handleInstall}
          className="ml-3 bg-primary hover:bg-primary/90 text-white px-4 py-2 rounded-md font-medium transition-colors"
        >
          Install
        </button>
      </div>
    </div>
  );
};

export default InstallPrompt;
