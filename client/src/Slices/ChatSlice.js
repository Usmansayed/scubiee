import { createSlice } from '@reduxjs/toolkit';

const initialState = {
  socket: null,
  selectedUser: null, // Add this

  messages: {},
  onlineUsers: new Set(),
  recentChats: [],
  multiUserPost: null, // store share data: { postId, selectedUsers }

};

const chatSlice = createSlice({
  name: 'chat',
  initialState,
  reducers: {
    removeRecentChat(state, action) {
      state.recentChats = state.recentChats.filter(
        (chat) => chat.chatRoomId !== action.payload
      );
    },
    setSocket(state, action) { 
      state.socket = action.payload; 
    },
    updateOnlineUsers(state, action) { 
      state.onlineUsers = action.payload; 
    },
    setRecentChats(state, action) {
      state.recentChats = action.payload;
    },

    setSelectedUser(state, action) { state.selectedUser = action.payload; },

    updateRecentChat(state, action) {
      const { chatRoomId, updates } = action.payload;
      state.recentChats = state.recentChats.map(chat => 
        chat.chatRoomId === chatRoomId ? { ...chat, ...updates } : chat
      );
    },
    setMultiUserPost(state, action) {
      state.multiUserPost = action.payload;
    },
  },
});

export const { 
  setSocket, 
  setMessages, 
  updateOnlineUsers, 
  setRecentChats, 
  updateRecentChat ,
  setSelectedUser,
  removeRecentChat,
  setMultiUserPost,

} = chatSlice.actions;
export default chatSlice.reducer;