import React, { useState, useEffect, useRef } from 'react';
import { FaInstagram, FaFacebook ,FaYoutube} from "react-icons/fa";
import { RiTwitterXFill } from "react-icons/ri";
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { checkAuth } from '../Slices/UserSlice';
import { useDispatch ,useSelector } from 'react-redux';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import './EditProfile.css';
import { FaPen } from "react-icons/fa";
import { fetchProfileInfo, fetchUserPosts } from '../Slices/profileSlice'; // <-- import these

const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;
const DefaultPicture = "/logos/DefaultPicture.png"; // Path to Google SVG
const DefaultCover = "/logos/DefualtCover.png"; // Path to Google SVG

const EditProfile = () => {
  const inputRef = useRef(null); 
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const userData = useSelector((state) => state.user.userData);

  // Add loading state for initial data fetch
  const [initialLoading, setInitialLoading] = useState(true);
  const [formSubmitLoading, setFormSubmitLoading] = useState(false); // New state for form submission loading

  // Add alert state
  const [alert, setAlert] = useState({
    show: false,
    message: '',
    type: 'error'
  });

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  const [userProfile, setUserProfile] = useState({
    firstName: "",
    lastName: "",
    username: "",
    bio: "",
    posts: 0,
    followers: 0,
    following: 0,
    socialLinks: {
      twitter: "",
      instagram: "",
      facebook: "",
      youtube: ""
    },
    profilePicture: "",
  });

  const [usernameAvailable, setUsernameAvailable] = useState(null);
  const [loading, setLoading] = useState(false);
  const [editingLink, setEditingLink] = useState(null);
  const [profilePicFile, setProfilePicFile] = useState(null);
  const [previewImage, setPreviewImage] = useState(DefaultPicture);
  const [coverImagePreview, setCoverImagePreview] = useState(DefaultCover);
  const [coverImageFile, setCoverImageFile] = useState(null);
  const [formSubmitAttempted, setFormSubmitAttempted] = useState(false);

  const [errors, setErrors] = useState({
    firstName: '',
    lastName: '',
    username: '',
    bio: '',
    profilePic: '',
    coverImage: ''
  });
  
  const [socialLinkErrors, setSocialLinkErrors] = useState({
    twitter: "",
    instagram: "",
    facebook: "",
    youtube: ""
  });

  useEffect(() => {
    if (userProfile && userProfile.profilePicture) {
      if (userProfile.profilePicture.startsWith("blob:")) {
        // Local file preview
        setPreviewImage(userProfile.profilePicture);
      } else {
        // Uploaded image path from server
        setPreviewImage(`${cloud}/cloudofscubiee/profilePic/${userProfile.profilePicture}`);
      }
    } else {
      setPreviewImage(DefaultPicture);
    }
  }, [userProfile]);

  // Validation
  const validateSocialUrl = (platform, url) => {
    if (!url) return true; 
    const patterns = {
      twitter: /^https?:\/\/(www\.)?twitter\.com\/[a-zA-Z0-9_]+\/?$/,
      instagram: /^https?:\/\/(www\.)?instagram\.com\/[a-zA-Z0-9_.]+\/?$/,
      facebook: /^https?:\/\/(www\.)?facebook\.com\/[a-zA-Z0-9_.]+\/?$/,
      youtube: /^https?:\/\/(www\.)?youtube\.com\/@[a-zA-Z0-9_-]+\/?$/
    };
    return patterns[platform].test(url);
  };

const validateField = (field, value) => {
  switch (field) {
    case 'firstName':
      if (value.length > 20) return 'First name must be at most 20 characters';
      break;
    case 'lastName':
      if (value.length > 20) return 'Last name must be at most 20 characters';
      break;
    case 'username':
      if (!value) return 'Username is required';
      if (value.length < 4) return 'Username must be at least 4 characters';
      if (value.length > 16) return 'Username must be at most 16 characters';
      const usernameRegex = /^[a-zA-Z0-9._]+$/;
      if (!usernameRegex.test(value)) return 'Username can only contain letters, numbers, periods, and underscores';
      break;
    case 'bio':
      if (value.length > 200) return 'Bio must be at most 200 characters';
      break;
  }
  return '';
};

  // Fetch profile data
  useEffect(() => {
    const fetchProfileData = async () => {
      setInitialLoading(true); // Set loading to true when starting fetch
      try {
        const { data } = await axios.get(`${api}/user/profile-info`, {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") },
        });

        if (data) {
          const { user, postCount, following, followers } = data;

          // Parse social links
          let parsedSocialLinks = { twitter: "", instagram: "", facebook: "", youtube: "" };
          if (user.SocialMedia && typeof user.SocialMedia === 'string') {
            try {
              const parsed = JSON.parse(user.SocialMedia);
              parsedSocialLinks = {
                twitter: parsed?.twitter || "",
                instagram: parsed?.instagram || "",
                facebook: parsed?.facebook || "",
                youtube: parsed?.youtube || ""
              };
            } catch (e) {
              console.error("Error parsing social media:", e);
            }
          }

          // Set user profile
          setUserProfile({
            firstName: user.firstName || "",
            lastName: user.lastName || "",
            username: user.username || "",
            bio: user.Bio || "",
            posts: postCount || 0,
            followers: followers?.length || 0,
            following: following?.length || 0,
            socialLinks: parsedSocialLinks,
            profilePicture: user.profilePicture || "",
            coverImage: user.coverImage || "",

          });
        }
      } catch (error) {
        console.error("Error fetching profile data:", error);
      } finally {
        // Set loading to false once data is fetched (with a slight delay for better UX)
        setTimeout(() => {
          setInitialLoading(false);
        }, 500);
      }
    };
    fetchProfileData();
  }, []);

  // Handle text inputs
  const handleInputChange = (e, field) => {
    const value = e.target.value;
    setUserProfile({ ...userProfile, [field]: value });
    setErrors({ ...errors, [field]: validateField(field, value) });
  };

  const handleUsernameChange = (e) => {
    const newUsername = e.target.value;
    setUserProfile({ ...userProfile, username: newUsername });
    
    // Validate format
    const formatError = validateField('username', newUsername);
    setErrors({ ...errors, username: formatError });
    
    // Reset availability status when username changes after a submission attempt
    if (formSubmitAttempted) {
      setUsernameAvailable(null);
    }
  };

  const handleSocialLinkChange = (e, platform) => {
    const url = e.target.value;
    setUserProfile((prev) => ({
      ...prev,
      socialLinks: { ...prev.socialLinks, [platform]: url }
    }));
    if (url && !validateSocialUrl(platform, url)) {
      setSocialLinkErrors((prev) => ({
        ...prev,
        [platform]: `Invalid ${platform} profile URL`
      }));
    } else {
      setSocialLinkErrors((prev) => ({
        ...prev,
        [platform]: ""
      }));
    }
  };

  const handleProfilePicChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const imageFile = e.target.files[0];
      
      // Check file size
      if (imageFile.size > 10 * 1024 * 1024) {
        setErrors({ ...errors, profilePic: 'Profile picture must be smaller than 10MB' });
        showAlert('Profile picture must be smaller than 10MB', 'error');
        return;
      }
      
      // Check file type
      const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png'];
      if (!allowedTypes.includes(imageFile.type)) {
        setErrors({ ...errors, profilePic: 'Only JPG, JPEG, and PNG formats are allowed' });
        showAlert('Only JPG, JPEG, and PNG formats are allowed', 'error');
        return;
      }
      
      const imageUrl = URL.createObjectURL(imageFile);
      setUserProfile({ ...userProfile, profilePicture: imageUrl });
      setProfilePicFile(imageFile);
      setErrors({ ...errors, profilePic: '' });
    }
  };

const validateFields = async () => {
  const hasErrors = Object.values(errors).some(error => error !== '');
  const hasSocialErrors = Object.values(socialLinkErrors).some(error => error !== '');
  
  if (hasErrors || hasSocialErrors) {
    window.scrollTo(0, 0);
    return false;
  }
  
  const requiredFieldErrors = {};
  if (!userProfile.username) requiredFieldErrors.username = 'Username is required';
  
  if (Object.keys(requiredFieldErrors).length > 0) {
    setErrors(prev => ({ ...prev, ...requiredFieldErrors }));
    return false;
  }
  
  setFormSubmitAttempted(true);
  setLoading(true);
  
  try {
    const { data } = await axios.get(`${api}/user/check-username`, {
      params: { username: userProfile.username },
      withCredentials: true,
    }
  
  );
    
    setUsernameAvailable(data.available);
    
    if (!data.available) {
      setErrors(prev => ({ ...prev, username: 'Username is already taken' }));
      window.scrollTo(0, 0);
      return false;
    }
    
    return true;
  } catch (error) {
    console.error('Error checking username:', error);
    setErrors(prev => ({ ...prev, username: 'Error checking username availability' }));
    window.scrollTo(0, 0);
    return false;
  } finally {
    setLoading(false);
  }
};

  const handleSaveChanges = async () => {
    // Show loading overlay immediately
    setFormSubmitLoading(true);
    
    const isValid = await validateFields();
    if (!isValid) {
      // If validation fails, hide loading overlay and return
      setFormSubmitLoading(false);
      return;
    }

    const formData = new FormData();
    formData.append('firstName', userProfile.firstName);
    formData.append('lastName', userProfile.lastName);
    formData.append('username', userProfile.username);
    formData.append('bio', userProfile.bio);
    formData.append('profilePic', profilePicFile);
    formData.append('coverImage', coverImageFile);
    formData.append('socialLinks', JSON.stringify(userProfile.socialLinks));

    try {
      const response = await axios.post(`${api}/user/edit-profile`, formData, {
        withCredentials: true,
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      if (response.data.success) {
        dispatch(checkAuth());
        dispatch(fetchProfileInfo({ forceRefresh: true }));    
            navigate(`/${userProfile.username}`);
      } else {
        // Hide loading overlay on failure
        setFormSubmitLoading(false);
        showAlert('Failed to update profile');
        console.error('Failed to update profile');
      }
    } catch (error) {
      // Hide loading overlay on error
      setFormSubmitLoading(false);
      showAlert('Error updating profile: ' + (error.response?.data?.message || error.message));
      console.error('Error updating profile:', error);
    }
  };

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (inputRef.current && !inputRef.current.contains(event.target)) {
        setEditingLink(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

const handleCoverImageChange = (e) => {
  if (e.target.files && e.target.files[0]) {
    const imageFile = e.target.files[0];
    
    // Check file size
    if (imageFile.size > 10 * 1024 * 1024) {
      setErrors({ ...errors, coverImage: 'Cover image must be smaller than 10MB' });
      showAlert('Cover image must be smaller than 10MB', 'error');
      return;
    }
    
    // Check file type
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    if (!allowedTypes.includes(imageFile.type)) {
      setErrors({ ...errors, coverImage: 'Only JPG, JPEG, and PNG formats are allowed' });
      showAlert('Only JPG, JPEG, and PNG formats are allowed', 'error');
      return;
    }
    
    const imageUrl = URL.createObjectURL(imageFile);
    setCoverImagePreview(imageUrl);
    setCoverImageFile(imageFile);
    setErrors({ ...errors, coverImage: '' });
  }
};

const showAlert = (message, type = 'error') => {
  setAlert({
    show: true,
    message,
    type
  });

  setTimeout(() => {
    setAlert({
      show: false,
      message: '',
      type: 'error'
    });
  }, 3000);
};

const handleCancel = () => {
  navigate(`/${userData.username}`);
};
  return (
    <div className="min-h-screen editprofile bg-[#0a0a0a] text-white flex flex-col items-center p-0 overflow-y-hidden relative">
      {/* Loading overlay for initial data fetch */}
      {initialLoading && (
        <div className="fixed inset-0 bg-black bg-opacity-70 z-50 flex justify-center items-center">
          <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-white"></div>
        </div>
      )}
      
      {/* New Loading overlay for form submission */}
      {formSubmitLoading && (
        <div className="fixed inset-0 bg-black bg-opacity-70 z-50 flex justify-center items-center">
          <div className="flex flex-col items-center">
            <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-white"></div>
            <p className="mt-4 text-white font-medium">Saving changes...</p>
          </div>
        </div>
      )}
      
      <div className="relative w-full h-[80%] max-w-[1250px]  flex justify-center items-center flex-col overflow-y-hidden">
      <div
  className="relative w-full h-48 bg-cover bg-center"
  style={{
    backgroundImage: `url(${
      coverImagePreview !== DefaultCover 
        ? coverImagePreview
        : userProfile.coverImage
          ? `${cloud}/cloudofscubiee/coverImages/${userProfile.coverImage}`
          : DefaultCover
    })`
  }}
>
        {/* Edit cover button */}
       <div 
               className="absolute bottom-[-15px] right-0 border-4 border-black bg-gray-100 p-[6px] rounded-full cursor-pointer"
               onClick={() => document.getElementById("coverInput").click()}
       >
         <FaPen className="text-black w-5 h-5 md:w-6 md:h-6 font-bold"/>
       </div>
        <input
          type="file"
          id="coverInput"
          className="hidden"
          accept="image/*"
          onChange={handleCoverImageChange}
        /></div>
       <div className="w-32 h-32 md:w-40 top-[-85px] md:h-40  rounded-full overflow-hidden border-4 border-zinc-300 relative">
         <img
           src={previewImage}
           className="object-cover w-full h-full bg-white"
           alt="Profile"
         />
         <input
           id="profilePic"
           type="file"
           accept="image/*"
           className="hidden"
           onChange={handleProfilePicChange}
         />
       </div>
       <div 
  className="absolute bottom-20 ml-10 transform -translate-x-[-52%] border-4 border-black bg-gray-100 p-[6px] rounded-full cursor-pointer"
  onClick={() => document.getElementById("profilePic").click()}
>
  <FaPen className="text-black w-5 h-5 font-bold"/>
</div>
     </div>

      {/* Form Section */}
      <div className=" w-full max-w-lg p-6 mt-[-70px] rounded-md space-y-4">
        <div className="flex space-x-4">
          <div className="flex-1">
            <TextField
              label="First Name"
              variant="outlined"
              value={userProfile.firstName}
              onChange={(e) => handleInputChange(e, "firstName")}
              fullWidth
              InputLabelProps={{ className: 'text-zinc-400' }}
              InputProps={{ className: 'text-white' }}
              className="custom-textfield"
              error={!!errors.firstName}
              helperText={errors.firstName && <span className="text-red-500">{errors.firstName}</span>}
            />
          </div>
          <div className="flex-1">
            <TextField
              label="Last Name"
              variant="outlined"
              value={userProfile.lastName}
              onChange={(e) => handleInputChange(e, "lastName")}
              fullWidth
              InputLabelProps={{ className: 'text-zinc-400' }}
              InputProps={{ className: 'text-white' }}
              className="custom-textfield"
              error={!!errors.lastName}
              helperText={errors.lastName && <span className="text-red-500">{errors.lastName}</span>}
            />
          </div>
        </div>

        <div className="relative">
          <TextField
            label="Username"
            variant="outlined"
            value={userProfile.username}
            onChange={handleUsernameChange}
            fullWidth
            InputLabelProps={{ className: 'text-zinc-400' }}
            InputProps={{ className: 'text-white' }}
            className="custom-textfield"
            error={!!errors.username}
            helperText={errors.username && <span className="text-red-500">{errors.username}</span>}
          />
          {loading && (
            <div className="absolute right-2 top-2">
              <svg
                className="animate-spin h-5 w-5 text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
            </div>
          )}
        </div>
        {formSubmitAttempted && usernameAvailable === true && (
          <p className="mt-2 text-sm text-green-500">
            Username is available
          </p>
        )}

        <TextField
          label="Bio"
          variant="outlined"
          value={userProfile.bio}
          onChange={(e) => handleInputChange(e, "bio")}
          fullWidth
          multiline
          rows={4}
          InputLabelProps={{ className: 'text-zinc-400' }}
          InputProps={{ className: 'text-white' }}
          className="custom-textfield"
          error={!!errors.bio}
          helperText={errors.bio && <span className="text-red-500">{errors.bio}</span>}
        />
      </div>

      {/* Social Links */}
      <div className="flex justify-center space-x-6 text-xl text-zinc-400">
        {["twitter", "instagram", "facebook", "youtube"].map((platform) => (
          <div key={platform} className="relative">
            <button
              className="hover:text-white transition-colors"
              onClick={() => setEditingLink(platform)}
            >
              {platform === "twitter" && <RiTwitterXFill />}
              {platform === "instagram" && <FaInstagram />}
              {platform === "facebook" && <FaFacebook />}
              {platform === "youtube" && <FaYoutube  className='w-6 h-6 mt-[-1px]'/>}
            </button>
            {editingLink === platform && (
              <div ref={inputRef}>
                <input
                  type="text"
                  value={userProfile.socialLinks[platform]}
                  onChange={(e) => handleSocialLinkChange(e, platform)}
                  className="absolute bg-zinc-800 text-white p-2 rounded-lg top-[-3rem] left-[-2rem] w-64 shadow-lg text-sm"
                  onBlur={() => setEditingLink(null)}
                  placeholder={`Enter ${platform} profile URL`}
                />
                {socialLinkErrors[platform] && (
                  <span className="absolute text-red-500 text-xs top-[-1rem] pt-1 left-[-2rem] w-64">
                    {socialLinkErrors[platform]}
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
<div className='flex justify-center items-center gap-3'>
      {/* Save Button */}
      <button
        className="mt-4 bg-white text-black  px-5 py-[6px] font-sans font-semibold rounded-full hover:from-gray-700 hover:to-zinc-600 focus:ring-4 focus:ring-zinc-500"
        onClick={handleCancel}
      >
        Cancel
      </button>
      <button
        className="mt-4 bg-white text-black px-5 py-[6px] font-sans font-semibold  rounded-full hover:from-gray-700 hover:to-zinc-600 focus:ring-4 focus:ring-zinc-500"
        onClick={handleSaveChanges}
      >
        Save Changes
      </button></div>
    </div>
  );
};

export default EditProfile;