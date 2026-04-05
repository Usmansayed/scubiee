import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import axios from 'axios';

const api = import.meta.env.VITE_API_URL ;

export const checkAuth = createAsyncThunk(
  'user/checkAuth',
  async (_, { rejectWithValue }) => {
    try {
      const response = await axios.get(`${api}/search/user-check`, {
        withCredentials: true,
        headers: {
          accessToken: localStorage.getItem("accessToken")
        }
      });
      return response.data;
    } catch (error) {
      return rejectWithValue(error.response.data);
    }
  }
);

const userSlice = createSlice({
  name: 'user',
  initialState: {
    userData: null,
    socketUserId: null, // Add dedicated property for socket user ID
    isPosting: false, // Add isPosting field for upload state
    loading: false,
    error: null,
  },
  reducers: {
    clearUser: (state) => {
      state.userData = null;
      state.socketUserId = null; // Clear socket user ID when user is cleared
      state.isPosting = false; // Clear posting state when user is cleared
    },
    setSocketUserId: (state, action) => {
      // Add action to set the socket user ID
      state.socketUserId = action.payload;
    },
    setIsPosting: (state, action) => {
      // Add action to set the posting state
      state.isPosting = action.payload;
    }
  },
  extraReducers: (builder) => {
    builder
      .addCase(checkAuth.pending, (state) => {
        state.loading = true;
      })      .addCase(checkAuth.fulfilled, (state, action) => {
        state.loading = false;
        state.userData = action.payload;
        // Set the socket user ID when authentication is successful
        if (action.payload && action.payload.id) {
          state.socketUserId = action.payload.id;
        }
        // Check if user data includes isPosting and set it
        if (action.payload && typeof action.payload.isPosting === 'boolean') {
          state.isPosting = action.payload.isPosting;
        }
        state.error = null;
      })
      .addCase(checkAuth.rejected, (state, action) => {
        state.loading = false;
        state.userData = null;
        state.socketUserId = null; // Clear socket user ID on auth rejection
        state.error = action.payload;
      });
  },
});

export const { clearUser, setSocketUserId, setIsPosting } = userSlice.actions;
export default userSlice.reducer;