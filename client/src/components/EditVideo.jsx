import React, { useRef, useState, useEffect } from "react";
import { Stage, Layer, Image as KonvaImage } from "react-konva";
const cloud = import.meta.env.VITE_CLOUD_URL;

const VideoUploadAndDisplay = () => {
  const [videoFile, setVideoFile] = useState(null);
  const videoRef = useRef(null);
  const konvaImageRef = useRef(null);

  // Handle video upload
  const handleVideoUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      const videoURL = URL.createObjectURL(file);
      setVideoFile(videoURL);
    }
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

  return (
    <div>
      <h1>Video Upload and Display with Konva.js</h1>
      <input type="file" accept="video/*" onChange={handleVideoUpload} />
      {videoFile && (
        <>
          {/* Hidden video element */}
          <video
            ref={videoRef}
            src={videoFile}
            style={{ display: "none" ,}}
            crossOrigin="anonymous" // Ensure CORS issues are avoided for local files
          />
          {/* Konva canvas */}
          <Stage width={800} height={600}>
            <Layer>
              <KonvaImage
                ref={konvaImageRef}
                width={800}
                height={600} // Ensure this matches the video's aspect ratio
             
                />
            </Layer>
          </Stage>
        </>
      )}
    </div>
  );
};

export default VideoUploadAndDisplay;
