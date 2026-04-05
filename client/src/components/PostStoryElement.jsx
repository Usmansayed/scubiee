import React, { useState, useEffect } from 'react';
import axios from 'axios';
const cloud = import.meta.env.VITE_CLOUD_URL;

const api = import.meta.env.VITE_API_URL;

const PostStoryElement = ({ postId, setSelectedPost }) => {
  const [postSummary, setPostSummary] = useState(null);
  const [transform, setTransform] = useState({ scale: 1, rotate: 0 });

  // Fetch the post summary using the summary route
  useEffect(() => {
    if (!postId) return;
    axios
      .get(`${api}/post/summary/${postId}`)
      .then((res) => setPostSummary(res.data))
      .catch((err) => console.error("Error fetching post summary:", err));
  }, [postId]);

  if (!postSummary) return null;

  // On mouse wheel, adjust scale
  const handleWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.1 : -0.1;
    setTransform((prev) => ({
      ...prev,
      scale: Math.max(prev.scale + delta, 0.5),
    }));
  };

  // On double-click, rotate the element
  const handleDoubleClick = () => {
    setTransform((prev) => ({
      ...prev,
      rotate: prev.rotate + 15,
    }));
  };

  return (
    <div
      className="my-4 bg-white/5 rounded-lg px-2 pb-3 pt-1 cursor-pointer max-w-[350px] w-full"
      onClick={() => setSelectedPost({ id: postSummary.id })}
      onWheel={handleWheel}
      onDoubleClick={handleDoubleClick}
      style={{
        transform: `scale(${transform.scale}) rotate(${transform.rotate}deg)`,
        transformOrigin: "center",
        transition: "transform 0.2s ease-out",
      }}
    >
      <div className="flex items-center gap-2 mb-[6px]">
        <img
          src={`${cloud}/cloudofscubiee/profilePic/${postSummary.author.profilePicture || "default.png"}`}
          alt="Profile"
          className="w-8 h-8 rounded-full object-cover"
        />
        <span className="text-[14.2px] text-gray3400">{postSummary.author.username}</span>
      </div>
      <img
        src={`${cloud}/cloudofscubiee/Postthumbnail/${postSummary.thumbnail}`}
        alt={postSummary.title}
        className="w-full [aspect-ratio:9/6] object-cover rounded-md"
      />
      <div className="text-gray-300 mt-2 font-[500] font-sans max-md:text-[14.5px] text-[15.5px] leading-tight line-clamp-2 overflow-hidden">
        {postSummary.title}
      </div>
    </div>
  );
};

export default PostStoryElement;