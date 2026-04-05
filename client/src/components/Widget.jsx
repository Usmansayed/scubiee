import React, { useState, useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { 
  setShowWidget, 
  setPostContent, 
  setParentId,
  setFormData,
  setShowCategorySelector,
  setFormType
} from '../Slices/WidgetSlice';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
const api = import.meta.env.VITE_API_URL;
import { RiVerifiedBadgeFill } from 'react-icons/ri';
const cloud = import.meta.env.VITE_CLOUD_URL;

import './Widget.css'
import CuisineSelector from './postSelection';

const Widget = () => {
  const dispatch = useDispatch();
  const postContent = useSelector((state) => state.widget.postContent);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [thumbnail, setThumbnail] = useState(null);
  const [thumbnailUrl, setThumbnailUrl] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [showSearchBox, setShowSearchBox] = useState(false);
  const [searchType, setSearchType] = useState('');
  const [inputPosition, setInputPosition] = useState({ top: 0, left: 0 });
  const [imagesArray, setImagesArray] = useState([]);
  const [disableSubmit, setDisableSubmit] = useState(false);
  
  // Redux state
  const showWidget = useSelector((state) => state.widget.showWidget);
  const parentId = useSelector((state) => state.widget.parentId);
  const showCategorySelector = useSelector((state) => state.widget.showCategorySelector);
  const selectedCategories = useSelector((state) => state.widget.selectedCategories);
  const formData = useSelector((state) => state.widget.formData);

  useEffect(() => {
    // Cleanup function will run when component unmounts
    return () => {
      if (!showWidget) {
        // Reset local state
        setTitle('');
        setDescription('');
        setThumbnail(null);
        setThumbnailUrl(null);
        setImagesArray([]);
        setSearchTerm('');
        setSearchResults([]);
        setShowSearchBox(false);
        
        // Reset Redux state
        dispatch(setPostContent(null));
        dispatch(setParentId(null));
      }
    };
  }, [dispatch, showWidget]);

  useEffect(() => {
    // If formData exists and we're coming back to the form (not showing category selector)
    if (formData && !showCategorySelector) {
      // Restore form state from Redux
      setTitle(formData.title || '');
      setDescription(formData.description || '');
      if (formData.thumbnailUrl) {
        setThumbnailUrl(formData.thumbnailUrl);
      }
      if (formData.thumbnail) {
        setThumbnail(formData.thumbnail);
      }
    }
  }, [formData, showCategorySelector]);

  const widgetRef = useRef(null);
  const navigate = useNavigate();

  const extractTags = (text, symbol) => {
    const regex = new RegExp(`\\${symbol}[A-Za-z0-9_]+`, 'g');
    return text.match(regex) || [];
  };

  // Modified to store form data in Redux instead of submitting directly
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title || !description || !thumbnail) {
      toast.error('Please fill the Full Form');
      return;
    }

    const hashtags = extractTags(description, '#');
    const mentions = extractTags(description, '@');

    // Store form data in Redux
    const formDataObj = {
      title,
      description,
      thumbnail,
      thumbnailUrl,
      hashtags,
      mentions,
      postContent: postContent,
      parentId: parentId,
      imagesArray
    };

    dispatch(setFormData(formDataObj));
    dispatch(setFormType('post'));
    dispatch(setShowCategorySelector(true));
  };

  const handleSubmitWithCategories = async (selectedCategories) => {
    if (!formData) {
      toast.error('Form data is missing');
      return;
    }

    setDisableSubmit(true);

    const submitFormData = new FormData();
    submitFormData.append('title', formData.title);
    submitFormData.append('description', formData.description);
    submitFormData.append('thumbnail', formData.thumbnail);
    submitFormData.append('hashtags', JSON.stringify(formData.hashtags));
    submitFormData.append('mentions', JSON.stringify(formData.mentions));
    submitFormData.append('postContent', JSON.stringify(formData.postContent));
    submitFormData.append('categories', JSON.stringify(selectedCategories));
    
    if (formData.parentId) {
      submitFormData.append('parentId', formData.parentId);
    }
    
    if (formData.imagesArray && formData.imagesArray.length) {
      formData.imagesArray.forEach(imgFile => {
        submitFormData.append('postImages', imgFile);
      });
    }
    
    try {
      const response = await axios.post(`${api}/post/create-post`, submitFormData, {
        withCredentials: true,
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      toast.success('Post created successfully!');
      
      // Reset all state
      setTitle('');
      setDescription('');
      setThumbnail(null);
      setThumbnailUrl(null);
      setImagesArray([]);
      
      // Reset Redux state
      dispatch(setPostContent(null));
      dispatch(setShowWidget(false));
      dispatch(setParentId(null));
      dispatch(setFormData(null));
      dispatch(setShowCategorySelector(false));
      
      // Navigate after a short delay to let the toast show
      setTimeout(() => {
        navigate('/');
      }, 500);
      
    } catch (error) {
      toast.error('Error creating post');
      console.error('Error creating post:', error);
      setDisableSubmit(false);
    }
  };
  
  const handleImageChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const imageFile = e.target.files[0];
      const imageUrl = URL.createObjectURL(imageFile);
      setThumbnail(imageFile);
      setThumbnailUrl(imageUrl);
    }
  };

  const resetForm = () => {
    setTitle('');
    setDescription('');
    setThumbnail(null);
    setThumbnailUrl(null);
  };

  const handleInputChange = (e, inputType) => {
    const value = e.target.value;
    if (inputType === 'title') {
      setTitle(value);
    } else {
      setDescription(value);
    }

    if (inputType === 'description') {
      const cursorPosition = e.target.selectionStart;
      const textBeforeCursor = value.slice(0, cursorPosition);
      const lastSymbolIndex = Math.max(textBeforeCursor.lastIndexOf('#'), textBeforeCursor.lastIndexOf('@'));

      if (lastSymbolIndex !== -1) {
        const symbol = textBeforeCursor[lastSymbolIndex];
        const term = textBeforeCursor.slice(lastSymbolIndex + 1);

        if (term.length > 0 && /^[A-Za-z0-9_]+$/.test(term)) { // Ensure term has only valid characters
          setSearchTerm(term);
          setSearchType(symbol === '#' ? 'hashtag' : 'username');
          setShowSearchBox(true);

          const inputRect = e.target.getBoundingClientRect();
          setInputPosition({ top: inputRect.bottom, left: inputRect.left });

          search(term, symbol === '#' ? 'hashtag' : 'username');
          console.log('searching for:', term);
        } else {
          setShowSearchBox(false);
        }
      } else {
        setShowSearchBox(false);
      }
    } else {
      setShowSearchBox(false);
    }
  };

  const search = async (term, type) => {
    try {
      const response = await axios.post(`${api}/post/${type}-search`, { searchTerm: term });
      setSearchResults(response.data);
      console.log('Search results:', response.data);
    } catch (error) {
      console.error('Error fetching search results:', error);
    }
  };

  const handleCancelPost = () => {
    dispatch(setPostContent(null));
    dispatch(setShowWidget(false));
    dispatch(setFormData(null));
    dispatch(setShowCategorySelector(false));
    resetForm();
    setTimeout(() => {
      dispatch(setPostContent(null));
    }, 0);
  };

  // If showing category selector, render CuisineSelector component
  if (showCategorySelector) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white">
        <CuisineSelector onSubmitCategories={handleSubmitWithCategories} />
      </div>
    );
  }

  return postContent ? (
    <>
     <div className=" thetopwidget min-h-screen text-foreground flex items-center justify-center p-4  md:p-4 w-full z-5">
  <form ref={widgetRef} className="bg-[#0a0a0a] shadow-md rounded-lg p-4 max-md:p-2  w-full max-w-lg space-y-6" onSubmit={handleSubmit}>
    <div className='border-gray-500 border-[1px] rounded-2xl'>
        <label htmlFor="title" className="block text-[14px] ml-3 mt-2 font-medium text-primary-foreground">
          Title
          { (title.includes('#') || title.includes('@')) && (
            <span className="text-sm ml-2 font-nunito text-red-300">(title should not include #hashtags or @mentions)</span>
          )}
        </label>
      <input id="title" pattern="[^#]*"  type="text" value={title} onChange={(e) => handleInputChange(e, 'title')} className="w-full mb-2 bg-transparent text-[15px] p-2 rounded-lg bg-input focus:outline-none text-foreground" placeholder="Enter post title" />
    </div>
    <div className='border-gray-500 border-[1px] rounded-2xl'>
      <label htmlFor="description" className="block text-[14px] font-medium  ml-3 mt-2 text-primary-foreground">Description</label>
      <textarea id="description" value={description} onChange={(e) => handleInputChange(e, 'description')} rows="5" className="w-full bg-transparent focus:outline-none text-[15px] p-2 rounded-lg bg-input text-foreground" placeholder="Write your description here"></textarea>
    </div>
    <div className='border-gray-500 border-[1px] rounded-2xl'>
      <input
        id="thumbnail"
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleImageChange}
      />
       <label
       style={{ backgroundColor : '#26266e !important;' } }
        htmlFor="thumbnail" className="block  text-sm font-medium mt-2 ml-3 text-primary-foreground">Thumbnail</label>
<div className='py-2 pt-4'>
      <div
        className="  w-full [aspect-ratio:9/6] h-[180px] py-4 focus:outline-none  rounded-lg bg-input text-foreground flex items-center justify-center cursor-pointer"
        onClick={() => document.getElementById('thumbnail').click()}
        style={{
          backgroundImage: thumbnailUrl ? `url(${thumbnailUrl})` : 'none',
          backgroundSize: 'contain',
          backgroundPosition: 'center',
          backgroundRepeat: 'no-repeat',
          
        }}
      >

        {!thumbnailUrl && <span className="text-primary-foreground rounded-full bg-white/5 px-4 py-2 font-sans font-semibold">Upload Image</span>}
      </div>
    </div></div>
    <div className='grid grid-cols-2 mx-[3px] gap-3 text-black font-roboto font-medium'>
    
    <button type="button" className="w-full bg-[#c5c5c5] text-secondary-foreground py-2 rounded-xl hover:bg-[#a5a5a5]" onClick={handleCancelPost}>Cancel</button>
    <button 
      type="submit" 
      disabled={disableSubmit}
      className={`w-full ${disableSubmit ? 'bg-[#8a8a8a]' : 'bg-[#c5c5c5] hover:bg-[#a5a5a5]'} text-primary-foreground py-2 rounded-xl `}
    >
      {disableSubmit ? 'Proceeding...' : 'Next'}
    </button>
  </div>
  </form>
  {showSearchBox && (
  <div
    className="absolute bg-[#0a0a0a] border-2 border-gray-600 rounded-lg shadow-lg p-2 w-80 max-h-64 mt-2 space-y-2 overflow-y-auto"
    style={{ top: inputPosition.top, left: inputPosition.left }}
  >
    {searchResults.map((result) =>
      searchType === 'hashtag' ? (
        <div
          key={result.id}
          className="flex items-center justify-between p-2 py-1 hover:bg-[#1b1b1b] cursor-pointer "
        >
          <span className="text-white text-sm">{`#${result.name}`}</span>
          <span className="text-gray-300 text-sm">{result.Count}</span>
        </div>
      ) : (
        <div key={result.username} className="flex items-center p-2 hover:bg-[#1b1b1b] cursor-pointer">
        <img
          className="w-7 h-7 rounded-full bg-gray-300 object-cover"
       
           src={
            result.profilePicture ?
              `${cloud}/cloudofscubiee/profilePic/${result.profilePicture}` :
             "/logos/DefaultPicture.png"
            }
          alt={result.username}
        />
        <div className="ml-2 text-white text-sm flex flex-cols-2">
          {result.username}
          {result.verified ? <span><RiVerifiedBadgeFill className='text-blue-500 w-4 h-4 ml-1 mt-[1px]'/></span> : null}
        </div>
      </div>
      )
    )}
  </div>
)}
  <ToastContainer position="bottom-right" autoClose={4000} hideProgressBar={true} newestOnTop={false} closeOnClick rtl={false}
    pauseOnFocusLoss draggable pauseOnHover
    toastClassName={() =>
      'relative flex items-center justify-between w-full max-w-xs p-3 mb-4 bg-[#181515] text-white rounded-lg shadow-lg'
    } />
</div>
    </>
  ) : null;
};

export default Widget;