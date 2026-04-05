import React, { useEffect } from "react";
import { motion } from "framer-motion";

const AboutUs = () => {
  // Smooth scroll to sections with animation
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash;
      if (hash) {
        const element = document.querySelector(hash);
        if (element) {
          element.scrollIntoView({ behavior: "smooth" });
        }
      }
    };
    
    window.addEventListener("hashchange", handleHashChange);
    handleHashChange(); // Handle hash on initial load
    
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white pb-24">
      {/* Hero Section */}
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
        className="relative overflow-hidden py-24 px-4"
      >
        <div className="absolute inset-0 z-0 opacity-20">
          <div className="absolute inset-0 bg-gradient-to-b from-blue-600/10 to-transparent"></div>
          <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-blue-500/50 to-transparent"></div>
        </div>
        
        <div className="max-w-5xl mx-auto relative z-10">
          <div className="text-center">
            <div className="inline-block p-2 px-4 rounded-full bg-blue-500/10 backdrop-blur-sm border border-blue-500/20 mb-4">
              <span className="text-blue-400 font-medium">Changing How News Travels</span>
            </div>
            <h1 className="text-5xl md:text-6xl font-bold mb-4 tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white to-gray-300">
              About Scubiee
            </h1>
            <h2 className="text-xl md:text-3xl font-medium text-blue-400 mb-8">
              A Distributive Network for Open News Sharing
            </h2>
            <div className="max-w-3xl mx-auto">
              <p className="text-xl max-md:text-lg text-gray-300 leading-relaxed mb-8">
                Creating a world where journalism thrives without constraints, 
                where information flows freely, and where every voice matters.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-4 mt-8">
              <a 
                href="#mission" 
                className="px-8 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-all transform hover:scale-105"
              >
                Our Mission
              </a>
              <a 
                href="#features" 
                className="px-8 py-3 bg-neutral-800 hover:bg-neutral-700 border border-neutral-700 rounded-lg font-medium transition-all transform hover:scale-105"
              >
                Key Features
              </a>
            </div>
          </div>
        </div>
      </motion.div>

      <div className="container max-w-5xl mx-auto px-4">
        {/* Mission section */}
        <motion.section 
          id="mission"
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.8 }}
          className="mb-20"
        >
          <div className="flex flex-col md:flex-row gap-12 items-center">
            <div className="md:w-1/2">
              <h3 className="text-2xl font-bold text-blue-400 mb-6 flex items-center">
                <span className="flex items-center justify-center w-10 h-10 bg-blue-500/20 rounded-full mr-3">📰</span>
                Our Mission
              </h3>
              <p className="text-lg leading-relaxed mb-6 text-gray-200">
                In an era overwhelmed by noise, bias, and restricted platforms, Scubiee emerges as a first-of-its-kind 
                distributive network for open news sharing, built to empower independent voices — from individuals to 
                global organizations.
              </p>
              <p className="text-lg leading-relaxed text-gray-300">
                Unlike traditional social media platforms built for entertainment, Scubiee is designed specifically for 
                news. It's a platform where journalists, citizen reporters, and organizations can communicate directly 
                with their audiences, without unnecessary barriers or censorship.
              </p>
            </div>
            <div className="md:w-1/2 relative">
              <div className="absolute inset-0 -m-4 rounded-3xl bg-gradient-to-r from-blue-600/20 to-purple-600/20 blur-xl"></div>
              <div className="flex flex-col md:flex-row gap-4 items-center relative z-10">
                <img 
                  src="/pot 0.png" 
                  alt="Scubiee Platform" 
                  className="w-full md:w-[48%] mx-auto h-auto object-cover rounded-lg border border-gray-800"
                  loading="lazy"
                  draggable={false}
                />
                <img 
                  src="/pot 1.png" 
                  alt="Scubiee Interface" 
                  className="w-full md:w-[48%] mx-auto h-auto object-cover rounded-lg border border-gray-800"
                  loading="lazy"
                  draggable={false}
                />
              </div>
            </div>
          </div>
        </motion.section>

        {/* Feature sections */}
        <div id="features" className="space-y-24 pt-8">
          <motion.section 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.8 }}
            className="flex flex-col md:flex-row gap-12 items-center"
          >
            <div className="md:w-1/2 order-2 md:order-1">
              <img 
                src="/pot 3.png" 
                alt="For journalists big and small"
                className="rounded-xl border border-gray-800 shadow-lg w-full md:w-3/5 mx-auto"
                loading="lazy"
                draggable={false}
              />
            </div>
            <div className="md:w-1/2 order-1 md:order-2">
              <div className="inline-flex items-center px-3 py-1 rounded-full bg-blue-900/30 text-blue-400 text-sm font-medium mb-4">
                <span className="mr-2">✓</span> For Every Journalist
              </div>
              <h3 className="text-2xl font-bold text-white mb-4">Built for Journalists, Big and Small</h3>
              <p className="text-lg leading-relaxed mb-4 text-gray-300">
                One of Scubiee's most groundbreaking features is its support for journalists of every scale. Whether you're a solo reporter, a small media outlet, or part of a large news organization, Scubiee gives you the tools to build a real, dedicated news channel.
              </p>
              <p className="text-lg leading-relaxed text-gray-400">
                No more creating unofficial pages or relying on platforms where your work gets buried. Scubiee offers the reach, tools, and freedom to speak the truth, stay independent, and grow your reader base — all in one place.
              </p>
            </div>
          </motion.section>

          <motion.section 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.8 }}
            className="flex flex-col md:flex-row gap-12 items-center"
          >
            <div className="md:w-1/2">
              <div className="inline-flex items-center px-3 py-1 rounded-full bg-blue-900/30 text-blue-400 text-sm font-medium mb-4">
                <span className="mr-2">✓</span> Fair & Transparent
              </div>
              <h3 className="text-2xl font-bold text-white mb-4">Open to All — Moderated With Integrity</h3>
              <p className="text-lg leading-relaxed mb-4 text-gray-300">
                Scubiee operates under a firm belief in freedom of speech. Our moderation is transparent, unbiased, and completely independent of politics, religion, race, or ideology.
              </p>
              <p className="text-lg leading-relaxed text-gray-400">
                The administrative team is not aligned with any party, belief system, or group. We maintain platform safety and fairness without amplifying one voice over another, and we never interfere with content unless it directly breaks community trust or privacy guidelines.
              </p>
            </div>
            <div className="md:w-1/2">
              <div className="relative">
                <div className="absolute inset-0 -m-4 rounded-3xl bg-gradient-to-r from-blue-600/10 to-purple-600/10 blur-xl"></div>
                <img 
                  src="/pot 4.png" 
                  alt="Open to all users" 
                  className="rounded-xl border border-gray-800 shadow-lg w-full md:w-3/5 mx-auto relative z-10"
                  loading="lazy"
                  draggable={false}
                />
              </div>
            </div>
          </motion.section>

          <motion.section 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.8 }}
            className="flex flex-col md:flex-row gap-12 items-center"
          >
            <div className="md:w-1/2 order-2 md:order-1 relative">
              <div className="absolute inset-0 -m-4 rounded-3xl bg-gradient-to-r from-blue-600/10 to-purple-600/10 blur-xl"></div>
              <img 
                src="/pot 2.png" 
                alt="Scubiee Mobile" 
                className="w-full md:w-3/5 mx-auto h-auto object-cover rounded-lg border border-gray-800 relative z-10"
                loading="lazy"
                draggable={false}
              />
            </div>
            <div className="md:w-1/2 order-1 md:order-2">
              <div className="inline-flex items-center px-3 py-1 rounded-full bg-blue-900/30 text-blue-400 text-sm font-medium mb-4">
                <span className="mr-2">✓</span> Community-Focused
              </div>
              <h3 className="text-2xl font-bold text-white mb-4">A Place for Communities and Conversations</h3>
              <p className="text-lg leading-relaxed mb-4 text-gray-300">
                Scubiee isn't just for journalists — it's for readers too. Users can follow their favorite journalists, organizations, and independent voices, and customize their own news feed to reflect their interests, values, and curiosities.
              </p>
              <p className="text-lg leading-relaxed text-gray-400">
                You don't need to scroll endlessly through distractions. On Scubiee, you only see the news you care about, from the people you trust.
              </p>
            </div>
          </motion.section>

          {/* Community Features Cards - Now in one row */}
          <motion.section 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.8 }}
            className="flex flex-col gap-6"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-neutral-800/50 border border-neutral-700/50 p-6 rounded-xl">
                <div className="flex items-center mb-3">
                  <div className="w-10 h-10 rounded-full bg-blue-800/30 flex items-center justify-center mr-3">
                    <span className="text-blue-400">👥</span>
                  </div>
                  <h4 className="text-xl font-semibold text-gray-200">Communities</h4>
                </div>
                <p className="text-gray-400">Connect with like-minded readers and follow voices you trust.</p>
              </div>
              
              <div className="bg-neutral-800/50 border border-neutral-700/50 p-6 rounded-xl">
                <div className="flex items-center mb-3">
                  <div className="w-10 h-10 rounded-full bg-blue-800/30 flex items-center justify-center mr-3">
                    <span className="text-blue-400">💬</span>
                  </div>
                  <h4 className="text-xl font-semibold text-gray-200">Conversations</h4>
                </div>
                <p className="text-gray-400">Engage in meaningful discussions about the topics that matter to you.</p>
              </div>
            </div>
          </motion.section>

          <motion.section 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.8 }}
          >
            <div className="text-center mb-12">
              <div className="inline-flex items-center px-3 py-1 rounded-full bg-blue-900/30 text-blue-400 text-sm font-medium mb-4">
                <span className="mr-2">✓</span> Coming Soon
              </div>
              <h3 className="text-2xl font-bold text-white mb-4">The "Create Paper" Feature — Personalized News Delivery</h3>
              <p className="text-lg leading-relaxed mb-4 text-gray-300 max-w-3xl mx-auto">
                What truly sets Scubiee apart is our powerful upcoming feature: Create Paper. This tool lets users design their own personalized newspaper, based on what they want to read and when.
              </p>
            </div>
            
            <div className="bg-gradient-to-b from-neutral-800/50 to-neutral-900/50 border border-neutral-700/50 rounded-xl p-6 md:p-10">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-neutral-800/50 p-6 rounded-lg border border-neutral-700/30 transform transition-all hover:scale-105">
                  <div className="w-12 h-12 rounded-full bg-blue-800/30 flex items-center justify-center mb-4">
                    <span className="text-2xl">🗞️</span>
                  </div>
                  <h4 className="text-lg font-semibold text-white mb-2">Personalized Digest</h4>
                  <p className="text-gray-400">Set your preferences once, and Scubiee will gather the most relevant stories for you.</p>
                </div>
                
                <div className="bg-neutral-800/50 p-6 rounded-lg border border-neutral-700/30 transform transition-all hover:scale-105">
                  <div className="w-12 h-12 rounded-full bg-blue-800/30 flex items-center justify-center mb-4">
                    <span className="text-2xl">⏰</span>
                  </div>
                  <h4 className="text-lg font-semibold text-white mb-2">Scheduled Delivery</h4>
                  <p className="text-gray-400">Choose when you want to receive your news - morning updates, evening digests, or weekend recaps.</p>
                </div>
                
                <div className="bg-neutral-800/50 p-6 rounded-lg border border-neutral-700/30 transform transition-all hover:scale-105">
                  <div className="w-12 h-12 rounded-full bg-blue-800/30 flex items-center justify-center mb-4">
                    <span className="text-2xl">🔍</span>
                  </div>
                  <h4 className="text-lg font-semibold text-white mb-2">Topic Selection</h4>
                  <p className="text-gray-400">Filter by categories like politics, science, tech, or local news to build your perfect paper.</p>
                </div>
              </div>
            </div>
          </motion.section>
          
          <motion.section 
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 0.8 }}
            className="text-center"
          >
            <div className="inline-flex items-center px-3 py-1 rounded-full bg-blue-900/30 text-blue-400 text-sm font-medium mb-4">
              <span className="mr-2">✓</span> Our Promise
            </div>
            <h3 className="text-2xl font-bold text-white mb-6">Trustworthy, Transparent, and Fair</h3>
            <div className="max-w-3xl mx-auto">
              <p className="text-lg leading-relaxed mb-6 text-gray-300">
                Scubiee is proudly a distributive network for open news sharing, not driven by algorithms, ad pressure, or influence from any side. We are a home for truth-seekers, fact-sharers, and curious minds.
              </p>
              <p className="text-lg leading-relaxed mb-8 text-gray-300">
                Our goal is not to become another media outlet — our goal is to empower all outlets and voices to thrive independently. We believe the future of news isn't centralized — it's connected. And Scubiee is that connection.
              </p>
              <div className="p-6 bg-blue-900/20 border border-blue-800/30 rounded-lg">
                <p className="text-xl max-md:text-lg font-medium text-white">
                  Join us in building a smarter, freer, more open world of information — where stories matter, truth spreads, and everyone has a voice.
                </p>
              </div>
              <div className="mt-12">
                <a href="/" className="inline-flex items-center px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-all transform hover:scale-105">
                  Join Scubiee Today
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 ml-2" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10.293 5.293a1 1 0 011.414 0l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414-1.414L12.586 11H5a1 1 0 110-2h7.586l-2.293-2.293a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </a>
              </div>
            </div>
          </motion.section>
        </div>
      </div>
    </div>
  );
};

export default AboutUs;
