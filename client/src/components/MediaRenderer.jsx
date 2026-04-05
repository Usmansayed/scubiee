import React from 'react';
const cloud = import.meta.env.VITE_CLOUD_URL;

const MediaRenderer = ({ media, className, api, altText = "Post media" }) => {
  // If no media or empty array, render placeholder
  if (!media || (Array.isArray(media) && media.length === 0)) {
    return (
      <div className={`${className} bg-gray-800 flex items-center justify-center`}>
        <span className="text-gray-500">No media</span>
      </div>
    );
  }

  // Handle legacy thumbnail field for old posts
  if (typeof media === 'string') {
    return (
      <img 
        src={`${cloud}/cloudofscubiee/Postthumbnail/${media}`}
        alt={altText}
        className={className}
      />
    );
  }

  // Handle single media item
  if (!Array.isArray(media)) {
    const item = media;
    return item.type === 'video' ? (
      <video
        src={`${cloud}/cloudofscubiee/postVideos/${item.url}`}
        className={className}
        preload="metadata"
        muted
      />
    ) : (
      <img
        src={`${cloud}/cloudofscubiee/postImages/${item.url}`}
        alt={altText}
        className={className}
      />
    );
  }

  // Handle first item from media array
  const firstItem = media[0];
  return firstItem.type === 'video' ? (
    <video
      src={`${cloud}/cloudofscubiee/postVideos/${firstItem.url}`}
      className={className}
      preload="metadata"
      muted
    />
  ) : (
    <img
      src={`${cloud}/cloudofscubiee/postImages/${firstItem.url}`}
      alt={altText}
      className={className}
    />
  );
};

export default MediaRenderer;
