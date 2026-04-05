import React, { useRef, useState, useEffect } from "react";
import { Stage, Layer, Image , Text, Rect, Transformer, Group } from "react-konva";
import { MdOutlineDriveFolderUpload } from "react-icons/md";
import { IoTextSharp } from "react-icons/io5";
import { FiLink } from "react-icons/fi";
import { VscMention } from "react-icons/vsc";
import "./MEditorWidget.css";
import { UploadCloudIcon } from "lucide-react";
import { LuDownload } from "react-icons/lu";
import { RiDeleteBin6Line } from "react-icons/ri";
import { MdDeleteOutline } from "react-icons/md";
import ColorThief from 'colorthief';
import Hammer from 'hammerjs';
import Konva from 'konva';
import { FFmpeg } from '@ffmpeg/ffmpeg';
import { fetchFile } from '@ffmpeg/util';
import JSZip from 'jszip';
const cloud = import.meta.env.VITE_CLOUD_URL;



Konva.hitOnDragEnabled = true;
Konva.captureTouchEventsEnabled = true;




const CreateStory = () => {
  const stageRef = useRef(null);
  const fileInputRef = useRef(null);
 const [videoScale, setVideoScale] = useState(1);
  const [images, setImages] = useState([]);
  const [textGroups, setTextGroups] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
const [isTransforming, setIsTransforming] = useState(false);

  const [showTextOverlay, setShowTextOverlay] = useState(false);
  const [textValue, setTextValue] = useState("");
  const [fontColor, setFontColor] = useState("#ffffff");
  const [backgroundColor, setBackgroundColor] = useState("#000000");
  const [showBackground, setShowBackground] = useState(false);
  const [showMentionOverlay, setShowMentionOverlay] = useState(false);
  const [mentionValue, setMentionValue] = useState("");
  const [showLinkOverlay, setShowLinkOverlay] = useState(false);
  const [linkValue, setLinkValue] = useState("");
  const [hasMedia, setHasMedia] = useState(false);
  const [canvasBgColor, setCanvasBgColor] = useState('#000000');
  const videoRef = useRef(null);
const konvaImageRef = useRef(null);
const [videoFile, setVideoFile] = useState(null);
const [videoPosition, setVideoPosition] = useState({ x: 0, y: 0 });
const [videoTransform, setVideoTransform] = useState({});
const trRef = useRef(null);

const [windowWidth, setWindowWidth] = useState(window.innerWidth);
const [initialRotation, setInitialRotation] = useState(0);
const [initialScale, setInitialScale] = useState({ x: 1, y: 1 });
const [initialDist, setInitialDist] = useState(0);
const [initialAngle, setInitialAngle] = useState(0);
const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
const containerRef = useRef(null);


useEffect(() => {
  const updateStageDimensions = () => {
    if (containerRef.current) {
      let stageWidth, stageHeight;

      if (window.innerWidth < window.innerHeight) {
        // For small screens, base calculations on width
        const containerWidth = window.innerWidth - 8; // Subtracting 8px for borders
        const aspectRatio = 16 / 9; // Inverted ratio since we're calculating height
        stageWidth = containerWidth;
        stageHeight = stageWidth * aspectRatio;
      } else {
        // Original logic for larger screens
        const containerHeight = window.innerHeight - 16;
        const aspectRatio = 9 / 16;
        stageHeight = containerHeight;
        stageWidth = stageHeight * aspectRatio;
      }

      // Ensure dimensions are even
      if (Math.round(stageWidth) % 2 !== 0) {
        stageWidth = Math.floor(stageWidth) - 1;
      }
      if (Math.round(stageHeight) % 2 !== 0) {
        stageHeight = Math.floor(stageHeight) - 1;
      }

      setStageSize({
        width: Math.round(stageWidth),
        height: Math.round(stageHeight),
      });
    }
  };

  // Attach the listener
  window.addEventListener("resize", updateStageDimensions);
  updateStageDimensions(); // Initial call

  return () => {
    window.removeEventListener("resize", updateStageDimensions);
  };
}, [containerRef]);

const handleStageTouch = (e) => {
  if (!selectedId || e.evt.touches.length !== 2) return;
  
  const stage = stageRef.current;
  const node = stage.findOne(`#${selectedId}`);
  if (!node) return;

  e.evt.preventDefault();
  const [t1, t2] = e.evt.touches;
  const p1 = { x: t1.clientX, y: t1.clientY };
  const p2 = { x: t2.clientX, y: t2.clientY };
  
  setInitialAngle(Math.atan2(p2.y - p1.y, p2.x - p1.x));
  setInitialRotation(node.rotation());
  setInitialDist(Math.hypot(p1.x - p2.x, p1.y - p2.y));
  setInitialScale({ x: node.scaleX(), y: node.scaleY() });
};

const handleStageTouchMove = (e) => {
  if (!selectedId || e.evt.touches.length !== 2) return;

  const stage = stageRef.current;
  const node = stage.findOne(`#${selectedId}`);
  if (!node) return;

  e.evt.preventDefault();
  const [t1, t2] = e.evt.touches;
  const p1 = { x: t1.clientX, y: t1.clientY };
  const p2 = { x: t2.clientX, y: t2.clientY };
  
  const currentAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
  const angleDiff = (currentAngle - initialAngle) * (180 / Math.PI);
  const currentDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
  const scaleFactor = currentDist / initialDist;

  node.rotation(initialRotation + angleDiff);
  node.scaleX(initialScale.x * scaleFactor);
  node.scaleY(initialScale.y * scaleFactor);
  node.getLayer().batchDraw();
};


useEffect(() => {
  if (!selectedId) return;
  const stage = stageRef.current?.getStage();
  if (!stage) return;
  const node = stage.findOne(`#${selectedId}`);
  if (!node) return;

  let initialRotation = 0;
  let initialAngle = 0;
  let initialDist = 0;
  let initialScaleX = node.scaleX();
  let initialScaleY = node.scaleY();

  // Apply offset once
  if (!node.hasOffsetApplied) {
    const offsetX = node.width() / 2;
    const offsetY = node.height() / 2;
    node.offset({ x: offsetX, y: offsetY });
    node.position({
      x: node.x() + offsetX * node.scaleX(),
      y: node.y() + offsetY * node.scaleY(),
    });
    node.hasOffsetApplied = true;
  }

  const handleTouchStart = (e) => {
    if (e.evt.touches.length === 2) {
      e.evt.preventDefault();
      const [t1, t2] = e.evt.touches;
      const p1 = { x: t1.clientX, y: t1.clientY };
      const p2 = { x: t2.clientX, y: t2.clientY };
      initialAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
      initialRotation = node.rotation();
      initialDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      initialScaleX = node.scaleX();
      initialScaleY = node.scaleY();
    }
  };

  const handleTouchMove = (e) => {
    if (e.evt.touches.length === 2) {
      e.evt.preventDefault();
      const [t1, t2] = e.evt.touches;
      const p1 = { x: t1.clientX, y: t1.clientY };
      const p2 = { x: t2.clientX, y: t2.clientY };
      const currentAngle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
      const angleDiff = (currentAngle - initialAngle) * (180 / Math.PI);
      const currentDist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
      const scaleFactor = currentDist / initialDist;
      node.rotation(initialRotation + angleDiff);
      node.scaleX(initialScaleX * scaleFactor);
      node.scaleY(initialScaleY * scaleFactor);
      node.getLayer().batchDraw();
    }
  };

  const handleTouchEnd = () => {
    initialRotation = 0;
    initialAngle = 0;
    initialDist = 0;
    initialScaleX = 0;
    initialScaleY = 0;
  };

  stage.on("touchstart", handleTouchStart);
  stage.on("touchmove", handleTouchMove);
  stage.on("touchend", handleTouchEnd);

  return () => {
    stage.off("touchstart", handleTouchStart);
    stage.off("touchmove", handleTouchMove);
    stage.off("touchend", handleTouchEnd);
  };
}, [selectedId]);

// Utility function to calculate the distance between two points
const getDistance = (p1, p2) => Math.sqrt(Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2));




  const extractFirstFrame = (file) => {
    return new Promise((resolve, reject) => {
      const video = document.createElement("video");
      video.src = URL.createObjectURL(file);
      video.addEventListener("loadeddata", () => {
        video.currentTime = 0;
      });
      video.addEventListener("seeked", () => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, video.videoWidth, video.videoHeight);
        const img = new window.Image();
        img.src = canvas.toDataURL("image/png");
        resolve(img);
      });
      video.addEventListener("error", (err) => reject(err));
    });
  };

  // Handle upload
  const handleUpload = () => {
    if (!hasMedia) {
      fileInputRef.current.accept = "image/*,video/*";
    } else {
      fileInputRef.current.accept = "image/*";
    }
    fileInputRef.current.click();
  };

  // Update Konva canvas with video frames
  const updateKonvaCanvas = () => {
    const video = videoRef.current;
    if (video && konvaImageRef.current) {
      konvaImageRef.current.image(video);
      konvaImageRef.current.getLayer().batchDraw();
      requestAnimationFrame(updateKonvaCanvas); // Continuously update the canvas
    }
  };

  // Start video playback and update Konva
  useEffect(() => {
    if (videoFile && videoRef.current) {
      videoRef.current.play();
      videoRef.current.addEventListener("play", updateKonvaCanvas);
    }

    // Cleanup
    return () => {
      if (videoRef.current) {
        videoRef.current.removeEventListener("play", updateKonvaCanvas);
      }
    };
  }, [videoFile]);

  const handleFilesUpload = (e) => {
    const files = e.target.files;
    if (!files) return;
    [...files].forEach((file) => {
      const reader = new FileReader();
      reader.onload = () => {
        if (file.type.startsWith("image/")) {
          const img = new window.Image();
          img.src = reader.result;
          img.onload = () => {
            const desiredWidth = 390;
            const desiredHeight = 700;
            const scale = Math.min(desiredWidth / img.width, desiredHeight / img.height);
  
            if (!hasMedia) {
              const colorThief = new ColorThief();
              const dominantColor = colorThief.getColor(img);
              const rgbColor = `rgb(${dominantColor[0]}, ${dominantColor[1]}, ${dominantColor[2]})`;
              // Set the base color - gradient will be created automatically through the Stage style
              setCanvasBgColor(rgbColor);
              setHasMedia(true);
            }
  
            setImages((prev) => [
              ...prev,
              {
                id: `img_${Date.now()}_${Math.random()}`,
                image: img,
                x: (desiredWidth - img.width * scale) / 2,
                y: (desiredHeight - img.height * scale) / 2,
                rotation: 0,
                scaleX: scale,
                scaleY: scale
              }
            ]);
          };
        } else if (file.type.startsWith("video/")) {
          extractFirstFrame(file).then((frameImage) => {
            const desiredWidth = 390;
            const desiredHeight = 700;
            const scale = Math.min(
              desiredWidth / frameImage.width,
              desiredHeight / frameImage.height
            );
            if (!hasMedia) {
              const colorThief = new ColorThief();
              const dominantColor = colorThief.getColor(frameImage);
              const rgbColor = `rgb(${dominantColor[0]}, ${dominantColor[1]}, ${dominantColor[2]})`;
              setCanvasBgColor(rgbColor);
              setHasMedia(true);
            }
            const file = e.target.files[0];
            if (file) {
              const videoURL = URL.createObjectURL(file);
              setVideoFile(videoURL);
            }
          });
        }
      };
      reader.readAsDataURL(file);
    });
  };
  // Add text
  const addText = () => {
    setTextGroups((prev) => [
      ...prev,
      {
        id: `text_${Date.now()}_${Math.random()}`,
        text: textValue,
        x: 100,
        y: 100,
        fontColor,
        backgroundColor,
        showBackground,
        rotation: 0,
        scaleX: 1,
        scaleY: 1
      }
    ]);
    setTextValue("");
    setShowTextOverlay(false);
  };

  useEffect(() => {
    const handleResize = () => {
      setWindowWidth(window.innerWidth);
    };
  
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Transformer
  const TransformerComponent = ({ selectedShape }) => {
    const trRef = useRef(null);

    useEffect(() => {
      if (trRef.current && selectedShape) {
        trRef.current.nodes([selectedShape]);
        trRef.current.getLayer().batchDraw();
      }
    }, [selectedShape]);

    return (
      
      <Transformer
      ref={trRef}
      rotateEnabled={windowWidth >= 1280 }
      enabledAnchors={
        windowWidth >= 1280 
          ? ["top-left", "top-right", "bottom-left", "bottom-right"]
          : []
      }
      rotateAnchorOffset={50}
    />
    );
  };

  // Find selected node
  const getSelectedNode = () => {
    if (!selectedId) return null;
    return stageRef.current
      .getStage()
      .findOne((node) => node.attrs.id === selectedId);
  };

  // Handle selection
  const handleSelect = (id) => {
    if (selectedId === id) {
      setSelectedId(null);
    } else
    setSelectedId(id);
  };

  const handleStageClick = (e) => {
    if (e.target === e.target.getStage()) {
      setSelectedId(null);
    }
  };


  const captureFrame = (stage) => {
    return new Promise(resolve => {
      const dataURL = stage.toDataURL();
      const img = new window.Image();
      img.src = dataURL;
      img.onload = () => resolve(dataURL);
    });
  };

  const createVideoFromFrames = async (frames, fps = 30) => {
    const ffmpeg = new FFmpeg();
  
    try {
      await ffmpeg.load(); // Load FFmpeg WebAssembly module
  
      // Write frames into FFmpeg's virtual filesystem
      for (let i = 0; i < frames.length; i++) {
        const frameBase64 = frames[i].replace(/^data:image\/\w+;base64,/, '');
        const frameBuffer = Uint8Array.from(atob(frameBase64), char => char.charCodeAt(0));
        await ffmpeg.writeFile(`frame_${String(i).padStart(3, '0')}.png`, frameBuffer);
      }
  
      // Video output file
      const outputFile = 'output.mp4';
  
      // FFmpeg command to generate the video
      await ffmpeg.exec([
        '-framerate', fps.toString(),  // Set frame rate
        '-i', 'frame_%03d.png',       // Input frame pattern
        '-c:v', 'libx264',            // Video codec
        '-pix_fmt', 'yuv420p',        // Pixel format
        '-vf', 'scale=640:-2',        // Optional: Resize to fit dimensions
        outputFile                    // Output file name
      ]);
  
      // Read the generated video file from FFmpeg's virtual filesystem
      const videoData = await ffmpeg.readFile(outputFile);
  
      // Convert video data to a Blob for downloading
      const blob = new Blob([videoData], { type: 'video/mp4' });
      const url = URL.createObjectURL(blob);
  
      // Trigger download
      const link = document.createElement('a');
      link.href = url;
      link.download = 'animation.mp4';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
  
      console.log('Video created and downloaded successfully!');
    } catch (error) {
      console.error('Error creating video:', error);
    } finally {
      // Cleanup: Remove virtual filesystem files
      for (let i = 0; i < frames.length; i++) {
        await ffmpeg.removeFile(`frame_${String(i).padStart(3, '0')}.png`);
      }
      await ffmpeg.removeFile(outputFile);
    }
  };
  
  const handleDownload = async () => {
    if (!videoFile) {
      // Handle image download
      const dataUrl = stageRef.current.toDataURL();
      const link = document.createElement('a');
      link.href = dataUrl;
      link.download = 'story.png';
      link.click();
      return;
    }
    const stage = stageRef.current;
    const fps = 60;
    const duration = 10; // 2 seconds
    const totalFrames = fps * duration;
  
    try {
      // Capture frames from the canvas
      const frames = [];
      for (let i = 0; i < totalFrames; i++) {
        const frame = await captureFrame(stage);
        frames.push(frame);
      }
  
      // Create and download video from frames
      await createVideoFromFrames(frames, fps);
    } catch (error) {
      console.error('Error capturing frames or creating video:', error);
    }
  };
  const addMention = () => {
    setTextGroups((prev) => [
      ...prev,
      {
        id: `mention_${Date.now()}_${Math.random()}`,
        text: mentionValue,
        x: 100,
        y: 100,
        fontColor: "#000000",
        backgroundColor: "#ffffff",
        showBackground: true,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        isMention: true
      }
    ]);
    setMentionValue("");
    setShowMentionOverlay(false);
  };

  // Add link
  const addLink = () => {
    setTextGroups((prev) => [
      ...prev,
      {
        id: `link_${Date.now()}_${Math.random()}`,
        text: linkValue,
        x: 100,
        y: 100,
        fontColor: "#000000",
        backgroundColor: "#ffffff",
        showBackground: true,
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        isLink: true
      }
    ]);
    setLinkValue("");
    setShowLinkOverlay(false);
  };

  // Delete selected object
  const handleDelete = () => {
    if (!selectedId) return;
    setImages((prev) => prev.filter((img) => img.id !== selectedId));
    setTextGroups((prev) => prev.filter((txt) => txt.id !== selectedId));
    setSelectedId(null);
  };

  // Add this function to determine if the selected item is the primary upload
const isPrimaryUpload = () => {
  if (videoFile) {
    return selectedId === 'video';
  } else if (images.length > 0) {
    return selectedId === images[0].id;
  }
  return false;
};

useEffect(() => {
  if (videoFile && videoRef.current) {
    videoRef.current.addEventListener("loadedmetadata", () => {
      // Always set loop to true so even non-trimmed videos will replay
      videoRef.current.loop = true;
      if (videoRef.current.duration > 60) {
        videoRef.current.currentTime = 0;
        // Only trim if the video is longer than 60s
        videoRef.current.addEventListener("timeupdate", () => {
          if (videoRef.current.currentTime >= 60) {
            videoRef.current.currentTime = 0;
          }
        });
      }
      videoRef.current.play();
      videoRef.current.addEventListener("play", updateKonvaCanvas);
    });
  }
  return () => {
    if (videoRef.current) {
      videoRef.current.removeEventListener("play", updateKonvaCanvas);
    }
  };
}, [videoFile]);

const createColorVariations = (color) => {
  const rgbValues = color.replace('rgb(', '').replace(')', '').split(',');
  const baseValues = rgbValues.map(val => parseInt(val));
  
  // Create 4 variations with subtle differences
  const color1 = baseValues.map(val => Math.min(255, val + (255 - val) * 0.15));
  const color2 = baseValues.map(val => Math.min(255, val + (255 - val) * 0.10));
  const color3 = baseValues.map(val => Math.min(255, val + (255 - val) * 0.05));
  const color4 = baseValues; // Original color
  
  return {
    color1: `rgba(${color1.join(',')}, 0.60)`,
    color2: `rgba(${color2.join(',')}, 0.70)`,
    color3: `rgba(${color3.join(',')}, 0.75)`,
    color4: `rgba(${color4.join(',')}, 0.70)`
  };
};
  return (
    <div className="h-screen text-white flex flex-col items-center justify-start md:my-2">
      {/* Top Buttons */}

      {/* Hidden file input */}
      <input
        type="file"
        multiple
        accept="image/*"
        ref={fileInputRef}
        onChange={handleFilesUpload}
        style={{ display: "none" }}
      />

      {/* Overlay for text input */}
      {showTextOverlay && (
        <div className="fixed inset-0 flex items-center justify-center thetopone max-md:mb-60">
          <div className="p-4 backdrop-blur-md bg-black/85 rounded-lg shadow-lg w-[90%] max-w-[380px] md:ml-14 space-y-6">
            <h2 className="text-lg font-semibold text-white">Add Text Overlay</h2>
            <div className="flex items-center space-x-2">
              <input
                type="text"
                className="flex-grow p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
                placeholder="Enter text here"
                value={textValue}
                autoFocus
                onChange={(e) => setTextValue(e.target.value)}
              />
              <input
                type="color"
                className="w-[55px] h-[55px] p-0 border-0 rounded-xl bg-transparent cursor-pointer"
                value={fontColor}
                onChange={(e) => setFontColor(e.target.value)}
              />
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <input
                  type="checkbox"
                  className="form-checkbox h-5 w-5 text-gray-500 border border-gray-500 rounded focus:ring-gray-500"
                  checked={showBackground}
                  onChange={(e) => setShowBackground(e.target.checked)}
                />
                <span className="text-smd text-gray-300">Background</span>
              </div>
              {showBackground && (
                <input
                  type="color"
                  className="w-10 h-10 p-0 border-0 bg-transparent cursor-pointer"
                  value={backgroundColor}
                  onChange={(e) => setBackgroundColor(e.target.value)}
                />
              )}
            </div>
            <div className="flex items-center justify-end space-x-4">
              <button
                onClick={addText}
                className="px-5 py-2 bg-white text-black font-semibold rounded-md hover:bg-gray-400 transition duration-200"
              >
                Add Text
              </button>
              <button
                onClick={() => setShowTextOverlay(false)}
                className="px-5 py-2 bg-white text-black font-semibold rounded-md hover:bg-gray-400 transition duration-200"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {showMentionOverlay && (
        <div className="fixed inset-0 flex items-center justify-center thetopone max-md:mb-40">
          <div className="p-4 backdrop-blur-md bg-black/85 rounded-lg shadow-lg w-[90%] max-w-[380px] md:ml-14 space-y-6">
          <h2 className="text-white font-semibold">Add Mention</h2>
            <input
              type="text"
              placeholder="@username"
              value={mentionValue}
              onChange={(e) => setMentionValue(e.target.value)}
              className="flex w-full p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
              autoFocus
            />
            <div className="flex justify-end space-x-3">
              <button onClick={addMention} className="px-4 py-2 bg-white text-black rounded-md focus:outline-none border-none">
                Add Mention
              </button>
              <button onClick={() => setShowMentionOverlay(false)} className="px-4 py-2 bg-white text-black rounded-md">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {showLinkOverlay && (
        <div className="fixed inset-0 flex items-center justify-center thetopone max-md:mb-40">
          <div className="p-4 backdrop-blur-md bg-black/85 rounded-lg shadow-lg w-[90%] max-w-[380px] md:ml-14 space-y-6">
          <h2 className="text-white font-semibold">Add Link</h2>
            <input
              type="text"
              placeholder="Enter link text"
              value={linkValue}
              onChange={(e) => setLinkValue(e.target.value)}
              className="flex w-full p-2 rounded-md bg-transparent border-b-2 focus:border-none text-white focus:outline-blue-300 focus:outline-none"
              autoFocus
            />
            <div className="flex justify-end space-x-3">
              <button onClick={addLink} className="px-4 py-2 bg-white text-black rounded-md">
                Add Link
              </button>
              <button onClick={() => setShowLinkOverlay(false)} className="px-4 py-2 bg-white text-black rounded-md">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Konva Stage */}
      <div    className={`md:border-2 border-gray-800 rounded-xl  h-[calc(100vh-16px)] max-md:mx-2`}
      style={{ background: canvasBgColor }}
       ref={containerRef} >
        <div className="relative h-0  space-x-3 pl-3 bg-transparent w-full flex justify-start rounded-t-xl thetopone backdrop-blur-lg">
          <button
            onClick={handleUpload}
          >
            <UploadCloudIcon className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 mt-2 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          <button
            onClick={() => setShowTextOverlay(true)}
          >
            <IoTextSharp className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          <button
            onClick={() => setShowLinkOverlay(true)}
          >
            <FiLink className="inline w-[36px] h-[36px] md:w-[38px] md:h-[38px]  px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          <button
            onClick={() => setShowMentionOverlay(true)}
          >
            <VscMention className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-1 py-[1px] rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>

              {selectedId && !isPrimaryUpload() && (
                <button
                  onClick={handleDelete}
                >
                  <RiDeleteBin6Line className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]"/>
                </button>
              )}
          <button
            onClick={handleDownload}
          >
            <LuDownload className="inline w-[38px] h-[38px] md:h-10 md:w-10 px-2 py-1 rounded-full backdrop-blur-md mt-2  bg-black/40 hover:bg-[#252525]" />
          </button>
          </div>
          {videoFile && (
  <>
    {/* Hidden video element */}
    <video
      ref={videoRef}
      src={videoFile}
      style={{ display: "none" }}
      crossOrigin="anonymous" // Ensure CORS issues are avoided for local files
      onLoadedMetadata={(e) => {
        const video = e.target;
        const videoWidth = video.videoWidth;
        const videoHeight = video.videoHeight;
        const canvasWidth = stageSize.width;
        const canvasHeight = stageSize.height;
        const scale = Math.min(canvasWidth / videoWidth, canvasHeight / videoHeight);
        setVideoScale(scale);
      }}
    />
  </>
)}
<Stage
     width={stageSize.width}
     height={stageSize.height}
  ref={stageRef}
  onMouseDown={handleStageClick}
  onTouchStart={handleStageTouch}
  onTouchMove={handleStageTouchMove}

  style={{
    background: (() => {
      const colors = createColorVariations(canvasBgColor);
      return `radial-gradient(circle at center, 
        ${colors.color1} 0%, 
        ${colors.color2} 30%, 
        ${colors.color3} 60%, 
        ${colors.color4} 100%)`
    })()
  }}>
  <Layer>
    {videoFile && (
      <Image
        ref={konvaImageRef}
        id="video"
        image={videoRef.current}
        width={videoRef.current ? videoRef.current.videoWidth : 0}
        height={videoRef.current ? videoRef.current.videoHeight : 0}
        x={(390 - (videoRef.current ? videoRef.current.videoWidth : 0) * videoScale) / 2}
        y={(680 - (videoRef.current ? videoRef.current.videoHeight : 0) * videoScale) / 2}
        scaleX={videoScale}
        scaleY={videoScale}
        draggable={windowWidth >= 1280 || selectedId === 'video'}
        onClick={(e) => {
          e.cancelBubble = true;
          handleSelect('video');
        }}
        onTap={(e) => {
          e.cancelBubble = true;
          handleSelect('video');
        }}
        onDragEnd={(e) => {
          const node = e.target;
          setVideoPosition({ x: node.x(), y: node.y() });
        }}
        onTransformEnd={(e) => {
          const node = e.target;
          setVideoTransform({
            x: node.x(),
            y: node.y(),
            rotation: node.rotation(),
            scaleX: node.scaleX(),
            scaleY: node.scaleY()
          });
        }}
      />
    )}
    {selectedId === 'video' && (
       <Transformer
       ref={trRef}
       rotateEnabled={windowWidth >= 1280 }
       enabledAnchors={
         windowWidth >= 1280 
           ? ["top-left", "top-right", "bottom-left", "bottom-right"]
           : []
       }
       rotateAnchorOffset={50}
     />
    )}
    {images.map((imgObj) => (
      <Image
        key={imgObj.id}
        id={imgObj.id}
        image={imgObj.image}
        x={imgObj.x}
        y={imgObj.y}
        draggable={windowWidth >= 1280 || selectedId === imgObj.id}
        rotation={imgObj.rotation}
        scaleX={imgObj.scaleX}
        scaleY={imgObj.scaleY}
        onClick={(e) => {
          e.cancelBubble = true;
          handleSelect(imgObj.id);
        }}
        onTap={(e) => {
          e.cancelBubble = true;
          handleSelect(imgObj.id);
        }}
        onDragEnd={(e) => {
          const node = e.target;
          setImages((prev) =>
            prev.map((o) =>
              o.id === imgObj.id
                ? { ...o, x: node.x(), y: node.y() }
                : o
            )
          );
        }}
        onTransformEnd={(e) => {
          const node = e.target;
          setImages((prev) =>
            prev.map((o) =>
              o.id === imgObj.id
                ? {
                    ...o,
                    x: node.x(),
                    y: node.y(),
                    rotation: node.rotation(),
                    scaleX: node.scaleX(),
                    scaleY: node.scaleY()
                  }
                : o
            )
          );
        }}
      />
    ))}
   {textGroups.map((txt) => (
  <Group
    key={txt.id}
    id={txt.id}
    x={txt.x}
    y={txt.y}
    draggable={windowWidth >= 1280 || selectedId === txt.id}
    rotation={txt.rotation}
    scaleX={txt.scaleX}
    scaleY={txt.scaleY}
    onClick={(e) => {
      e.cancelBubble = true;
      handleSelect(txt.id);
    }}
    onTap={(e) => {
      e.cancelBubble = true;
      handleSelect(txt.id);
    }}
    onDragEnd={(e) => {
      const node = e.target;
      setTextGroups((prev) =>
        prev.map((o) =>
          o.id === txt.id ? { ...o, x: node.x(), y: node.y() } : o
        )
      );
    }}
    onTransformEnd={(e) => {
      const node = e.target;
      const scaleX = node.scaleX();
      const scaleY = node.scaleY();
      
      // Update text scale and position
      setTextGroups((prev) =>
        prev.map((o) =>
          o.id === txt.id
            ? {
                ...o,
                x: node.x(),
                y: node.y(),
                rotation: node.rotation(),
                scaleX: scaleX,
                scaleY: scaleY
              }
            : o
        )
      );
    }}
  >
        {txt.showBackground && (
          <Rect
            id={`${txt.id}_bg`}
            x={0}
            y={0}
            fill={txt.backgroundColor}
            listening
            cornerRadius={6}
          />
        )}
        <Text
          text={
            txt.isMention
              ? `@ ${txt.text}`
              : txt.isLink
              ? `🔗 ${txt.text}`
              : txt.text
          }
          fontSize={20}
          fill={txt.fontColor}
          x={5}
          y={5}
          ref={(node) => {
            if (node && txt.showBackground) {
              const newWidth = node.width() + 10;
              const newHeight = node.height() + 10;
              const rect = node.getParent().findOne(`#${txt.id}_bg`);
              if (rect) {
                rect.width(newWidth);
                rect.height(newHeight);
              }
            }
          }}
        />
      </Group>
    ))}

{selectedId && textGroups.find(t => t.id === selectedId) && (
  <Transformer
    ref={trRef}
    rotateEnabled={true}
    enabledAnchors={[
      "top-left",
      "top-right",
      "bottom-left",
      "bottom-right"
    ]}
    rotateAnchorOffset={50}
  />
)}
    <TransformerComponent selectedShape={getSelectedNode()} />
  </Layer>
</Stage>
</div>
    </div>
  );
};

export default CreateStory;