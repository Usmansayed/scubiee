import React, { useCallback, useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './MEditorWidget.css';
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
const cloud = import.meta.env.VITE_CLOUD_URL;

import 'katex/dist/katex.min.css';

import 'reactjs-tiptap-editor/style.css';
import 'react-toastify/dist/ReactToastify.css';
import { ToastContainer, toast } from 'react-toastify';
import { BsSave2 } from "react-icons/bs";
import { use } from 'react';




function MEditor({isViewPost}) {
  const dispatch = useDispatch();

 const DEFAULT = ''

 const [initialHeight] = useState(window.innerHeight);

  const [content, setContent] = useState(DEFAULT);
  const refEditor = React.useRef(null);
  const widgetRef = useRef(null); // Ref to track the widget element
  const [disable, setDisable] = useState(false);
  const [hideToolbar, setHideToolbar] = useState(window.innerWidth < 1080); // Initial state
  const showWidget = useSelector((state) => state.widget.showWidget);
  const postContent = useSelector((state) => state.widget.postContent);
  const parentId = useSelector((state) => state.widget.parentId);
  const [isKeyboardOpen, setIsKeyboardOpen] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [dateTypeJson, setDateTypeJson] = useState(false);
  const parentRef = useRef(null);
  const [childHeight, setChildHeight] = useState(0);

  console.log(isViewPost)

  const navigate = useNavigate();

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
  
    useEffect(() => {
      if (parentRef.current) {
        setChildHeight(parentRef.current.offsetHeight);
      }
    }, [showPreview, window.innerWidth]);
    
  
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
  useEffect(() => {
    // Wait for editor to be ready
    setTimeout(() => {
      if (refEditor.current && refEditor.current.editor) {
        refEditor.current.editor.commands.focus('start');
      }
    }, 100);
  }, []); // Run once on mount

const style = document.createElement('style');
style.textContent = `
   .MEditor .tiptap.ProseMirror {
      height: ${window.innerWidth < 788 ? childHeight - 80 : childHeight - 50}px; 
    }
       .MEditor .richtext-flex.richtext-flex-col.richtext-w-full.richtext-max-h-full {
      height: ${childHeight}px;
  
}
`;

document.head.appendChild(style);



return (
<main
  id="thecreateone"
  className={`h-fit overflow-y-hidden w-full max-lg:border-none hideNavbar ...`}
>   {showPreview ? (<div className="  mt-4 gap-4 mb-4 flex justify-center items-center ">
    <div className="relative ">
 
         
         <button 
           onClick={()=>{setShowPreview(false)}} 
           className="py-2 px-4 rounded-xl bg-[#15151d] text-white font-semibold"
         >
           Write
         </button>
         {!showPreview && (
           <div className="absolute flex justify-center w-[60%] bottom-2  left-[13px] top-12 mb-[-2px] h-[3px] bg-gray-400 transition-all duration-200"/>
         )}
       </div>
       
       <div className="relative">
         <button 
           onClick={()=>{setShowPreview(true)}} 
           className="py-2 px-4 rounded-xl bg-[#15151d] text-white font-semibold"
         >
           Preview
         </button>
         {showPreview && (
           <div className="absolute   w-[60%] bottom-2  left-[18px]  top-12   h-[3px] bg-gray-400 transition-all duration-200"/>
         )}
       </div>
       <button 
   onClick={() => setShowPreview(false)} 
   className="py-2 px-4 rounded-xl bg-[#15151d] text-white font-semibold flex items-center justify-center" 
 >
   
   Publish<FaArrowRightLong className="ml-2" /> 
 </button>
    
   </div>) : null}
 
         <div className="thetopone  text-[16px] flex justify-end  max-sm:mt-4     bg-transparent    w-[80%] sm:max-w-[90%] max-xl:w-[90%] max-lg:w-full xl:w-[85%] max-lg:fixed
       max-md:top-0 max-md:left-1 ">
 
   { window.innerWidth > 1400 && (
   <div
     className={`w-fit thetopone fixed bg-black   ${
       showWidget ? "hidden" : "none"
      } flex md:space-x-0 border-[#b4b4b4] max-lg:border-none  border-[2px] lg:text-[18px] max-lg:border-[1px] max-lg:bottom-8 lg:top-4 right-10 max-md:bottom-16 bg-gray-black text-black backdrop-blur-xl rounded-xl `}
      >
 
   
       <button
         className=" p-[6px] max-lg:bg-[#15151d]  font-sans rounded-[11px] flex items-center  hover:bg-gray-300 hover:text-black bg-[#0a0a0a] text-gray-300"
        onClick={handleSavePost} 
       >
         Publish
         <FaArrowRightLong className="ml-2" />
       </button> 
     </div>)}
 </div>
 <div>
  
 <div  className=' hideNavbar scrollbar-hide max-md:border-b-2  border-[#242323]'>
 <div 
   className={`max-w-[900px] md:mt-4 max-lg:max-w-[670px] max-md:max-w-full h-fit scrollbar-hide  rounded-lg   max-md:w-full md:mx-auto  relative xl:right-[10px] MEditor`}
   ref={parentRef}

   style={
     window.innerWidth < 12060
       ? showPreview
         ? {
             height: '100vh',
            
           }
         :{
           height:
             window.innerWidth > 1500
               ? '95vh'
               : window.innerWidth > 768
               ? '62vh'
               : '54vh',
         }
       : {}
   }
 >
   <RcTiptapEditor
     ref={refEditor}
     output={dateTypeJson ? 'json' : 'text'} 
     content={content}
     onChangeContent={onValueChange}
     extensions={extensions}
     dark={true}
     autofocus={true}
     hideBubble={true}
    
     disabled={showPreview}
     hideToolbar={showPreview}
     style={{ height: '100%' }}
   />
 </div>
       </div>
 
       
       {!showPreview && window.innerWidth < 1400 ? (   
    <div className="flex mt-12 gap-4 mb-4 justify-center items-center">
      <div className="relative">
        <button 
          onClick={()=>{setShowPreview(false)}} 
          className="py-2 px-4 rounded-xl bg-[#15151d] text-white font-semibold"
        >
          Write
        </button>
        {!showPreview && (
          <div className="absolute flex justify-center w-[60%] bottom-2  left-[13px] top-12  h-[3px] bg-gray-400 transition-all duration-200"/>
        )}
      </div>
      
      <div className="relative">
        <button 
          onClick={()=>{setShowPreview(true)}} 
          className="py-2 px-4 rounded-xl bg-[#15151d] text-white font-semibold"
        >
          Preview
        </button>
        {showPreview && (
          <div className="absolute   w-[60%] bottom-2  left-[18px]  top-12   h-[3px] bg-gray-400 transition-all duration-200"/>
        )}
      </div>
      <button 
  onClick={() => setShowPreview(false)} 
  className="py-2 px-4 rounded-xl bg-[#15151d] text-white font-semibold flex items-center justify-center" 
>

  Publish  <FaArrowRightLong className="ml-2" /> 
</button>
</div>) : null }  
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
         <div className="fixed inset-0 bg-[#0a0a0a] bg-opacity-85 z-50 flex items-center justify-center "
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

export default MEditor;