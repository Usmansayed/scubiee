import { IoIosArrowForward } from "react-icons/io";
import { IoArrowBack } from "react-icons/io5";
import { CircleCheckBig  } from 'lucide-react';
import axios from 'axios';
import React, { useState, useRef, useEffect } from 'react';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

const categories = [
  {
    title: "Spam",
    description: "For reporting content or users involved in spammy behavior.",
    covers: [
      "Unsolicited promotional messages",
      "Repeated or irrelevant content",
      "Fake engagement (e.g., bot-like activity)"
    ]
  },
  {
    title: "Inappropriate Content",
    description: "For reporting harmful, offensive, or unsuitable content.",
    covers: [
      "Nudity or sexually explicit content",
      "Violence, graphic content, or gore",
      "Hate speech, harassment, or bullying",
      "Misinformation or fake news"
    ]
  },
  {
    title: "False Information",
    description: "For reporting misleading or fake content.",
    covers: [
      "Misinformation about events or facts",
      "Fake accounts or impersonation",
      "Fraudulent or deceptive content"
    ]
  },
  {
    title: "Scam or Fraud",
    description: "For reporting attempts to deceive users for financial or personal gain.",
    covers: [
      "Phishing links or fake giveaways",
      "Impersonation for scams",
      "Unsolicited money requests or fraud"
    ]
  },
  {
    title: "Intellectual Property Violation",
    description: "For reporting unauthorized use of copyrighted or trademarked material.",
    covers: [
      "Plagiarized content",
      "Using someone’s artwork, videos, or music without permission",
      "Trademark violations in posts or usernames"
    ]
  },
  {
    title: "Hate Speech or Abuse",
    description: "For reporting harmful interactions or content aimed at individuals or groups.",
    covers: [
      "Racism, sexism, or discrimination",
      "Targeted harassment or bullying",
      "Threatening or abusive language"
    ]
  }
];

const ReportWidget = ({onClose ,type ,targetId}) => {
  const [selectedCategory, setSelectedCategory] = useState(null);
    const [showSuccess, setShowSuccess] = useState(false);
    const widgetRef = useRef(null);

  const handleCategoryClick = (title) => {
    setSelectedCategory(title);
  };

  const handleBack = () => {
    setSelectedCategory(null);
  };

  const handleCoverClick = async (reason) => {
    try {
      await axios.post(`${api}/user-interactions/report`, {
        reporting: type,
        target_id: targetId,
        reason: reason
      }, {
        withCredentials: true,
        headers: {
          accessToken: localStorage.getItem("accessToken")
        }
      });
  
      setShowSuccess(true);
      setTimeout(() => {
        setShowSuccess(false);
        setSelectedCategory(null);
        onClose();
      }, 2400);
    } catch (error) {
      console.error('Error submitting report:', error);
    }
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (widgetRef.current && !widgetRef.current.contains(event.target)) {
        event.stopPropagation(); // Prevent bubbling to parent widgets
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);
  
  if (showSuccess) {
    return (
      <div ref={widgetRef} className="bg-[#1a1a1a]  rounded-md w-full max-w-sm text-white flex flex-col items-center justify-center min-h-[200px] border-gray-700">
        <CircleCheckBig className="w-16 h-16 text-green-500 mb-4" />
        <p className="text-center text-gray-200">
          Your report has been submitted <br /> and will be reviewed by our team.
        </p>
      </div>
    );
  }


  if (selectedCategory) {
    const category = categories.find(cat => cat.title === selectedCategory);
    return (
      <div ref={widgetRef} className="bg-[#1a1a1a] p-4 rounded-md w-full max-w-sm text-white ">
        <button 
          onClick={handleBack} 
          className="flex items-center text-sm mb-2 text-gray-400 hover:text-gray-200"
        >
          <IoArrowBack className="mr-2 ml-[-15px] mt-[-15px] text-xl " />
          <h1 className='text-lg  mt-[-16px]'>Back</h1>
        </button>
        <div className="border-b-[1px] border-gray-600 ">
        <h2 className="text-lg font-semibold mt-6">{category.title}</h2>
        <p className="text-xs text-gray-400 mb-3">{category.description}</p>
        </div>
        <div className="space-y-2 mt-4">
          {category.covers.map((reason, index) => (
            <div
              key={index}
              onClick={() => handleCoverClick(reason)}
              className="flex items-center justify-between p-2 hover:bg-[#2a2a2a] rounded-md cursor-pointer"
            >
              <p className="text-md text-gray-300">{reason}</p>
              <IoIosArrowForward className="text-gray-400" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div ref={widgetRef} className={`bg-[#1a1a1a] rounded-md w-full max-w-sm text-white ${showSuccess ? 'border-gray-600 border-2' : ''}`}>
        <div className='border-b-[1px] border-gray-600 w-full'>
      <h2 className="text-xl font-bold mb-2 ml-2 font-lato mt-0">Report</h2>
      </div>
      <div className='px-3 mt-2'>
      <div className="space-y-2">
        {categories.map(cat => (
          <p
            key={cat.title}
            className="flex items-center justify-between cursor-pointer hover:bg-[#2a2a2a] p-2 rounded-md"
            onClick={() => handleCategoryClick(cat.title)}
          >
            <div>
              <p className="text-md font-medium">{cat.title}</p>
              <p className="text-xs text-gray-400">{cat.description}</p>
            </div>
            <IoIosArrowForward />
          </p>
        ))}
      </div>
      </div>
    </div>
  );
};

export default ReportWidget;