const express = require("express");
const router = express.Router();
const passport = require('passport');
const jwt = require('jsonwebtoken');
const { validateToken } = require('../middlewares/AuthMiddleware');
const multer = require('multer'); // For handling file uploads
const path = require('path');
const { Users, Post, Follow, sequelize, Sequelize ,Notifications } = require("../models");
const fs = require('fs');
const { Op } = require("sequelize"); // Add this import
const { uploadToB2, deleteFromB2, generateUniqueFilename } = require('../utils/backblaze');

const Domain = process.env.VITE_DOMAIN ;

// Add reserved usernames that cannot be used
const RESERVED_USERNAMES = [
  'username',
  'complete',
  'chat',
  'shorts',
  'story',
  'notifications',
  'explore',
  'settings',
  'help',
  'support',
  'login',
  'signup',
  'register',
  'home',
  'admin',
  'search',
  'profile',
  'about',
  'terms',
  'privacy',
  'contact',
  'feedback',
  
];

// Secret for JWT
const JWT_SECRET = process.env.JWT_SECRET;

// filepath: /c:/Users/usman/Videos/Real Projects/server/routes/Users.js
const generateToken = (user) => {
  return jwt.sign(
    { 
      id: user.id, 
      username: user.username,
      email: user.email, 
      firstName: user.firstName, 
      lastName: user.lastName, 
      profilePicture: user.profilePicture
    }, 
    JWT_SECRET, 
    { expiresIn: '6w' }
  );
};

// Function to decode JWT
const decodeToken = (token) => {
  const decoded = jwt.verify(token, JWT_SECRET);
  return decoded;
};

// Add a simpler URL generation function that takes context into account
function generateMediaUrl(filename, type) {
  if (!filename) return null;
  // Return as-is if it's already a full URL
  if (filename.startsWith('http')) return filename;
  
  const bucketName = process.env.BUCKET_NAME;
  // Determine folder based on media type
  let folder = 'media';
  if (type === 'profile') folder = 'profilePic';
  else if (type === 'cover') folder = 'coverImages';
  
  return `https://f002.backblazeb2.com/file/${bucketName}/${folder}/${filename}`;
}

// Add new endpoint to get user by ID
router.get('/getUserById/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    
    if (!userId) {
      return res.status(400).json({ 
        success: false, 
        message: 'User ID is required' 
      });
    }

    const user = await Users.findOne({
      where: { id: userId },
      attributes: [
        'id', 'username', 'firstName', 'lastName', 'profilePicture', 
        'coverImage', 'bio', 'verified'
      ]
    });

    if (!user) {
      return res.status(404).json({ 
        success: false, 
        message: 'User not found' 
      });
    }

    return res.json({
      success: true,
      user
    });
  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Server error while getting user'
    });
  }
});

// Google OAuth routes
router.get('/google', passport.authenticate('google', { scope: ['email', 'profile'] }));

router.get('/google/callback',
  passport.authenticate('google', { failureRedirect: '/auth/google/failure' }),
  async (req, res) => {
    const redirectReplace = (url) => {
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, private');
      return res.send(`
        <html>
          <head>
            <script>
              console.log('OAuth callback script running');
              console.log('Window opener exists:', !!window.opener);
              
              if (window.opener) {
                try {
                  // Send message to original tab
                  console.log('Sending message to opener with URL:', '${url}');
                  window.opener.postMessage({ type: 'oauth-success', url: '${url}' }, '${Domain}');
                  console.log('Message sent, closing window');
                  // Close this tab
                  window.close();
                } catch(err) {
                  console.error('Error in communication:', err);
                  window.location.replace('${url}');
                }
              } else {
                // Fallback if opener is not available
                console.log('No window.opener, redirecting normally');
                window.location.replace('${url}');
              }
            </script>
          </head>
          <body>
            Authentication successful. Redirecting...
          </body>
        </html>
      `);
    };

    if (req.existingUser) {
      const token = generateToken(req.existingUser);
      res.cookie('access_token', token, { 
        httpOnly: true, 
        secure: false, 
        maxAge: 1209600000 
      });
      return redirectReplace(`${Domain}/`);
    }

    let userData = req.session?.tempUserData;
    if (!userData) {
      userData = req.cookies.temp_user_data ? JSON.parse(req.cookies.temp_user_data) : null;
    }

    if (userData && userData.email) {
      try {
        const user = await Users.findOne({ where: { email: userData.email } });
        
        if (user) {
          const token = generateToken(user);
          res.cookie('access_token', token, { 
            httpOnly: true, 
            secure: false, 
            maxAge: 1209600000 
          });

          if (req.session?.tempUserData) delete req.session.tempUserData;
          if (req.cookies.temp_user_data) res.clearCookie('temp_user_data');

          return redirectReplace(`${Domain}/`);
        } else {
          return redirectReplace(`${Domain}/complete`);
        }
      } catch (error) {
        return redirectReplace(`${Domain}/complete`);
      }
    } else {
      return redirectReplace(`${Domain}/complete`);
    }
  }
);

router.get('/google/failure', (req, res) => {
  res.send('Failed to authenticate with Google');
});



// Set up multer storage for file uploads
const storage = multer.memoryStorage();

const upload = multer({ 
  storage,
  limits: {
    fileSize: 10 * 1024 * 1024, // 10MB in bytes
  },
  fileFilter: (req, file, cb) => {
    // Check for allowed image file types
    const allowedMimeTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    
    if (allowedMimeTypes.includes(file.mimetype)) {
      cb(null, true);
    } else {
      cb(new Error('Only JPG, JPEG, and PNG image files are allowed'), false);
    }
  }
});

router.post('/complete-profile', upload.single('profilePic'), async (req, res) => {
  try {
    // Destructure the fields
    const { username, complete, firstName, lastName, categories, state } = req.body;
    const tempUserData = req.cookies.temp_user_data ? JSON.parse(req.cookies.temp_user_data) : null;

    // Backend validation
    const usernameRegex = /^[a-zA-Z0-9._]+$/;
    
    // Validation checks
    if (!username || username.length < 4 || username.length > 16 || !usernameRegex.test(username)) {
      return res.status(400).json({ 
        success: false, 
        message: 'Username must be 4-16 characters and can only contain letters, numbers, periods, and underscores' 
      });
    }
    
    // Check if username is reserved
    const isReserved = RESERVED_USERNAMES.some(
      reserved => reserved.toLowerCase() === username.toLowerCase()
    );
    
    if (isReserved) {
      return res.status(400).json({ 
        success: false, 
        message: 'This username is reserved and cannot be used.' 
      });
    }
    
    // Check if username is already taken
    try {
      const existingUser = await Users.findOne({ where: { username } });
      if (existingUser) {
        return res.status(400).json({
          success: false,
          message: 'This username is already taken. Please choose another one.'
        });
      }
    } catch (error) {
      return res.status(500).json({
        success: false,
        message: 'Error checking username availability'
      });
    }
    
    if (!firstName || firstName.length > 20) {
      return res.status(400).json({ 
        success: false, 
        message: 'First name cannot exceed 20 characters' 
      });
    }
    
    // Rest of the function remains the same...
    
    if (!lastName || lastName.length > 20) {
      return res.status(400).json({ 
        success: false, 
        message: 'Last name cannot exceed 20 characters' 
      });
    }

    if (tempUserData) {
      try {
        // Parse categories JSON if available
        const parsedCategories = categories ? JSON.parse(categories) : null;
        
        // Upload profile picture to B2 if provided
        let profilePicture = null;
        if (req.file) {
          const filename = generateUniqueFilename(req.file.originalname);
          const result = await uploadToB2(req.file.buffer, filename, 'profilePic');
          
          // Store only the filename
          profilePicture = filename;
        }
        
        const user = await Users.create({
          username,
          complete,
          password: null,
          email: tempUserData.email,
          firstName,
          lastName,
          state,
          profilePicture, // Now it's just the filename
          intrest: parsedCategories 
        });

        res.clearCookie('temp_user_data');
        const token = generateToken(user);
        res.cookie('access_token', token, { httpOnly: true, secure: false, maxAge: 1209600000 });
        res.json({ success: true });
      } catch (error) {
        // Check if error is from multer
        if (error.message.includes('Only JPG, JPEG, and PNG')) {
          return res.status(400).json({ 
            success: false, 
            message: 'Only JPG, JPEG, and PNG image files are allowed'
          });
        }
        
        res.status(500).json({ 
          success: false, 
          message: 'Error saving user details',
          error: error.message 
        });
      }
    } else {
      res.status(400).json({ success: false, message: 'No temporary user data found' });
    }
  } catch (error) {
    // Check if error is from multer
    if (error.message.includes('Only JPG, JPEG, and PNG')) {
      return res.status(400).json({ 
        success: false, 
        message: 'Only JPG, JPEG, and PNG image files are allowed'
      });
    }
    
    res.status(500).json({ 
      success: false, 
      message: 'Error saving user details',
      error: error.message 
    });
  }
});

router.get('/user', async (req, res) => {
  const token = req.cookies.access_token;
  if (!token) {
    return res.status(401).json({ message: 'No token provided' });
  }

  try {
    const decoded = decodeToken(token);
    const user = await Users.findByPk(decoded.id);
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    res.json(user);
  } catch (error) {
    res.status(401).json({ message: 'Invalid token' });
  }
});


router.get('/check-complete', async (req, res) => {
  const { complete } = req.query;

  try {
    const user = await Users.findOne({ where: { complete } });

    if (user) {
      return res.json({ available: false });
    } else {
      return res.json({ available: true });
    }
  } catch (error) {
    return res.status(500).json({ message: 'Internal server error' });
  }
});

// Updated route to check username availability - works with or without authentication
router.get('/check-username', async (req, res) => {
  const { username } = req.query;
  let userId = null;
  
  // Optional token validation - if token exists, get userId
  const token = req.cookies?.access_token;
  if (token) {
    try {
      const decoded = jwt.verify(token, JWT_SECRET);
      userId = decoded.id;
    } catch (error) {
      // Invalid token, proceeding as unauthenticated request
    }
  }
  
  if (!username) {
    return res.status(400).json({ message: 'Username parameter is required', available: false });
  }
  
  // Check if the username is in the reserved list (case insensitive)
  const isReserved = RESERVED_USERNAMES.some(
    reserved => reserved.toLowerCase() === username.toLowerCase()
  );
  
  if (isReserved) {
    return res.json({ 
      available: false,
      message: 'This username is reserved and cannot be used.' 
    });
  }
  
  try {
    // Find user with this username
    const existingUser = await Users.findOne({ where: { username } });
    
    // If no user exists with this username, it's available
    if (!existingUser) {
      return res.json({ available: true });
    }
    
    // If userId exists (user is authenticated) and the username belongs to them, it's available
    if (userId && existingUser.id === userId) {
      return res.json({ available: true });
    }
    
    // Otherwise, the username is taken by someone else
    return res.json({ available: false });
    
  } catch (error) {
    return res.status(500).json({ 
      message: 'Internal server error while checking username availability',
      available: false 
    });
  }
});

router.post('/edit-profile', validateToken, upload.fields([
  { name: 'profilePic', maxCount: 1 },
  { name: 'coverImage', maxCount: 1 },
]), async (req, res) => {
  const { firstName, lastName, username, complete, bio, socialLinks } = req.body;
  const userId = req.user.id;
  
  // Backend validation
  if (firstName && firstName.length > 20) {
    return res.status(400).json({ 
      success: false, 
      message: 'First name cannot exceed 20 characters' 
    });
  }
  
  if (lastName && lastName.length > 20) {
    return res.status(400).json({ 
      success: false, 
      message: 'Last name cannot exceed 20 characters' 
    });
  }
  
  if (username) {
    // Username format validation
    const usernameRegex = /^[a-zA-Z0-9._]+$/;
    if (username.length < 4 || username.length > 16 || !usernameRegex.test(username)) {
      return res.status(400).json({
        success: false,
        message: 'Username must be 4-16 characters and can only contain letters, numbers, periods, and underscores'
      });
    }
    
    // Check if username is in reserved list
    const isReserved = RESERVED_USERNAMES.some(
      reserved => reserved.toLowerCase() === username.toLowerCase()
    );
    
    if (isReserved) {
      return res.status(400).json({ 
        success: false, 
        message: 'This username is reserved and cannot be used.' 
      });
    }
    
    // Check if username is already taken by another user
    try {
      const existingUser = await Users.findOne({ 
        where: { 
          username,
          id: { [Op.ne]: userId } // Exclude current user
        } 
      });
      
      if (existingUser) {
        return res.status(400).json({
          success: false,
          message: 'This username is already taken. Please choose another one.'
        });
      }
    } catch (error) {
      return res.status(500).json({
        success: false,
        message: 'Error checking username availability'
      });
    }
  }
  
  const profilePicFile = req.files['profilePic'] ? req.files['profilePic'][0] : null;
  const coverImageFile = req.files['coverImage'] ? req.files['coverImage'][0] : null;

  try {
    const user = await Users.findOne({ where: { id: userId } });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }

    let profilePicture = user.profilePicture;
    let coverImage = user.coverImage;
    let uploadErrors = [];

    try {
      // Upload new profile picture if provided
      if (profilePicFile) {
        
        try {
          // Delete old profile picture if exists
          if (user.profilePicture) {
            try {
              await deleteFromB2(user.profilePicture, 'profilePic');
            } catch (deleteError) {
            }
          }
          
          // Upload new profile picture
          const filename = generateUniqueFilename(profilePicFile.originalname);
          const result = await uploadToB2(profilePicFile.buffer, filename, 'profilePic');
          
          // Store just the filename
          profilePicture = filename;
          
          if (result.isLocalFallback) {
          } else {
          }
        } catch (uploadError) {
          uploadErrors.push("Profile picture: " + uploadError.message);
          // Continue with other updates even if profile pic upload fails
        }
      }
      
      // Upload new cover image if provided
      if (coverImageFile) {
        
        try {
          // Delete old cover image if exists
          if (user.coverImage) {
            try {
              await deleteFromB2(user.coverImage, 'coverImages');
            } catch (deleteError) {
            }
          }
          
          // Upload new cover image
          const filename = generateUniqueFilename(coverImageFile.originalname);
          const result = await uploadToB2(coverImageFile.buffer, filename, 'coverImages');
          
          // Store just the filename
          coverImage = filename;
          
          if (result.isLocalFallback) {
          } else {
          }
        } catch (uploadError) {
          uploadErrors.push("Cover image: " + uploadError.message);
          // Continue with other updates even if cover image upload fails
        }
      }
    } catch (uploadError) {
      console.error('File upload error:', uploadError);
      uploadErrors.push("General upload error: " + uploadError.message);
      // Continue with profile update even if uploads fail
    }

    const updatedData = {
      firstName: firstName || user.firstName,
      lastName: lastName || user.lastName,
      username: username || user.username,
      complete: complete || user.complete,
      Bio: bio !== undefined ? bio : user.Bio,
      SocialMedia: socialLinks !== 'null' ? socialLinks : user.SocialMedia,
      profilePicture: profilePicture,
      coverImage: coverImage
    };

    await user.update(updatedData);
    
    // Get the updated user to generate a token with the new data
    const updatedUser = await Users.findOne({ where: { id: userId } });
    const updatedToken = generateToken(updatedUser);
    
    res.cookie('access_token', updatedToken, {
      httpOnly: true,
      secure: false,
      maxAge: 1209600000,
    });
    
    const response = { 
      success: true, 
      message: 'Profile updated successfully', 
      user: updatedUser 
    };
    
    if (uploadErrors.length > 0) {
      response.warnings = uploadErrors;
    }
    
    res.json(response);
    
  } catch (error) {
    // Check if error is from multer
    if (error.message.includes('Only JPG, JPEG, and PNG')) {
      return res.status(400).json({ 
        success: false, 
        message: 'Only JPG, JPEG, and PNG image files are allowed'
      });
    }
    
    console.error('Profile update error:', error);
    res.status(500).json({ 
      message: 'Error updating profile',
      error: error.message 
    });
  }
});

router.get('/profile-info', validateToken, async (req, res) => {
  const username = req.query.username || req.user.username;
  const userId = req.user.id;

  try {    // Find user with all relevant information
    const user = await Users.findOne({
      where: { username: username },      attributes: [
        'id',
        'username', 
        'firstName', 
        'lastName',
        'badges',
        'Verified',
        'Bio', 
        'SocialMedia', 
        'profilePicture',
        'coverImage',
        'followers',
        'following',
        'posts',
        'state',
        'isPosting'
      ]
    });

    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }

    // Check if the logged-in user follows this profile
    let followedByMe = false;
    if (req.query.username) { // Only check if viewing another user's profile
      const followRelation = await Follow.findOne({
        where: {
          followerId: userId,
          followingId: user.id
        }
      });
      followedByMe = !!followRelation;
    }

    // Convert stored filenames to full URLs for client
    const userData = user.dataValues;
    
    // Generate profile picture URL if available
    userData.profilePictureUrl = generateMediaUrl(userData.profilePicture, 'profile');
    
    // Generate cover image URL if available
    userData.coverImageUrl = generateMediaUrl(userData.coverImage, 'cover');

    res.json({
      user: {
        ...userData,
        followedByMe
      }
    });
    
  } catch (error) {
    res.status(500).json({ message: 'Error fetching profile information' });
  }
});

// Search route
router.post('/search', async (req, res) => {
  const { complete } = req.body;
  if (!complete) {
    return res.status(400).json({ error: "Username is required" });
  }

  try {
    const users = await Users.findAll({
      attributes: ['id', 'complete', 'firstName', 'lastName', 'profilePicture']
    });

    const fuse = new Fuse(users, {
      keys: ["complete"],
      threshold: 0.3,
    });

    const results = fuse.search(complete);
    res.json(results.map(result => result.item));
  } catch (error) {
    res.status(500).json({ error: "Internal server error" });
  }
});

// GET search route for communities and other features
router.get('/search', async (req, res) => {
  const { q, limit = 10 } = req.query;
  
  if (!q) {
    return res.status(400).json({ error: "Search query is required" });
  }

  try {
    const users = await Users.findAll({
      where: {
        [Op.or]: [
          { username: { [Op.like]: `%${q}%` } },
          { firstName: { [Op.like]: `%${q}%` } },
          { lastName: { [Op.like]: `%${q}%` } }
        ]
      },
      attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture'],
      limit: parseInt(limit)
    });

    res.json({ users });
  } catch (error) {
    console.error('Error searching users:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});


router.post('/follow/:userId', validateToken, async (req, res) => {
  try {
    const followerId = req.user.id;  // Logged in user's ID
    const followingId = req.params.userId; // User to follow's ID

    // Check if already following
    const existingFollow = await Follow.findOne({
      where: {
        followerId,
        followingId
      }
    });

    if (existingFollow) {
      return res.status(400).json({ message: 'Already following this user' });
    }

    // Use transaction to ensure data consistency
    await sequelize.transaction(async (t) => {
      // Create follow relationship
      await Follow.create({
        followerId,
        followingId
      }, { transaction: t });

      // Update follower's following count
      await Users.increment('following', {
        where: { id: followerId },
        transaction: t
      });

      // Update followed user's followers count
      await Users.increment('followers', {
        where: { id: followingId },
        transaction: t
      });
      
      // Create a notification for the user being followed
      await sequelize.models.Notifications.create({
        user_id: followingId,        // The user receiving the notification (who was followed)
        sender_id: followerId,       // The user who followed (current user)
        type: 'follow',              // Type is follow
        reference_id: null,          // No specific post/comment reference for follows
        reference_type: null,        // No reference type needed
        message: 'started following you',
        is_read: false
      }, { transaction: t });
    });

    // If you have socket.io set up, emit notification here
    if (req.io) {
      req.io.to(followingId).emit('notification', {
        type: 'follow',
        senderId: followerId,
        message: 'started following you'
      });
    }

    // If you have socket.io set up with enhanced emit, use it here
    if (req.io && req.io.emitWithSender) {
      req.io.emitWithSender('notification', followingId, {
        type: 'follow',
        senderId: followerId,
        message: 'started following you'
      }, Users);
    }

    res.status(200).json({ message: 'Successfully followed user' });
  } catch (error) {
    res.status(500).json({ message: 'Error following user' });
  }
});
router.delete('/follow/:userId', validateToken, async (req, res) => {
  try {
    const followerId = req.user.id;
    const followingId = req.params.userId;

    // Use transaction to ensure data consistency
    await sequelize.transaction(async (t) => {
      // Remove follow relationship
      const result = await Follow.destroy({
        where: {
          followerId,
          followingId
        },
        transaction: t
      });

      if (result === 0) {
        return res.status(404).json({ message: 'Follow relationship not found' });
      }

      // Update follower's following count
      await Users.decrement('following', {
        where: { id: followerId },
        transaction: t
      });

      // Update followed user's followers count
      await Users.decrement('followers', {
        where: { id: followingId },
        transaction: t
      });
      
      // Remove any follow notifications
      await sequelize.models.Notifications.destroy({
        where: {
          sender_id: followerId,
          user_id: followingId,
          type: 'follow'
        },
        transaction: t
      });
      
      // Emit socket event to update notifications in real-time
      if (req.io) {
        req.io.to(followingId.toString()).emit('notification_remove', {
          type: 'follow',
          senderId: followerId
        });
      }
    });

    res.status(200).json({ message: 'Successfully unfollowed user' });
  } catch (error) {
    res.status(500).json({ message: 'Error unfollowing user' });
  }
});

// Add this route that returns all users
router.get('/getAllUsers', validateToken, async (req, res) => {
  try {
    const users = await Users.findAll({
      attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture', 'verified'],
      limit: 100 // Limit the result to prevent large data transfer
    });
    
    return res.json(users);
  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Server error while getting users'
    });
  }
});

// Replace this route with an improved version
router.get('/follows', validateToken, async (req, res) => {
  try {
    const { userId, username, fetchType, page = 0, limit = 10 } = req.query;
    
    // Ensure page and limit are valid numbers
    const pageNum = parseInt(page) || 0;
    const limitNum = parseInt(limit) || 10;
    const offset = pageNum * limitNum;
    const currentUserId = req.user.id;
    
    if (!userId) {
      return res.status(400).json({ 
        success: false, 
        message: 'User ID is required' 
      });
    }

    // Determine if the profile belongs to the current user
    const isOwnProfile = userId === currentUserId;
    
    // First, find all followers/following IDs using Sequelize models
    let followsRelations;
    if (fetchType === 'followers') {
      followsRelations = await Follow.findAll({
        attributes: ['followerId'],
        where: { followingId: userId },
        raw: true
      });
    } else {
      followsRelations = await Follow.findAll({
        attributes: ['followingId'],
        where: { followerId: userId },
        raw: true
      });
    }

    // If no follows found
    if (!followsRelations || followsRelations.length === 0) {
      return res.json({
        success: true,
        users: [],
        hasMore: false,
        total: 0
      });
    }
    
    // Extract IDs
    const idField = fetchType === 'followers' ? 'followerId' : 'followingId';
    const followIds = followsRelations.map(relation => relation[idField]).filter(Boolean);
    
    // If there are no valid IDs after filtering, return empty results
    if (followIds.length === 0) {
      return res.json({
        success: true,
        users: [],
        hasMore: false,
        total: 0
      });
    }
    
    // Find mutual followers if this is not the current user's profile
    let mutualFollowersIds = [];
    if (!isOwnProfile) {
      try {
        // Find users who the profile user is following
        const profileFollowing = await Follow.findAll({
          attributes: ['followingId'],
          where: { followerId: userId },
          raw: true
        });
        
        // Find users who the current user is following
        const currentUserFollowing = await Follow.findAll({
          attributes: ['followingId'],
          where: { followerId: currentUserId },
          raw: true
        });
        
        // Extract IDs
        const profileFollowingIds = profileFollowing.map(f => f.followingId).filter(Boolean);
        const currentUserFollowingIds = currentUserFollowing.map(f => f.followingId).filter(Boolean);
        
        // Find the intersection (mutual follows)
        mutualFollowersIds = profileFollowingIds.filter(id => 
          currentUserFollowingIds.includes(id)
        );
      } catch (error) {
        mutualFollowersIds = [];
      }
    }

    // Create literals for the extra columns we want to select
    const mutualFollowersLiteral = Sequelize.literal(`(
      SELECT COUNT(*) FROM Follows f1
      INNER JOIN Follows f2 ON f1.followingId = f2.followingId
      WHERE f1.followerId = '${currentUserId}' AND f2.followerId = Users.id 
      AND f1.followerId != f2.followerId
    )`);

    const followedByMeLiteral = Sequelize.literal(`(
      SELECT COUNT(*) > 0 FROM Follows 
      WHERE followerId = '${currentUserId}' AND followingId = Users.id
    )`);

    const isCurrentUserLiteral = Sequelize.literal(`(
      Users.id = '${currentUserId}'
    )`);

    // Create order array based on priorities
    let order = [];
    
    if (isOwnProfile) {
      // For own profile: Prioritize verified users first
      order.push(['Verified', 'DESC']);
    } else if (mutualFollowersIds.length > 0) {
      // Create a case statement for ordering by mutual followers
      // Only if we actually have mutual followers
      const mutualFollowersIdsString = mutualFollowersIds.map(id => `'${id}'`).join(',');
      const mutualCaseStatement = Sequelize.literal(
        `CASE WHEN Users.id IN (${mutualFollowersIdsString}) THEN 1 ELSE 0 END DESC`
      );
      order.push([mutualCaseStatement]);
      order.push(['Verified', 'DESC']);
    } else {
      // If no mutual followers, just sort by verified
      order.push(['Verified', 'DESC']);
    }
    
    // Always add creation date to the end
    order.push(['createdAt', 'DESC']);

    // Fetch users with proper attributes and ordering
    const users = await Users.findAll({
      attributes: [
        'id', 
        'username', 
        'firstName', 
        'lastName', 
        'profilePicture', 
        'Verified',
        [mutualFollowersLiteral, 'mutualFollowers'],
        [followedByMeLiteral, 'followedByMe'],
        [isCurrentUserLiteral, 'isCurrentUser']
      ],
      where: {
        id: {
          [Op.in]: followIds  // Use the imported Op.in
        }
      },
      order,
      limit: limitNum,
      offset,
      raw: true
    });

    // Count total for pagination
    const totalCount = await Follow.count({
      where: fetchType === 'followers' 
        ? { followingId: userId } 
        : { followerId: userId },
      distinct: true,
      col: fetchType === 'followers' ? 'followerId' : 'followingId'
    });
    
    const hasMore = offset + users.length < totalCount;

    res.json({
      success: true,
      users,
      hasMore,
      total: totalCount
    });
    
  } catch (error) {
    res.status(500).json({
      success: false,
      message: 'Server error while fetching follows data',
      error: error.message
    });
  }
});

// Logout route to clear the access token cookie
router.post('/logout', (req, res) => {
  try {
    // Clear the access_token cookie
    res.clearCookie('access_token', {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict'
    });
    
    return res.status(200).json({
      success: true,
      message: 'Logged out successfully'
    });
  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Server error during logout'
    });
  }
});

// Route to check if user has unread notifications
router.get('/unread-notifications', validateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    
    // Count unread notifications for this user
    const unreadCount = await sequelize.models.Notifications.count({
      where: {
        user_id: userId,
        is_read: false
      }
    });
    
    return res.json({
      hasUnread: unreadCount > 0,
      count: unreadCount
    });
  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Server error while checking notifications'
    });
  }
});

// Add new endpoint to check if temp_user_data cookie exists
router.get('/check-temp-data', (req, res) => {
  try {
    // Check if the cookie exists
    const tempUserData = req.cookies.temp_user_data ? 
      JSON.parse(req.cookies.temp_user_data) : null;
    
    return res.json({
      exists: !!tempUserData,
      // Optionally include the email if you need it
      email: tempUserData?.email || null
    });
  } catch (error) {
    return res.status(500).json({
      success: false,
      message: 'Error checking temporary user data',
      exists: false
    });
  }
});

// User suggestions route - fix for the limit issue
router.get('/suggestions', validateToken, async (req, res) => {
  try {
    const  limit = 4 ;
    const limitNum = parseInt(limit) || 4;
    const userId = req.user.id;
    
    // Get users the current user is already following
    const currentUserFollowings = await Follow.findAll({
      attributes: ['followingId'],
      where: { followerId: userId },
      raw: true
    });
    
    // Create an array of IDs to exclude (users already followed + self)
    const excludeIds = [...currentUserFollowings.map(f => f.followingId), userId];
    
    // PRIORITY 1: Users who follow you but you don't follow back
    const followersNotFollowed = await Follow.findAll({
      attributes: ['followerId'],
      where: {
        followingId: userId,
        followerId: {
          [Op.notIn]: excludeIds
        }
      },
      // Adjust to fetch slightly fewer for priority 1 to ensure we don't go over the limit
      limit: Math.floor(limitNum * 0.7), // Changed from Math.ceil to Math.floor
      raw: true
    });
    
    const priority1Ids = followersNotFollowed.map(f => f.followerId);
    
    // Get remaining count needed
    const remaining = Math.max(0, limitNum - priority1Ids.length);
    let priority2Ids = [];
    
    if (remaining > 0) {
      // PRIORITY 2: Get followings of your followings
      const yourFollowings = await Follow.findAll({
        attributes: ['followingId'],
        where: { followerId: userId },
        raw: true
      });
      
      const followingIds = yourFollowings.map(f => f.followingId);
      
      if (followingIds.length > 0) {
        // Find users followed by those you follow
        const followingsOfFollowings = await Follow.findAll({
          attributes: ['followingId'],
          where: {
            followerId: {
              [Op.in]: followingIds
            },
            followingId: {
              [Op.notIn]: [...excludeIds, ...priority1Ids]
            }
          },
          limit: remaining, // Exactly the remaining slots needed
          raw: true
        });
        
        priority2Ids = followingsOfFollowings.map(f => f.followingId);
      }
    }
    
   // Combine all suggestion IDs (no duplicates)
let allSuggestionIds = [...priority1Ids, ...priority2Ids];

// If we still don't have enough, get random users to fill all remaining slots
if (allSuggestionIds.length < limitNum) {
  const neededRandom = limitNum - allSuggestionIds.length;

  const randomUsers = await Users.findAll({
    attributes: ['id'],
    where: {
      id: {
        [Op.notIn]: [...excludeIds, ...allSuggestionIds]
      }
    },
    order: Sequelize.literal('RAND()'),
    limit: neededRandom,
    raw: true
  });

  const randomIds = randomUsers.map(u => u.id);
  allSuggestionIds = [...allSuggestionIds, ...randomIds];
}

// Only slice at the very end, after all priorities and randoms are combined
const limitedSuggestionIds = allSuggestionIds.slice(0, limitNum);
    
    // If we have any suggestions, fetch user details
    if (limitedSuggestionIds.length > 0) {
      // Get the followingIds for the sequelize subqueries
      const yourFollowingsForSubQueries = await Follow.findAll({
        attributes: ['followingId'],
        where: { followerId: userId },
        raw: true
      });
      
      const followingIdList = yourFollowingsForSubQueries.map(f => f.followingId);
      
      // Fetch user details - using multiple separate queries instead of SQL literals
      const suggestedUsers = await Users.findAll({
        attributes: [
          'id', 
          'username', 
          'firstName', 
          'lastName', 
          'profilePicture', 
          'Verified'
        ],
        where: {
          id: {
            [Op.in]: limitedSuggestionIds
          }
        },
        order: [
          ['Verified', 'DESC']
        ],
        raw: true,
        limit: limitNum // Ensure we don't get more than requested
      });
      
      // Fetch additional data for each user separately
      const processedSuggestions = await Promise.all(
        suggestedUsers.map(async (user) => {
          // Count how many people you follow also follow this user
          const followedByYourFollowings = await Follow.count({
            where: {
              followerId: {
                [Op.in]: followingIdList
              },
              followingId: user.id
            }
          });
          
          // Check if this user follows you
          const followsYou = await Follow.count({
            where: {
              followerId: user.id,
              followingId: userId
            }
          });
          
          // Determine suggestion reason
          let reason = "Suggested for you";
          
          if (priority1Ids.includes(user.id)) {
            reason = "Follows you";
          } else if (followedByYourFollowings > 0) {
            // Get one specific user who follows this suggested user
            const followerDetail = await Follow.findOne({
              where: {
                followerId: {
                  [Op.in]: followingIdList
                },
                followingId: user.id
              },
              include: [{
                model: Users,
                as: 'follower',
                attributes: ['username']
              }],
              raw: false
            });
            
            if (followerDetail && followerDetail.follower) {
              reason = `Followed by ${followerDetail.follower.username}`;
            } else {
              reason = "Followed by people you follow";
            }
          }
          
          // Return user with additional data (but NO URL construction)
          return {
            ...user,
            followedByYourFollowings,
            followsYou: followsYou > 0,
            reason
          };
        })
      );
      // Sort the processed suggestions as needed
      processedSuggestions.sort((a, b) => {
        // First by verified status
        if (a.Verified !== b.Verified) return b.Verified - a.Verified;
        // Then by number of mutual connections
        return b.followedByYourFollowings - a.followedByYourFollowings;
      });
      
      // Explicitly limit to requested number
      const limitedSuggestions = processedSuggestions.slice(0, limitNum);
      
      return res.json({
        success: true,
        suggestions: limitedSuggestions
      });
    } else {
      // No suggestions found
      return res.json({
        success: true,
        suggestions: []
      });
    }
    
  } catch (error) {
    console.error('Error in suggestions route:', error);
    return res.status(500).json({
      success: false,
      message: 'Server error while getting suggestions',
      error: error.message
    });
  }
});
module.exports = router;