import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { toast } from 'react-toastify';
import axios from 'axios';
import { 
  FiMail, FiClock, FiChevronDown, FiChevronRight, FiSend, 
  FiMapPin, FiHelpCircle, FiAlertCircle, FiUser, FiLock, FiBell
} from 'react-icons/fi';
import { BsQuestionCircle, BsShieldLock, BsHeadset } from 'react-icons/bs';
import { RiCustomerService2Line, RiQuestionAnswerLine } from 'react-icons/ri';
import { MdFeedback } from 'react-icons/md';
import { IoMdDocument } from 'react-icons/io';
import { FaTwitter, FaFacebookF, FaInstagram, FaLinkedinIn } from 'react-icons/fa';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

const HelpSupport = () => {
  const navigate = useNavigate();
  const userData = useSelector((state) => state.user.userData);
  
  // Add auth verification states
  const [authVerified, setAuthVerified] = useState(false);
  const [verifyingAuth, setVerifyingAuth] = useState(true);
  const [pendingSubmission, setPendingSubmission] = useState(false);
  
  // Add new state for unauthorized error modal
  const [showAuthModal, setShowAuthModal] = useState(false);
  
  // States for form and accordions
  const [activeSection, setActiveSection] = useState(null);
  const [formData, setFormData] = useState({
    subject: '',
    category: 'general',
    message: ''
  });
  const [formErrors, setFormErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [formSuccess, setFormSuccess] = useState(false);
  
  // Refs for scrolling to sections
  const faqRef = useRef(null);
  const contactRef = useRef(null);
  
  // Updated FAQ data organized by categories
  const faqCategories = [
    {
      id: 'account',
      icon: <FiUser className="text-gray-300" />,
      title: 'Account & Profile',
      questions: [
        {
          question: 'How do I create an account?',
          answer: 'To create an account on Scubiee, you can sign up using Google authentication by clicking the "Sign Up" button on our homepage. Once authenticated, you\'ll need to choose a unique username, provide your first and last name, and select your interests to complete your profile. We\'ll use your email from your authentication provider to set up your account.'
        },
        {
          question: 'How do I reset my password?',
          answer: 'Since Scubiee uses secure authentication through Google, there are no passwords to reset. If you\'re having trouble accessing your account, try signing in again through your authentication provider. If problems persist, please contact our support team through the form on this page.'
        },
        {
          question: 'How do I change my profile picture?',
          answer: 'To change your profile picture, go to your profile page by clicking on your username in the navigation bar, then click "Edit Profile". You\'ll find options to upload a new profile picture and cover image. We support image uploads up to 10MB in size.'
        },
        {
          question: 'Can I change my username?',
          answer: 'Yes, you can change your username through the Edit Profile page. Your username must be 4-16 characters and can only contain letters, numbers, periods, and underscores. Note that certain reserved words cannot be used as usernames. Changes to your username will be reflected across the platform immediately.'
        },
        {
          question: 'How do I add social media links to my profile?',
          answer: 'To add links to your other social media profiles, go to your profile page, click "Edit Profile", and look for the social media section where you can add links to your Instagram, Facebook, Twitter, and YouTube accounts. These will be displayed on your profile for other users to find and follow you on other platforms.'
        }
      ]
    },
    {
      id: 'content',
      icon: <RiQuestionAnswerLine className="text-gray-300" />,
      title: 'Posts & Content',
      questions: [
        {
          question: 'What types of content can I post?',
          answer: 'On Scubiee, you can create two main types of content: Posts and Shorts. For regular posts, you can share text with up to 4 images or videos per post. Videos can be up to 2 minutes in length. Shorts are a more focused format that typically include a media component and brief text. Both formats support multiple images and video content.'
        },
        {
          question: 'Why was my post removed?',
          answer: 'Posts that violate our community guidelines may be removed. This includes content that contains hate speech, harassment, explicit material, spam, misinformation, or copyright infringement. As Scubiee focuses on connecting people with journalism and news, we take content accuracy and integrity seriously. If you believe your post was removed incorrectly, you can contact our support team.'
        },
        {
          question: 'Can I edit my post after publishing?',
          answer: 'Currently, you cannot edit the media attachments of a post once published. For text content, limited editing may be available depending on the post type. If you need to make significant changes, we recommend deleting the original post and creating a new one with the correct information.'
        },
        {
          question: 'How do I delete a post?',
          answer: 'To delete a post, navigate to the post you want to remove, click the three dots (⋮) in the top right corner to open the menu, and select "Delete Post". You\'ll be asked to confirm the deletion. This action is permanent and cannot be undone, so please be certain before deleting content.'
        },
        {
          question: 'What\'s the difference between a regular post and a Short?',
          answer: 'Regular posts appear in the main feed and focus on more in-depth content with text and optional media. Shorts are optimized for mobile viewing with a stronger emphasis on visual content, similar to stories on other platforms. Shorts are displayed in a dedicated vertical scrolling feed and are great for quick updates or engaging visual content.'
        },
        {
          question: 'How do I save posts to view later?',
          answer: 'You can save any post by clicking the bookmark icon below it. Saved posts can be accessed later by navigating to your profile menu and selecting "Saved Post". This feature allows you to curate content you find interesting without having to search for it again.'
        }
      ]
    },
    {
      id: 'privacy',
      icon: <BsShieldLock className="text-gray-300" />,
      title: 'Privacy & Security',
      questions: [
        {
          question: 'Who can see my posts?',
          answer: 'By default, all posts on Scubiee are public and can be seen by any user of the platform. Your followers will see your posts in their feed, and other users can discover your content through searches or recommendations. Currently, we don\'t offer private account options, but we\'re working on additional privacy controls for future updates.'
        },
        {
          question: 'How can I control who follows me?',
          answer: 'Currently, any user can follow you on Scubiee. You\'ll receive a notification when someone new follows you. While you cannot prevent someone from following you, you can block users who you don\'t want interacting with your content or viewing your profile.'
        },
        {
          question: 'How do I block someone?',
          answer: 'To block another user, go to their profile page, click the three dots (⋮) menu, and select "Block User". When you block someone, they will no longer be able to see your posts, follow you, or interact with your content. They won\'t be notified that you\'ve blocked them.'
        },
        {
          question: 'What information is shared on my public profile?',
          answer: 'Your public profile includes your username, full name, profile picture, cover image, bio, any badges you\'ve earned, your posts count, followers count, following count, and any social media links you\'ve added. Your posts and shorts are also visible from your profile page to anyone who visits it.'
        },
        {
          question: 'Does Scubiee use my data for advertising?',
          answer: 'As Scubiee is currently in beta, we\'re focused on building a great platform rather than advertising. We collect user data primarily to improve the service and provide relevant content. Please refer to our Privacy Policy for complete details on how we collect, use, and protect your data.'
        }
      ]
    },
    {
      id: 'reports',
      icon: <FiAlertCircle className="text-gray-300" />,
      title: 'Reporting & Issues',
      questions: [
        {
          question: 'How do I report inappropriate content?',
          answer: 'To report a post, click the three dots (⋮) on the post and select "Report Post". For reporting a user, go to their profile, click the three dots menu and select "Report User". In both cases, you\'ll need to select a reason for your report and provide details. Our moderation team reviews all reports and takes appropriate action based on our community guidelines.'
        },
        {
          question: 'What happens after I report something?',
          answer: 'Our team reviews all reports promptly. The review time depends on the volume of reports and the nature of the content. Due to privacy reasons, we may not always notify you of the specific outcome, but we take all reports seriously and will remove content that violates our guidelines. Repeated violations may result in account suspension.'
        },
        {
          question: 'I found a bug in the app. How do I report it?',
          answer: 'Please report any bugs through our contact form on this page. Select "Report a Bug" in the category dropdown and provide as much detail as possible, including: steps to reproduce the issue, what you expected to happen, what actually happened, your device information, browser details, and screenshots if applicable. This helps our development team address the issue quickly.'
        },
        {
          question: 'Someone is impersonating me. What should I do?',
          answer: 'If you discover an account impersonating you or someone else, please report it immediately using the report function. Select "Impersonation" as the reason for reporting. We take impersonation very seriously as it violates our platform\'s trust and may include providing proof of your identity for verification purposes. We\'ll take appropriate action against impersonation accounts.'
        },
        {
          question: 'How do I report misinformation or fake news?',
          answer: 'Scubiee is committed to maintaining information integrity. To report misinformation, click the three dots (⋮) on the post, select "Report Post", then choose "Misinformation" as the reason. Please provide details about why you believe the content is false or misleading. Our team will review the report and may request verification from credible sources.'
        }
      ]
    },
    {
      id: 'features',
      icon: <MdFeedback className="text-gray-300" />,
      title: 'Platform Features',
      questions: [
        {
          question: 'How does the feed work on Scubiee?',
          answer: 'Your Scubiee feed displays content from users you follow, with the most recent posts appearing at the top. We may also show recommended content based on your interests and interactions. You can scroll through your feed and interact with posts through likes, comments, shares, and saves. The feed automatically loads more content as you scroll down.'
        },
        {
          question: 'How do notifications work?',
          answer: 'You\'ll receive notifications when someone follows you, likes or comments on your posts, mentions you, or sends you a direct message. Notifications appear in your notifications tab, accessible from the bell icon. A red badge indicates unread notifications. You can view and clear your notifications at any time.'
        },
        {
          question: 'What are the messaging features?',
          answer: 'Scubiee has a built-in messaging system that allows you to chat with other users privately. You can access your messages from the messages icon. The platform supports text-based conversations with other users, and shows when users are online. Unread messages are indicated by a notification badge.'
        },
        {
          question: 'Is Scubiee available as a mobile app?',
          answer: 'Currently, Scubiee is available as a web application optimized for both desktop and mobile browsers. We\'re working on dedicated mobile apps for iOS and Android, which will be released in the future. The current web version is fully responsive and provides a great experience across all devices.'
        },
        {
          question: 'What special features does Scubiee offer for journalists?',
          answer: 'Scubiee is designed to connect independent journalists and small news organizations with their audience. Journalists can receive verification badges to establish credibility, share their reporting directly with followers, and build their personal brand through consistent posting. We\'re actively developing additional tools specifically for journalists and news organizations.'
        }
      ]
    }
  ];
  
  // Verify authentication on component mount
  useEffect(() => {
    // Check if userData is already available from Redux
    if (userData !== undefined) {
      setAuthVerified(true);
      setVerifyingAuth(false);
    } else {
      // Additional check for auth token validity
      const verifyAuth = async () => {
        try {
          const response = await axios.get(`${api}/user/user`, {
            withCredentials: true
          });
          if (response.data) {
            setAuthVerified(true);
          }
        } catch (error) {
          console.log("User not authenticated:", error);
        } finally {
          setVerifyingAuth(false);
          
          // Process any pending submissions after auth verification
          if (pendingSubmission) {
            handleSubmitAfterVerification();
          }
        }
      };
      
      verifyAuth();
    }
  }, [userData]);

  // Process form submission after auth verification
  const handleSubmitAfterVerification = () => {
    setPendingSubmission(false);
    
    if (!userData && !authVerified) {
      toast.error("Please sign in to submit a support request");
      return;
    }
    
    processFormSubmission();
  };
  
  // Actual form submission logic
  const processFormSubmission = async () => {
    setSubmitting(true);
    
    try {
      const response = await axios.post(`${api}/support/submit-query`, {
        subject: formData.subject,
        category: formData.category,
        message: formData.message
      }, {
        withCredentials: true
      });
      
      if (response.data.success) {
        setFormSuccess(true);
        toast.success("Your message has been sent! We'll get back to you soon.");
        setFormData({
          subject: '',
          category: 'general',
          message: ''
        });
        
        // Reset success state after 5 seconds
        setTimeout(() => {
          setFormSuccess(false);
        }, 5000);
      } else {
        toast.error(response.data.message || "Error submitting your request");
      }
    } catch (error) {
      console.error("Error submitting support request:", error);
      
      // Check for 401 Unauthorized error
      if (error.response && error.response.status === 401) {
        // Show auth modal instead of toast
        setShowAuthModal(true);
      } else {
        toast.error(error?.response?.data?.message || "Failed to submit your request. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Toggle FAQ sections
  const toggleSection = (sectionId) => {
    if (activeSection === sectionId) {
      setActiveSection(null);
    } else {
      setActiveSection(sectionId);
    }
  };

  // Toggle individual FAQ questions
  const [expandedQuestions, setExpandedQuestions] = useState({});
  const toggleQuestion = (categoryId, index) => {
    const key = `${categoryId}-${index}`;
    setExpandedQuestions(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  // Handle form input changes
  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
    
    // Clear error when user starts typing
    if (formErrors[name]) {
      setFormErrors(prev => ({
        ...prev,
        [name]: null
      }));
    }
  };

  // Validate form before submission
  const validateForm = () => {
    const errors = {};
    
    if (!formData.subject.trim()) errors.subject = 'Subject is required';
    if (!formData.message.trim()) errors.message = 'Message is required';
    else if (formData.message.trim().length < 20) errors.message = 'Message should be at least 20 characters';
    
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  // Handle form submission
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!validateForm()) {
      return;
    }
    
    // If auth is still being verified, set pending submission
    if (verifyingAuth) {
      setPendingSubmission(true);
      return;
    }
    
    // If user is not authenticated after verification
    if (!userData && !authVerified) {
      toast.error("Please sign in to submit a support request");
      return;
    }
    
    processFormSubmission();
  };

  // Scroll to section functions
  const scrollToFAQ = () => {
    faqRef.current?.scrollIntoView({ behavior: 'smooth' });
  };
  
  const scrollToContact = () => {
    contactRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="min-h-screen text-gray-200">
      {/* Auth Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-[#111] border border-gray-700 rounded-xl p-6 max-w-md w-[90%] text-center shadow-xl animate-fade-in">
            <div className="bg-red-900/30 p-3 rounded-full w-16 h-16 mx-auto mb-4 flex items-center justify-center">
              <FiUser className="text-red-400 text-2xl" />
            </div>
            <h3 className="text-xl font-semibold mb-2">Authentication Required</h3>
            <p className="text-gray-300 mb-6">
              You need to sign in before submitting a support request so we can get back to you.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <button 
                onClick={() => navigate('/sign-in')}
                className="bg-blue-600 hover:bg-blue-700 text-white py-2.5 px-6 rounded-lg transition-colors font-medium"
              >
                Sign In
              </button>
              <button 
                onClick={() => setShowAuthModal(false)}
                className="bg-gray-700 hover:bg-gray-600 text-white py-2.5 px-6 rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hero Section */}
      <div className="py-16 px-4 sm:px-6 lg:px-8 text-center">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-4xl font-bold mb-6 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-purple-500 to-indigo-400">
            How Can We Help You?
          </h1>
          <p className="text-xl mb-8 text-gray-300">
            Find answers, get support, and share your feedback with us.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <button 
              onClick={scrollToFAQ}
              className="bg-[#222] hover:bg-[#333] text-white px-6 py-3 rounded-full font-medium flex items-center transition-all transform hover:scale-105"
            >
              <BsQuestionCircle className="mr-2" />
              Browse FAQ
            </button>
            <button 
              onClick={scrollToContact}
              className="bg-gradient-to-r from-blue-600 to-indigo-700 hover:from-blue-700 hover:to-indigo-800 text-white px-6 py-3 rounded-full font-medium flex items-center transition-all transform hover:scale-105"
            >
              <FiMail className="mr-2" />
              Contact Support
            </button>
          </div>
        </div>
      </div>

      {/* FAQ Section */}
      <div className="bg-[#080808] py-16 px-4" ref={faqRef}>
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-2">Frequently Asked Questions</h2>
          <p className="text-gray-400 text-center mb-10">Find quick answers to common questions</p>
          
          {/* Accordion style FAQ */}
          <div className="space-y-6">
            {faqCategories.map((category) => (
              <div key={category.id} className="bg-[#111] border border-gray-800 rounded-xl overflow-hidden">
                <button 
                  className="w-full px-6 py-4 flex items-center justify-between hover:bg-[#1a1a1a] transition-colors"
                  onClick={() => toggleSection(category.id)}
                >
                  <div className="flex items-center">
                    <span className="mr-3">{category.icon}</span>
                    <h3 className="text-xl font-semibold">{category.title}</h3>
                  </div>
                  {activeSection === category.id ? 
                    <FiChevronDown className="transform rotate-180 transition-transform" /> : 
                    <FiChevronDown className="transition-transform" />
                  }
                </button>
                
                {activeSection === category.id && (
                  <div className="px-6 pb-4">
                    <div className="space-y-4">
                      {category.questions.map((faq, index) => (
                        <div key={index} className="border-b border-gray-800 last:border-0 pb-4 last:pb-0">
                          <button 
                            className="w-full text-left flex items-center justify-between py-2"
                            onClick={() => toggleQuestion(category.id, index)}
                          >
                            <span className="font-medium text-gray-100">{faq.question}</span>
                            {expandedQuestions[`${category.id}-${index}`] ? 
                              <FiChevronDown className="transform rotate-180 transition-transform" /> : 
                              <FiChevronDown className="transition-transform" />
                            }
                          </button>
                          {expandedQuestions[`${category.id}-${index}`] && (
                            <div className="mt-2 text-gray-400">
                              <p>{faq.answer}</p>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
          
          <div className="text-center mt-10">
            <p className="text-gray-400 mb-4">Can't find what you're looking for?</p>
            <button 
              onClick={scrollToContact}
              className="bg-[#222] hover:bg-[#333] text-white px-5 py-2 rounded-full font-medium inline-flex items-center"
            >
              Contact Our Support Team <FiChevronRight className="ml-1" />
            </button>
          </div>
        </div>
      </div>

      {/* Contact Form Section */}
      <div className="max-w-4xl mx-auto px-4 py-16" ref={contactRef}>
        <h2 className="text-3xl font-bold text-center mb-2">Get in Touch</h2>
        <p className="text-gray-400 text-center mb-10">
          Send us a message and we'll get back to you as soon as possible
        </p>
        
        {formSuccess ? (
          <div className="bg-gradient-to-r from-blue-900/20 to-indigo-900/20 border border-blue-700/30 rounded-2xl p-8 text-center">
            <div className="w-16 h-16 bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full mx-auto mb-6 flex items-center justify-center">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h3 className="text-2xl font-semibold mb-3 text-white">Message Sent!</h3>
            <p className="text-gray-300 mb-6">
              Thank you for reaching out. Our support team will get back to you shortly.
            </p>
            <button 
              onClick={() => scrollToFAQ()}
              className="bg-blue-700 hover:bg-blue-800 text-white px-6 py-2.5 rounded-full transition-colors"
            >
              Browse FAQ While You Wait
            </button>
          </div>
        ) : (
          <div className="bg-gradient-to-br from-[#111] to-[#0c0c0c] border border-gray-800 rounded-2xl p-6 md:p-8 shadow-xl">
            {/* Only show sign-in alert after auth verification is complete and user is not authenticated */}
            {!verifyingAuth && !userData && !authVerified && (
              <div className="mb-6 bg-yellow-900/20 border border-yellow-700/30 rounded-xl p-4 text-yellow-200">
                <p className="flex items-center">
                  <FiAlertCircle className="mr-2 flex-shrink-0" />
                  <span>Please <a href="/sign-in" className="underline font-medium">sign in</a> to send a support request so we can respond to you.</span>
                </p>
              </div>
            )}
            
            {/* Show loading indicator when verifying auth */}
            {verifyingAuth && (
              <div className="mb-6 bg-blue-900/20 border border-blue-700/30 rounded-xl p-4 text-blue-200">
                <p className="flex items-center">
                  <div className="mr-2 w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"></div>
                  <span>Verifying your account...</span>
                </p>
              </div>
            )}
            
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label htmlFor="subject" className="block text-gray-300 mb-2 font-medium">Subject</label>
                  <input 
                    type="text" 
                    id="subject" 
                    name="subject" 
                    value={formData.subject} 
                    onChange={handleInputChange}
                    className={`w-full bg-[#1a1a1a] border ${formErrors.subject ? 'border-red-500' : 'border-gray-700'} rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all`} 
                    placeholder="How can we help you?" 
                  />
                  {formErrors.subject && <p className="text-red-500 text-sm mt-1">{formErrors.subject}</p>}
                </div>
                
                <div>
                  <label htmlFor="category" className="block text-gray-300 mb-2 font-medium">Category</label>
                  <select 
                    id="category" 
                    name="category" 
                    value={formData.category} 
                    onChange={handleInputChange}
                    className="w-full bg-[#1a1a1a] border border-gray-700 rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all appearance-none"
                    style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%236b7280'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E\")", backgroundRepeat: 'no-repeat', backgroundPosition: 'right 1rem center', backgroundSize: '1.5em 1.5em' }}
                  >
                    <option value="general">General Inquiry</option>
                    <option value="technical">Technical Support</option>
                    <option value="account">Account Issues</option>
                    <option value="bug">Report a Bug</option>
                    <option value="feedback">Feedback & Suggestions</option>
                    <option value="privacy">Privacy Concern</option>
                    <option value="other">Other</option>
                  </select>
                </div>
              </div>
              
              <div>
                <label htmlFor="message" className="block text-gray-300 mb-2 font-medium">Message</label>
                <textarea 
                  id="message" 
                  name="message" 
                  value={formData.message} 
                  onChange={handleInputChange}
                  className={`w-full bg-[#1a1a1a] border ${formErrors.message ? 'border-red-500' : 'border-gray-700'} rounded-xl px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 min-h-[150px] transition-all`} 
                  placeholder="Please provide as much detail as possible so we can help you better."
                ></textarea>
                {formErrors.message && <p className="text-red-500 text-sm mt-1">{formErrors.message}</p>}
              </div>
              
              <div className="flex justify-center pt-4">
                <button 
                  type="submit" 
                  className={`bg-gradient-to-r from-blue-600 to-indigo-700 hover:from-blue-700 hover:to-indigo-800 text-white px-8 py-3.5 rounded-xl font-medium flex items-center justify-center min-w-[180px] shadow-lg shadow-blue-900/20 disabled:opacity-70 disabled:cursor-not-allowed transition-all transform hover:scale-105`}
                  disabled={submitting || (verifyingAuth && pendingSubmission)}
                >
                  {submitting || (verifyingAuth && pendingSubmission) ? (
                    <>
                      <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                      {verifyingAuth ? 'Verifying...' : 'Processing...'}
                    </>
                  ) : (
                    <>
                      <FiSend className="mr-2" />
                      Submit Request
                    </>
                  )}
                </button>
              </div>
              
              {userData && (
                <div className="text-center text-gray-400 text-sm mt-3">
                  <p>We'll respond to your message at <span className="text-blue-400">{userData.email}</span></p>
                </div>
              )}
            </form>
          </div>
        )}
      </div>

      {/* Additional Information */}
      <div className="bg-[#080808] py-16 px-4">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Response Time */}
            <div className="bg-[#111] border border-gray-800 rounded-xl p-6 transition-all flex items-start">
              <div className="w-12 h-12 rounded-full bg-blue-900/30 flex items-center justify-center mr-4 shrink-0">
                <FiClock className="text-blue-400 text-xl" />
              </div>
              <div>
                <h3 className="text-lg font-semibold mb-2">Response Time</h3>
                <p className="text-gray-400">We typically respond to all inquiries within 24-48 hours during business days.</p>
              </div>
            </div>
            
            {/* Business Hours */}
            <div className="bg-[#111] border border-gray-800 rounded-xl p-6 transition-all flex items-start">
              <div className="w-12 h-12 rounded-full bg-purple-900/30 flex items-center justify-center mr-4 shrink-0">
                <FiHelpCircle className="text-purple-400 text-xl" />
              </div>
              <div>
                <h3 className="text-lg font-semibold mb-2">Business Hours</h3>
                <p className="text-gray-400">Our support team is available Monday to Saturday, 9:00 AM - 6:00 PM IST.</p>
              </div>
            </div>
            
            {/* Location */}
            <div className="bg-[#111] border border-gray-800 rounded-xl p-6 transition-all flex items-start">
              <div className="w-12 h-12 rounded-full bg-green-900/30 flex items-center justify-center mr-4 shrink-0">
                <FiMapPin className="text-green-400 text-xl" />
              </div>
              <div>
                <h3 className="text-lg font-semibold mb-2">Location</h3>
                <p className="text-gray-400">Based in Belagavi, Karnataka with team members working remotely across the globe.</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer Links */}
      <div className="max-w-4xl mx-auto px-4 py-12 text-center">
        <h3 className="text-xl font-semibold mb-6">Connect With Us</h3>
        
        <div className="flex justify-center space-x-4 mb-8">
          <a href="https://x.com/scubiee_inc" className="w-10 h-10 rounded-full bg-[#1a1a1a] border border-gray-800 flex items-center justify-center text-blue-400 hover:bg-blue-900/20 hover:border-blue-800/60 transition-all">
            <FaTwitter />
          </a>
          <a href="https://www.facebook.com/profile.php?id=61575250615574" className="w-10 h-10 rounded-full bg-[#1a1a1a] border border-gray-800 flex items-center justify-center text-blue-500 hover:bg-blue-900/20 hover:border-blue-800/60 transition-all">
            <FaFacebookF />
          </a>
          <a href="https://www.instagram.com/scubiee.inc" className="w-10 h-10 rounded-full bg-[#1a1a1a] border border-gray-800 flex items-center justify-center text-pink-500 hover:bg-pink-900/20 hover:border-pink-800/60 transition-all">
            <FaInstagram />
          </a>
         
        </div>
        
        <div className="flex flex-wrap justify-center gap-4 text-gray-400">
          <a href="/terms" className="hover:text-blue-400 transition-colors flex items-center">
            <IoMdDocument className="mr-1" /> Terms of Service
          </a>
          <span>•</span>
          <a href="/privacy-policy" className="hover:text-blue-400 transition-colors flex items-center">
            <BsShieldLock className="mr-1" /> Privacy Policy
          </a>
          <span>•</span>
          <a href="#" className="hover:text-blue-400 transition-colors flex items-center">
            <FiBell className="/privacy-policy" /> Cookie Policy
          </a>
        </div>
      </div>
    </div>
  );
};

export default HelpSupport;
