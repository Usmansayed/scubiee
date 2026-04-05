import { Chrome } from 'lucide-react'

import React, { useEffect } from 'react';
import axios from 'axios';

const googleLogoUrl = "/logos/google.svg"; // Path to Google SVG
const githubLogoUrl = "/logos/github.svg"; // Path to Facebook SVG
const scubieeLogoUrl = "/logos/scubiee.svg"; // Path to Scubiee Logo
const api = import.meta.env.VITE_API_URL;
const cloud = import.meta.env.VITE_CLOUD_URL;

const Registration =() => {
  const google = () => {
    window.open(`${api}/user/google`);
  };

  const facebook = () => {
    window.open(`${api}/user/github`);
  };

  useEffect(() => {
    // Check if user is already authenticated
    axios.get(`${api}/user`, { withCredentials: true })
      .then(res => {
        if (res.data && res.data.id) {
          // Instead of window.location.replace, use history.replaceState
          // This completely replaces the current history entry
          window.history.replaceState(null, '', '/');
          window.location.href = '/'; // Navigate without adding to history
        }
      })
      .catch(() => {
        // Not authenticated, do nothing
      });
  }, []);

  return (
    <div className="w-screen h-screen  dark flex flex-col items-center justify-center bg-[#0a0a0a] text-white p-4 max-md:p-3">
      {/* Logo and Welcome Section */}
      <div className="w-full md:mt-4 max-w-md flex flex-col items-center ">
      <img src={scubieeLogoUrl} alt="Scubiee Logo" className="mb-6 mt-[-110px] max-md:mt-[-160px] h-[130px] w-[260px] md:w-[280px]"  />
     {/* Tagline */}
     

      </div>

      {/* Auth Card */}
      <div className="w-full max-w-md border mt-20 shadow-sm border-zinc-800 rounded-lg bg-[#0c0c0c] backdrop-blur p-6 ">
        <div className="space-y-4 text-center mb-6">
          <h2 className="text-2xl font-semibold">Sign in to continue</h2>
          <p className="text-zinc-400 max-md:text-md text-[16px]">
            Join thousands of users who trust Scubiee for their needs
          </p>
        </div>
        <div className="space-y-6">
          <button 
            className="w-full h-12 text-base border border-zinc-800 bg-zinc-900 hover:bg-zinc-800 rounded-md flex items-center justify-center gap-2 transition-colors"
            onClick={google}
          >
            <div className='w-7 h-8  mr-3 ml-4'>
          <img
                src={googleLogoUrl}
                alt="Google logo"
               
                style={{ width: '32px', height: '32px' }} 
              />
              </div>
            Sign in with Google
          </button>

          {/* Additional Content */}
          <div className="pt-6 border-t border-zinc-800">
            <div className="grid grid-cols-3 gap-4 max-md:gap-2 text-center text-sm max-md:text-xs text-zinc-400">
              <a href="/privacy-policy" className="hover:text-white transition-colors">
                Privacy Policy
              </a>
              <a href="/terms" className="hover:text-white transition-colors">
                Terms of Service
              </a>
              <a href="/help-support" className="hover:text-white transition-colors">
                Contact
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* Trust Indicators */}
      <div className="mt-8 text-center space-y-2">
        <p className="text-sm text-zinc-400">Protected by industry standard encryption</p>
        <div className="flex justify-center gap-2">
          {[1, 2, 3].map((i) => (
            <div 
              key={i} 
              className="w-2 h-2 rounded-full bg-blue-500/50 animate-pulse"
              style={{ animationDelay: `${i * 200}ms` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

export default Registration;