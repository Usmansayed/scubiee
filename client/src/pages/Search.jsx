import React, { useState, useRef, useEffect } from 'react';
import { IoSearch } from "react-icons/io5";
import axios from 'axios';
import { FiHash } from "react-icons/fi";
import { RiVerifiedBadgeFill } from 'react-icons/ri';
import { IoArrowBack } from "react-icons/io5";
import { TiDocumentText } from "react-icons/ti";

const Search = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedOption, setSelectedOption] = useState('accounts');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedHashtag, setSelectedHashtag] = useState(null);
  const [hashtagPosts, setHashtagPosts] = useState([]);
  const [hashtagInfo, setHashtagInfo] = useState(null);
  const [isLoadingHashtag, setIsLoadingHashtag] = useState(false);
  const inputRef = useRef(null);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [loadingMore, setLoadingMore] = useState(false);
  const [isSearchLoading, setIsSearchLoading] = useState(false);
  const latestRequestRef = useRef(0);
  const cancelTokenRef = useRef(null);
  const api = import.meta.env.VITE_API_URL;
  const cloud = import.meta.env.VITE_CLOUD_URL;
  const vcloud = import.meta.env.VITE_VIDEO_CLOUD_URL;

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "VIDEO" || e.target.tagName === "IMG") {
        e.preventDefault();
      }
    };
    document.addEventListener("contextmenu", handler);
    return () => document.removeEventListener("contextmenu", handler);
  }, []);

  const handleOptionClick = (option) => {
    setSelectedOption(option);
    
    // Focus the input after changing options
    inputRef.current?.focus();
    
    if (searchTerm.trim()) {
      handleSearch(searchTerm, option);
    }
  };

  const renderOptionButton = (option, label) => {
    const isSelected = selectedOption === option;
    return (
      <button
        onClick={() => handleOptionClick(option)}
        className={`py-2 cursor-pointer transition duration-150 ease-in-out ${
          isSelected ? 'border-b-2 border-white text-white' : 'hover:text-white text-zinc-500'
        }`}
      >
        {label}
      </button>
    );
  };

  const fetchMorePosts = async (pageToFetch, searchQ) => {
    if (loadingMore) return;
    setLoadingMore(true);
    
    // Create a new cancellation token
    const cancelToken = axios.CancelToken.source();
  
    try {
      const response = await axios.post(
        `${api}/search/posts`,
        { query: searchQ, page: pageToFetch },
        { 
          withCredentials: true,
          cancelToken: cancelToken.token
        }
      );
      
      // Check if we have valid data before updating state
      const newPosts = response.data.posts || [];
      
      if (newPosts.length > 0) {
        // Only update if we got actual results
        setSearchResults((prev) =>
          pageToFetch === 1 ? newPosts : [...prev, ...newPosts]
        );
      }
      
      // Update hasMore based on response or set to false if no new posts
      setHasMore(response.data.pagination?.hasMore || false);
    } catch (error) {
      // Ignore cancellation errors
      if (!axios.isCancel(error)) {
        setHasMore(false);
      }
    } finally {
      setLoadingMore(false);
    }
  };
  
  // Update the scroll event handler with better conditions
  useEffect(() => {
    const handleScroll = () => {
      // Don't attempt to load more if already loading, no more results, or not on posts tab
      if (!hasMore || loadingMore || selectedOption !== 'posts') return;
      
      const scrollPosition = window.innerHeight + document.documentElement.scrollTop;
      const pageHeight = document.documentElement.offsetHeight;
      const threshold = pageHeight - 300; // Slightly earlier trigger point
      
      // Only trigger a load if we're near the bottom and we have confirmed there's more to load
      if (scrollPosition >= threshold && hasMore) {
        setPage((prev) => prev + 1);
      }
    };
    
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, [hasMore, loadingMore, selectedOption]); 
  
  // Update the page effect to be more defensive
  useEffect(() => {
    // Only fetch more if we're on the posts tab, have a search term, and have confirmed more posts exist
    if (selectedOption === 'posts' && page > 1 && hasMore && searchTerm.trim()) {
      fetchMorePosts(page, searchTerm);
    }
  }, [page, hasMore, selectedOption, searchTerm]);

  const handleSearch = async (query, option = selectedOption) => {
    setSearchTerm(query);
    setPage(1);
    
    // No need to show loading for empty queries
    if (!query.trim()) {
      setSearchResults([]);
      return;
    }
    
    // Cancel previous request
    if (cancelTokenRef.current) {
      cancelTokenRef.current.cancel('Operation canceled due to new search request');
    }
    
    // Create a new cancellation token
    const cancelToken = axios.CancelToken.source();
    cancelTokenRef.current = cancelToken;
    
    // Track this request with a timestamp to ensure we only process the most recent
    const requestTimestamp = Date.now();
    latestRequestRef.current = requestTimestamp;
    
    // Show loading indicator
    setIsSearchLoading(true);
  
    try {
      let response;
      
      if (option === 'accounts') {
        response = await axios.post(
          `${api}/search/users`, 
          { username: query }, 
          { 
            withCredentials: true,
            cancelToken: cancelToken.token
          }
        );
      } else if (option === 'posts') {
        response = await axios.post(
          `${api}/search/posts`, 
          { query }, 
          { 
            withCredentials: true,
            cancelToken: cancelToken.token
          }
        );
      } else if (option === 'tags') {
        response = await axios.post(
          `${api}/search/tags`, 
          { tag: query }, 
          { 
            withCredentials: true,
            cancelToken: cancelToken.token
          }
        );
      }
      
      // Only update results if this is still the most recent search
      if (requestTimestamp === latestRequestRef.current) {
        console.log('Updating search results for query:', query);
        
        if (option === 'accounts') {
          setSearchResults(response.data || []);
        } else if (option === 'posts') {
          setSearchResults(response.data?.posts || []);
          setHasMore(response.data?.pagination?.hasMore || false);
        } else if (option === 'tags') {
          setSearchResults(response.data || []);
        }
        
        // Always reset loading state
        setIsSearchLoading(false);
      } else {
        console.log('Ignoring outdated search results for query:', query);
      }
    } catch (error) {
      // Check if the request was canceled
      if (axios.isCancel(error)) {
        console.log('Search request canceled:', error.message);
      } else {
        console.error('Search error:', error);
        // Only update state if this is the latest request
        if (requestTimestamp === latestRequestRef.current) {
          setSearchResults([]);
          setIsSearchLoading(false);
        }
      }
    }
  };

  // Fetch posts by hashtag
  const fetchHashtagPosts = async (tagName) => {
    setIsLoadingHashtag(true);
    try {
      const response = await axios.get(`${api}/search/posts/hashtag/${tagName}`, {
        withCredentials: true
      });
      setHashtagPosts(response.data.posts);
      setHashtagInfo({
        name: response.data.hashtag.name,
        count: response.data.hashtag.count
      });
    } catch (error) {
      // Handle error state if needed
    } finally {
      setIsLoadingHashtag(false);
    }
  };

  // Handle hashtag selection
  const handleHashtagSelect = (tag) => {
    setSelectedHashtag(tag);
    fetchHashtagPosts(tag.name);
  };

  // Go back to search
  const handleBackToSearch = () => {
    setSelectedHashtag(null);
    setHashtagPosts([]);
    setHashtagInfo(null);
  };

  // Focus the input field when the component mounts
  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  
  // On mount, read query parameters if present and trigger search accordingly.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const term = params.get('term') || '';
    const option = params.get('selectedOption') || 'accounts';
    const tag = params.get('tag');
    
    if (tag) {
      // If a hashtag parameter is present, handle it as a selected hashtag
      setSelectedOption('tags');
      const hashtagObj = { name: tag };
      setSelectedHashtag(hashtagObj);
      fetchHashtagPosts(tag);
    } else if (term.trim()) {
      setSearchTerm(term);
      setSelectedOption(option);
      handleSearch(term, option);
    } else {
      setSearchTerm('');
      setSelectedOption(option);
    }
    
    // Cleanup function to cancel any pending requests when component unmounts
    return () => {
      if (cancelTokenRef.current) {
        cancelTokenRef.current.cancel('Component unmounted');
      }
    };
  }, []);

  // Render post item (used both in search results and hashtag posts)
  const renderPostItem = (result) => (
    <div className="py-3 max-md:py-2 flex items-start space-x-3 hover:bg-[#181818] cursor-pointer transition ease-in-out" 
         onClick={() => window.location.href = result.isShort ? `/shorts/${result.id}` : `/viewpost/${result.id}`}>
      {/* Thumbnail container with SHORT badge if applicable */}
      <div className="flex-shrink-0 relative">
      {result.isShort ? (
  result.media && result.media.length > 0 ? (
    result.media[0].type === 'video' ? (
      // Video short
      <video 
        src={`${cloud}/cloudofscubiee/shortVideos/${result.media[0].url}`}
        className="h-24 max-md:h-[86px] w-auto [aspect-ratio:9/6] object-cover rounded-md"
        preload="metadata"
        muted
      />
    ) : (
      // Image short
      <img 
        src={`${cloud}/cloudofscubiee/shortImages/${result.media[0].url}`}
        alt=""
        className="h-24 max-md:h-[86px] w-auto [aspect-ratio:9/6] object-cover rounded-md"
      />
    )
  ) : (
    // Fallback for shorts with no media
    <div className="h-24 max-md:h-[86px] w-[144px] bg-gray-800 rounded-md flex items-center justify-center">
      <span className="text-gray-500">No image</span>
    </div>
  )
) : (
          // Regular post - use first media item
          result.media && result.media.length > 0 ? (
            result.media[0].type === 'video' ? (
              <video 
                src={`${cloud}/cloudofscubiee/postVideos/${result.media[0].url}`}
                className="h-24 max-md:h-[86px] w-auto [aspect-ratio:9/6] object-cover rounded-md"
                preload="metadata"
                muted
              />
            ) : (
              <img 
                src={`${cloud}/cloudofscubiee/postImages/${result.media[0].url}`}
                alt=""
                className="h-24 max-md:h-[86px] w-auto [aspect-ratio:9/6] object-cover rounded-md"
              />
            )
          ) : (
            // Fallback to thumbnail if exists, otherwise show placeholder
            result.thumbnail ? (
              <img 
                src={`${cloud}/cloudofscubiee/Postthumbnail/${result.thumbnail}`}
                alt=""
                className="h-24 max-md:h-[86px] w-auto [aspect-ratio:9/6] object-cover rounded-md"
              />
            ) : (
              <div className="h-24 max-md:h-[86px] w-[144px] bg-gray-800 rounded-md flex items-center justify-center">
                <span className="text-gray-500">No image</span>
              </div>
            )
          )
        )}
        
        {/* SHORT badge overlay */}
        {result.isShort && (
          <div className="absolute bottom-1 right-1 bg-gray-800 p-0 border-gray-600 text-white font-poppins font-semibold rounded-md z-10 shadow-md">
            <TiDocumentText className='text-[25px] p-0'/>
          </div>
        )}
      </div>
      
      {/* Content on the right */}
      <div className="flex-grow overflow-hidden">
        {/* Display post title or content */}
        <h3 className="text-white text-[16px] mt-[-3px] max-md:text-[14.5px] max-md:font-sans max-md:font-semibold font-[400] line-clamp-2">
          {result.isShort 
            ? result.content || "Untitled Short" 
            : result.title || result.content || "Untitled Post"}
        </h3>
        
        {/* Author with verified badge */}
        <div className="flex items-center mt-1">
          <span className="text-[13.2px] max-md:text-[12px] text-gray-300">
            {result.author?.username}
          </span>
          {result.author?.Verified && (
            <RiVerifiedBadgeFill className="text-blue-500 h-[13px] w-[13px] ml-1" />
          )}
        </div>
        
        {/* Date, views, and likes */}
        <div className="text-[13px] max-md:text-[12px] mt-1 font-semibold font-sans text-gray-300">
          {new Date(result.createdAt).toLocaleDateString('en-US', {
            day: 'numeric',
            month: 'short',
            year: 'numeric'
          })}
          <span className="mx-1 font-bold"> • </span>
          {(result.views > 999 
            ? (result.views/1000).toFixed(1) + 'k' 
            : result.views)} Views
          <span className="mx-1 font-bold"> • </span>
          {(result.likes > 999 
            ? (result.likes/1000).toFixed(1) + 'k' 
            : result.likes)} likes
        </div>
      </div>
    </div>
  );

  return (
    <main className='bg-[#0a0a0a] min-h-screen'>
      <div className="bg-[#0a0a0a] flex flex-col items-center w-full h-full">
        {/* Fixed header */}
        <div className="fixed w-full max-w-[650px] left-1/2 transform -translate-x-1/2 top-0 z-50 bg-[#0a0a0a] ">
  <div className={`max-w-[650px] mx-auto bg-[#0a0a0a] ${selectedHashtag ? 'pt-6' : 'pt-4 pb-1'} px-4 max-md:px-2`}>
    {selectedHashtag ? (
      // Hashtag header - more compact
      <div className="relative w-full flex items-center px-3 py-1 a">
        <button 
          onClick={handleBackToSearch}
          className="text-white p-2 ml-4 hover:bg-zinc-800 rounded-full transition"
        >
          <IoArrowBack className="w-7 h-7" />
        </button>
        <div className="flex items-center ml-4">
          <FiHash className="text-white w-5 h-5 mr-[2px]" />
          <span className="text-white font-medium text-xl">{hashtagInfo?.name}</span>
          <span className="text-gray-400 text-sm ml-3">({hashtagInfo?.count} Posts)</span>
        </div>
      </div>
    ) : (
      // Search bar - unchanged
      <>
        <div className="relative w-full md:mt-1 px-3">
          <IoSearch className="absolute top-[51%] ml-3 w-5 h-5 left-3 transform -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            ref={inputRef}
            placeholder="Search..."
            value={searchTerm}
            onChange={(e) => handleSearch(e.target.value)}
            className="w-full pl-11 p-3 autofocus border-2 text-white bg-transparent placeholder-zinc-500 outline-none mt-[1px] border-gray-400 border-x-0 border-t-0 rounded-none shadow-lg transition-shadow duration-300"
          />
        </div>

        <div className="flex justify-between bg md:mx-24 max-md:mx-8 max-sm:mx-8 max-md:text-sm mt-2">
          {renderOptionButton('accounts', 'Accounts')}
          {renderOptionButton('posts', 'Posts')}
          {renderOptionButton('tags', 'Tags')}
        </div>
      </>
    )}
  </div>
</div>
  
        {/* Content area starts below the fixed header */}
        <div className={`w-full max-w-[650px] ${selectedHashtag ? 'mt-[80px]' : 'mt-[120px]'} px-4 max-md:px-2`}>
        {/* Show loading state while fetching hashtag posts */}
        {isLoadingHashtag && (
    <div className="flex justify-center items-center py-10">
      <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
    </div>
  )}
  
  {/* Search loading */}
  {!selectedHashtag && isSearchLoading && (
    <div className="flex justify-center items-center py-10">
      <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
    </div>
  )}


          {/* Hashtag posts */}
          {!isLoadingHashtag && selectedHashtag && hashtagPosts.length > 0 && (
            <div className="mt-4 md:mr-10">
              {hashtagPosts.map(post => (
                <div key={post.id}>
                  {renderPostItem(post)}
                </div>
              ))}
            </div>
          )}
  
          {/* No hashtag posts found */}
          {!isLoadingHashtag && selectedHashtag && hashtagPosts.length === 0 && (
            <div className="mt-10 text-center">
              <p className="text-white text-lg">No posts found for #{selectedHashtag.name}</p>
              <p className="text-gray-400 mt-2">Try searching for a different hashtag</p>
            </div>
          )}
  
          {/* Regular search results */}
          {!selectedHashtag && searchResults.length > 0 && (
            <div className="mt-4 md:mr-10 ">
              {searchResults.map((result) => (
                <div key={result.id}>
                 {selectedOption === 'accounts' && (
  <div className="p-3 max-md:p-2 flex items-center space-x-4 hover:bg-[#181818] cursor-pointer transition ease-in-out" 
       onClick={() => window.location.href = `/${result.username}`}>
    <div className="relative">
      <img
        src={
          result.profilePicture ?
          `${cloud}/cloudofscubiee/profilePic/${result.profilePicture}` : "/logos/DefaultPicture.png"}
        alt={result.username}
        className="w-10 bg-gray-300 h-10 rounded-full object-cover"
      />
    </div>
    <div>
      <div className="flex items-center">
        <div className="font-semibold text-white">{result.username}</div>
        {result.Verified && (
          <RiVerifiedBadgeFill className="text-blue-500 h-[13px] w-[13px] ml-1" />
        )}
      </div>
      <div className="text-gray-400">{result.firstName} {result.lastName}</div>
    </div>
  </div>
)}
                  
                  {selectedOption === 'posts' && renderPostItem(result)}
                  
                  {selectedOption === 'tags' && (
                    <div 
                      className="p-3 max-md:p-2 flex items-center space-x-3 hover:bg-[#181818] cursor-pointer transition ease-in-out"
                      onClick={() => handleHashtagSelect(result)}
                    >
                      <FiHash className="text-gray-400 w-5 h-5" />
                      <div>
                        <p className="text-white font-medium text-md">{result.name}</p>
                        <p className="text-gray-400 text-sm">{result.count} Posts</p>
                      </div>
                    </div>
                  )}
                </div>
              ))}
              
              {/* Loading more indicator */}
              {loadingMore && (
                <div className="py-4 flex justify-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-white"></div>
                </div>
              )}
            </div>
          )}
          
          {/* Empty state when no results */}
          {!selectedHashtag && searchTerm && searchResults.length === 0 && !isSearchLoading && !isLoadingHashtag && (
            <div className="mt-10 text-center">
              <p className="text-white text-lg">No results found</p>
              <p className="text-gray-400 mt-2">Try searching for something else</p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
};

export default Search;