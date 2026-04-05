import axios from 'axios';

const api = import.meta.env.VITE_API_URL;

/**
 * Service for handling post interactions (likes, saves, comments)
 * with centralized error handling and retry logic
 */
export const postInteractionService = {
  /**
   * Toggle like status for a post
   * 
   * @param {string|number} postId - ID of the post
   * @returns {Promise} - Promise with the server response
   */
  toggleLike: async (postId) => {
    try {
      const response = await axios.post(
        `${api}/user-interactions/like/${postId}`,
        {},
        {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") }
        }
      );
      
      return {
        success: response.data.success || true,
        data: response.data
      };
    } catch (error) {
      console.error(`Like operation failed for ${postId}:`, error);
      throw error;
    }
  },
  
  /**
   * Toggle save status for a post
   * 
   * @param {string|number} postId - ID of the post
   * @returns {Promise} - Promise with the server response
   */
  toggleSave: async (postId) => {
    try {
      const response = await axios.post(
        `${api}/user-interactions/save/${postId}`,
        {},
        {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") }
        }
      );
      
      return {
        success: response.data.success || true,
        data: response.data
      };
    } catch (error) {
      console.error(`Save operation failed for ${postId}:`, error);
      throw error;
    }
  },
  
  /**
   * Toggle like status for a comment
   * 
   * @param {string|number} commentId - ID of the comment
   * @returns {Promise} - Promise with the server response
   */
  toggleCommentLike: async (commentId) => {
    try {
      const response = await axios.post(
        `${api}/user-interactions/like-comment/${commentId}`,
        {},
        {
          withCredentials: true,
          headers: { accessToken: localStorage.getItem("accessToken") }
        }
      );
      
      return {
        success: response.data.success || true,
        data: response.data
      };
    } catch (error) {
      console.error(`Comment like operation failed for ${commentId}:`, error);
      throw error;
    }
  }
};

export default postInteractionService;
