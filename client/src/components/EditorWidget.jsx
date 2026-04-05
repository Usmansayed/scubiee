import React, { useCallback, useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './EditorWidget.css';
import Widget from '../components/Widget';
import RcTiptapEditor, {
  BaseKit,
  Blockquote,
  Bold,
  BulletList,
  Code,
  CodeBlock,
  Heading,
  History,
  HorizontalRule,
  Image,
  ImageUpload,
  Video ,
    Italic,
  Link,
  OrderedList,
  SlashCommand,
  TextAlign ,
  Underline,

  Mention,
  VideoUpload,
} from 'reactjs-tiptap-editor';
import { useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { setShowWidget, setPostContent } from '../Slices/WidgetSlice';
import { FaArrowRightLong } from "react-icons/fa6";
import 'katex/dist/katex.min.css';
const cloud = import.meta.env.VITE_CLOUD_URL;

import 'reactjs-tiptap-editor/style.css';
import 'react-toastify/dist/ReactToastify.css';
import { ToastContainer, toast } from 'react-toastify';
import { BsSave2 } from "react-icons/bs";




function EditorWidget({isViewPost}) {
  const dispatch = useDispatch();

 const DEFAULT = '<p></p><p></p><p></p><p></p><p></p><p></p><p></p><p></p><p></p><p></p><p></p><p></p>'


  const [content, setContent] = useState(DEFAULT);
  const refEditor = React.useRef(null);
  const widgetRef = useRef(null); // Ref to track the widget element
  const [disable, setDisable] = useState(false);
  const [hideToolbar, setHideToolbar] = useState(window.innerWidth < 1080); // Initial state
  const showWidget = useSelector((state) => state.widget.showWidget);
  const postContent = useSelector((state) => state.widget.postContent);
  const parentId = useSelector((state) => state.widget.parentId);
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);

  const [dateTypeJson, setDateTypeJson] = useState(false);

  const navigate = useNavigate();

  console.log(isViewPost)

  const extensions = [
    BaseKit.configure({
      multiColumn: true,
      placeholder: {
        showOnlyCurrent: true,
      },
      characterCount:false,
    }),
    History,
    Heading.configure({ spacer: true , levels: [1,2,3], bubbleMenu: true}),
    Bold,
    Italic,
    Underline.configure({
      toolbar: false,
    }),
    BulletList,
    
    Link,
    Image,
    ImageUpload.configure({
      HTMLAttributes: {
        class: 'image',
      },
      upload: (file) => {
        return new Promise((resolve) => {
          setTimeout(() => {
            resolve(URL.createObjectURL(file))
          }, 500)
        })
      },
      inline: true,
      allowBase64: true,
      acceptedImageFileTypes: ['image/jpeg', 'image/png', 'image/gif']
    }),
    Video,
    VideoUpload.configure({
      upload: (files) => {
        if (typeof files === 'string') {
          return Promise.resolve({
            src: files,
            alt: 'Video URL',
          });
        } else {
          toast(
            <div>
              <p>Direct video uploads are not supported.</p>
              <p>Please use a URL from YouTube or another video hosting service.</p>
            </div>,
            {
              className: 'relative flex flex-col items-start justify-between w-full max-w-xs p-3 mb-4 bg-[#181515] text-white rounded-lg shadow-lg',
              autoClose: 3000,
              hideProgressBar: true,
            }
          );
          return Promise.reject('Upload failed: Direct video uploads are not supported.');
        }
      },
    }),
    Blockquote.configure({ spacer: true }),
    SlashCommand,
    HorizontalRule,
    Code.configure({
      toolbar: false,
    }),
    CodeBlock.configure({ defaultTheme: 'dracula' }),
    Mention,

  ];
  
  
  
  function debounce(func, wait) {
    let timeout;
    return function (...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  }

  useEffect(() => {
    const handleBeforeUnload = (event) => {
      dispatch(setPostContent(null));
    };
  
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [dispatch]);

  useEffect(() => {
    const handleResize = () => {
      // Check if the window height is less than a certain threshold (e.g., 500px)
      setIsKeyboardOpen(window.innerHeight < 500);
    };

    window.addEventListener('resize', handleResize);

    // Initial check
    handleResize();

    return () => {
      window.removeEventListener('resize', handleResize);
    };
  }, []);
  

  // Function to check screen width and update hideToolbar state
  const checkScreenWidth = () => {
    if (window.innerWidth < 1080) {
      setHideToolbar(true);
    } else {
      setHideToolbar(false);
    }
  };

  // Run on component mount and window resize
  useEffect(() => {
    checkScreenWidth(); // Initial check
    window.addEventListener('resize', checkScreenWidth); // Add resize listener

    // Cleanup listener on component unmount
    return () => {
      window.removeEventListener('resize', checkScreenWidth);
    };
  }, []);

  const onValueChange = useCallback(
    debounce((value) => {
      setContent(value);
    }, 300),
    [],
  );



  useEffect(() => {
    if (showWidget) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'auto';
    }
  }, [showWidget]);

  const handleSavePost = async () => {
    setContent(content);
    // Set output type to json to check if content is empty
    setDateTypeJson(true);
  
    // Wait for the state to update
    await new Promise(resolve => setTimeout(resolve, 0));
  
    const jsonContent = refEditor.current.editor.getJSON(); // Get the JSON content
  
    // Function to check if JSON content is empty
    const isContentEmpty = (content) => {
      if (!content || !content.content || content.content.length === 0) {
        return true;
      }
  
      return content.content.every(block => {
        if (block.type === 'paragraph' || block.type === 'heading') {
          return !block.content || block.content.length === 0 || block.content.every(textBlock => textBlock.type === 'text' && textBlock.text.trim() === '');
        }
        return false;
      });
    };
  
    if (isContentEmpty(jsonContent)) {
      toast.error('Post should have some text content', {
        className: 'relative flex items-center justify-between w-full max-w-xs p-3 mb-4 bg-[#181515] text-white rounded-lg shadow-lg',
      });
      return;
    }
  
    // Calculate character count from paragraph blocks
    const paragraphCharacterCount = jsonContent.content.reduce((count, block) => {
      if (block.type === 'paragraph' && block.content) {
        return count + block.content.reduce((innerCount, textBlock) => {
          if (textBlock.type === 'text') {
            return innerCount + textBlock.text.trim().length;
          }
          return innerCount;
        }, 0);
      }
      return count;
    }, 0);
  
    // Calculate character count from heading blocks
    const headingCharacterCount = jsonContent.content.reduce((count, block) => {
      if (block.type === 'heading' && block.content) {
        return count + block.content.reduce((innerCount, textBlock) => {
          if (textBlock.type === 'text') {
            return innerCount + textBlock.text.trim().length;
          }
          return innerCount;
        }, 0);
      }
      return count;
    }, 0);
  
    // Total character count
    const characterCount = paragraphCharacterCount + headingCharacterCount;
    // Check if there are non-text elements
    const hasNonTextElements = jsonContent.content.some(block => block.type !== 'paragraph' && block.type !== 'heading');
  
    if (characterCount < 399 && !hasNonTextElements) {
      toast(
        <div>
          <p>Post content must be at least 400 characters. Would you like to convert this into a comment?</p>
          <button
            onClick={() => {
              // Handle conversion logic here
              toast.dismiss();
            }}
            className="mt-3 p-2 rounded-lg bg-[#cccccc] fon text-black mb-[-12px]"
          >
            Convert to Comment
          </button>
        </div>,
        {
          className: 'relative flex flex-col items-start justify-between w-full max-w-xs p-3 mb-4 bg-[#181515] text-white rounded-lg shadow-lg',
        }
      );
      return;
    }
  
    try {
      const htmlContent = refEditor.current.editor.getHTML(); // Convert JSON content to HTML
      dispatch(setPostContent(htmlContent)); // Dispatch the HTML content
      console.log('Post content:', htmlContent);
      dispatch(setShowWidget(true)); // Show the widget
    } catch (error) {
      toast.error('Error creating post', {
        className: 'relative flex items-center justify-between w-full max-w-xs p-3 mb-4 bg-[#181515] text-white rounded-lg shadow-lg',
      });
      console.error('Error creating post:', error);
    }
  };

  const handleCancelPost = () => {
    navigate('/');
  };
  

  return (
<main className='bg-[#121214] rounded-xl border-gray-800 mb-3' >
    
<div className=' '>
    <div className='flex items-center  mb-[-2px] justify-between cursor-pointer ' onClick={() => toggleExpand(contribution.id)}>
                  <div className='flex items-center gap-3 mx-4 max-md:mx-2 p-3'>
                    <img
                      src="https://images.ctfassets.net/h6goo9gw1hh6/2sNZtFAWOdP1lmQ33VwRN3/24e953b920a9cd0ff2e1d587742a2472/1-intro-photo-final.jpg?w=1200&h=992&q=70&fm=webp"
                      alt={"contribution.fullName"}
                      className='w-11 h-11 rounded-full object-cover'
                    />
                    <div>
                      <h2 className='font-semibold'>Usman Sayed</h2>
                      <p className='text-sm opacity-80'>@usmansayed_ </p>
                    </div>
                  </div>
                  </div>
     <div className='  EditorWidget '>
        
        <RcTiptapEditor
          ref={refEditor}
          output={dateTypeJson ? 'json' : 'text'}
          content={content}
          onChangeContent={onValueChange}
          extensions={extensions}
          dark={true}
          disabled={disable}
          autofocus={true}
          bubbleMenu={(Heading)}
          hideBubble={true}
          
        />
      </div>
      </div>
      <ToastContainer
        position="top-center"
        autoClose={3000}
        hideProgressBar={true}
        newestOnTop={false}
        closeOnClick={true}
        rtl={false}
        pauseOnFocusLoss
        closeButton
        draggable
        pauseOnHover
        toastClassName={() =>
          'relative flex p-1 min-h-10 rounded-md justify-between overflow-hidden cursor-pointer bg-gray-950 text-white text-sm font-medium'
        }
        bodyClassName="text-sm text-gray-400  block p-1 w-full"
        style={{
          width: "fit-content",
          maxWidth: "600px"
        }}

      />
      {showWidget && (
        <div className="fixed inset-0 bg-[#070708] bg-opacity-85 z-50 flex items-center justify-center "
        style={{
           backgroundColor: 'rgba(0, 0, 0, 0.85)',
    backdropFilter: 'blur(1px)'
        }}
        >
          <div className='w-full blur-0'>
            <Widget />
          </div>
        </div>
      )}
    </main>
  );
}

export default EditorWidget;