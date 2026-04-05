import React, { useState, useEffect, useRef,useCallback  } from 'react';
import { FiSend, FiSearch } from 'react-icons/fi';
import { MdGroups } from "react-icons/md";
import CryptoJS from 'crypto-js';
import '../App.css'; // Import the CSS file
import io from 'socket.io-client';
import axios from 'axios';






const CreateGroupBox = () => {
    const [groupName, setGroupName] = useState('')
    const [groupSearchQuery, setGroupSearchQuery] = useState('');
    const [groupSearchResults, setGroupSearchResults] = useState([]);
    const groupNameInputRef = useRef(null); // Track group name input field
    const searchInputRef = useRef(null); // Track search input field
    const [selectedImage, setSelectedImage] = useState(null); // State to store selected image
    const CreateGroupWindow = useRef(null);  
    const [selectedImage2, setSelectedImage2] = useState(null); // State to store selected image

    const cloud = import.meta.env.VITE_CLOUD_URL;


    const handleMemberSelectClick = (user) => {
      setSelectedGroupMembers((prevMembers) => {
        // Check if the user is already in the list to avoid duplicates
        if (!prevMembers.some((member) => member.id === user.id.trim())) {
          return [...prevMembers, { ...user, id: user.id.trim() }]; // Trim any leading/trailing spaces
        }
        return prevMembers;
      });
    
      // Do not clear the search input query to preserve user flow
     
    };
    
    
    const createGroup = async () => {
      if (selectedGroupMembers && groupName && selectedImage) {
        const userIds = selectedGroupMembers.map(user => user.id).sort((a, b) => a - b).join(',');
        const hash = CryptoJS.SHA256(userIds).toString(CryptoJS.enc.Hex);
        const shortHash = hash.substring(0, 16);
    
        try {
          if (!groupName.trim()) {
            alert('Group name is required');
            return;
          }
          if (selectedGroupMembers.length < 2) {
            alert('Please select at least 2 members');
            return;
          }
    
          // Create a FormData object for handling file upload
          const formData = new FormData();
          formData.append('groupName', groupName);
          formData.append('userIds', userIds);
          formData.append('roomId', shortHash);
          formData.append('groupImage', selectedImage2); // Assuming `selectedImage` is a File object
    
          const response = await axios.post('http://localhost:5001/chat/createGroup', formData, {
            withCredentials: true, // Send cookies with the request
            headers: {
              'Content-Type': 'multipart/form-data', // Important for file uploads
            },
          });
    
          if (response.data.success) {
            console.log('Group created successfully');
          } else {
            console.error('Failed to create group');
          }
        } catch (error) {
          console.error('Error creating group:', error);
        }
      } else {
        console.log('Please fill out the full group form');
      }
    };
    
  
// Function to handle image selection
const handleImageChange = (e) => {
  if (e.target.files && e.target.files[0]) {
    const imageFile = e.target.files[0];
    const imageUrl = URL.createObjectURL(imageFile); // Create a URL for the image
    setSelectedImage(imageUrl); // Update the state with the selected image URL
    setSelectedImage2(imageFile)
  }
};
  
    useEffect(() => {
      const handleClickOutside = (event) => {
        if (CreateGroupWindow.current && !CreateGroupWindow.current.contains(event.target)) {
          setShowCreateGroupBox(false);
           setSelectedGroupMembers([]);
           setGroupName('');
           setGroupSearchResults([]);
           setGroupSearchQuery(null);
        }
      };
  
    
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }, [CreateGroupWindow]);

    useEffect(() => {
      if (groupNameInputRef.current && groupName === "") {
        groupNameInputRef.current.focus();
      }
    }, [groupName]);
    
    useEffect(() => {
      if (searchInputRef.current && groupSearchQuery === "") {
        searchInputRef.current.focus();
      }
    }, [groupSearchQuery]);
    
  
    const uploadGroupImage = () => {
      // Your upload logic here
    };
  
    const handleGroupNameChange = useCallback((e) => {
      const name = e.target.value;
      setGroupName(name);
    }, []);
  
    const handleSearchForGroup = useCallback(async (e) => {
      const query = e.target.value;
      setGroupSearchQuery(query);
  
      if (!query.trim()) {
        setGroupSearchResults([]);
        return;
      }
  
      try {
        const response = await axios.post('http://localhost:5001/chat/search', { username: query });
        setGroupSearchResults(response.data);
      } catch (error) {
        console.error('Error searching users:', error);
      }
    }, []);
  
    return (
      <div
        ref={CreateGroupWindow}
        className="flex col-span-2 absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-10 w-[60%] max-xl:w-[40%] h-[64%] bg-[#161616] rounded-3xl border-[1px] border-[#222222] shadow-xl"
      >
        {/* Profile Picture Section */}
        <div className="bg-[#1d3f53] w-[40%] h-full flex flex-col items-center pt-8 rounded-l-3xl">
        <div className="w-full flex justify-center relative">
      {/* Hidden file input */}
      <input
        type="file"
        accept="image/*"
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        onChange={handleImageChange}
      />

      {/* Display "Upload" text if no image is selected, else show the image */}
      <div
        className="rounded-full w-28 h-28 mt-0 border-2 border-[#222222] flex items-center justify-center bg-white text-black"
        style={{
          backgroundImage: selectedImage ? `url(${selectedImage})` : 'none',
          backgroundSize: 'cover',
          backgroundPosition: 'center',
        }}
      >
        {!selectedImage && <span className=' font-semibold text-gray-600 text-[17px]'>Group Icon</span>}
      </div>
    </div>

          <div className="w-full mt-8 px-6">
            <h1 className="text-white text-lg font-semibold mb-4 text-center">Name of Group</h1>
            <input
              type="text"
              className="w-full p-2 bg-[#1f1f1f] rounded-lg text-white placeholder-gray-500 border border-[#333333] focus:outline-none focus:border-[#444444]"
              placeholder="Enter group name"
              value={groupName}
              ref={groupNameInputRef} // Attach ref to group name input
              onChange={handleGroupNameChange}
            />
          </div>
          <div className="w-full mt-6 h-[80%] rounded-b-3xl p-4 text-white text-left overflow-auto">
            {selectedGroupMembers.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {selectedGroupMembers.map((user) => (
                  <div key={user.id} className="text-gray-400 border-2 pr-3 rounded-md px-2 bg-[#183546] flex items-center border-gray-800">
                    <img src={user.profilePicture} alt="" className="w-6 h-6 rounded-full mr-2" />
                    {user.username}
                    <div className='pl-2 pr-[-8px] text-red-700 cursor-pointer' onClick={() => setSelectedGroupMembers((prevMembers) => prevMembers.filter((member) => member.id !== user.id))}>X</div>
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-gray-400 align-middle flex justify-center">No members selected</span>
            )}
          </div>
        </div>
  
        {/* Search and Results Section */}
        <div className="bg-[#1a1a1a] w-[60%] h-full rounded-r-3xl flex flex-col justify-between">
          {/* Search Bar */}
          <div className="flex items-center h-[12%] p-2 relative justify-center">
            <FiSearch className="absolute left-[102px] text-gray-400" size={20} />
            <input
              type="text"
              placeholder="Search Users"
              ref={searchInputRef} // Attach ref to search input
              value={groupSearchQuery}
              onChange={handleSearchForGroup}
              className="w-[70%] p-2 pl-10 bg-[#1f1f1f] rounded-lg text-white placeholder-gray-500 border border-[#333333] focus:outline-none focus:border-[#444444]"
            />
          </div>
  
          {/* Search Results */}
          <div className="w-full h-[70%] px-4 py-2 bg-[#1a1a1a] overflow-y-auto rounded-b-3xl">
            {groupSearchResults.length > 0 ? (
              groupSearchResults.map((user) => (
                <div
                  key={user.id}
                  onClick={() => handleMemberSelectClick(user)}
                  className="p-3 flex items-center space-x-4 hover:bg-[#1f1f1f] cursor-pointer transition ease-in-out rounded-lg"
                >
                  <img
                    src={user.profilePicture}
                    alt={user.name}
                    className="w-10 h-10 rounded-full border border-[#333333]"
                  />
                  <div>
                    <div className="font-semibold text-white">{user.username}</div>
                    <div className="text-gray-400">{user.firstName} {user.lastName}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-white text-center"></div>
            )}
          </div>
          {selectedGroupMembers.length > 0 && groupName !== "" && (
            <div className="w-full p-4 pt-0 flex justify-end bg-[#1a1a1a] rounded-b-3xl">
              <button
                className="bg-[#1d3f53] text-white py-2 px-4 rounded-lg hover:bg-[#183546] transition-colors duration-300"
                onClick={createGroup}
              >
                Create Group
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  export default CreateGroupBox;