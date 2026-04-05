const express = require("express");
const router = express.Router();
const { 
  Users, 
  Message, 
  postChatRoom, 
  PostHashtags, 
  PostLike, 
  PostSaved, 
  UserChatRooms, 
  Post, 
  Hashtag, 
  Mention, 
  PostRelation, 
  sequelize, 
  StoryMetaData,
  Story,
  Follow,
  StoryView,
  StoryLike,
  Shorts,
  PostView,
  CommunityPosts,
  CommunityMemberships,
  Communities
} = require("../models");
const { validateToken } = require('../middlewares/AuthMiddleware');
const GoogleApi = require('../middlewares/GoogleApi');
const Sequelize = require('sequelize');
const { Op } = Sequelize;
const multer = require('multer'); // For handling file uploads
const path = require('path');
const Fuse = require("fuse.js");
const fs = require('fs');
const { text } = require("stream/consumers");
const { create } = require("domain");
// Replace the old cities import with the enhanced version
const cityDetector = require('../middlewares/EnhancedCities');
// Add this near the top of your file with the other imports
const { uploadToB2, deleteFromB2, generateUniqueFilename } = require('../utils/backblaze');
// Debug flag for location detection
const DEBUG_LOCATION = true;

// Function to detect city/town names in content with enhanced detection
async function detectLocations(content) {
  // Validate input
  if (!content || typeof content !== 'string') {
    if (DEBUG_LOCATION)
    return null;
  }
  
  
  // Use the enhanced city detector
  const location = cityDetector.detectLocation(content);
  
  if (location) {
    if (DEBUG_LOCATION) 
    return location;
  }
  
  if (DEBUG_LOCATION) 
  return null;
}

// Add a test endpoint to verify city detection
router.post('/test-location-detection', validateToken, async (req, res) => {
  const { text } = req.body;
  
  if (!text) {
    return res.status(400).json({ error: "Text is required" });
  }
  
  try {
    const location = await detectLocations(text);
    
    res.json({
      text,
      location,
      success: !!location
    });
  } catch (error) {
    console.error("Error testing location detection:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Test endpoint for AI category detection
router.post('/test-category-detection', validateToken, async (req, res) => {
  const { content } = req.body;
  
  if (!content) {
    return res.status(400).json({ error: "Content is required for testing" });
  }
  
  try {
    console.log("[DEBUG] Testing category detection for:", content.substring(0, 100) + "...");
    const detectedCategories = await GoogleApi.detectPostCategories(content);
    console.log("[DEBUG] AI detected categories:", detectedCategories);
    
    res.json({
      content,
      detectedCategories,
      success: true
    });
  } catch (error) {
    console.error("Error testing category detection:", error);
    res.status(500).json({ 
      error: "Internal server error", 
      fallbackCategories: ["General"],
      success: false 
    });
  }
});

router.get('/shorts-feed', validateToken, async (req, res) => {

  
  try {
    const userId = req.user.id;
    const currentTime = new Date();
    
    // Get mode parameter (hybrid, unviewed, viewed)
    const mode = req.query.mode || 'hybrid';
    
    // Get pagination parameters
    const lastScore = parseFloat(req.query.lastScore) || null;
    const lastCreatedAt = req.query.lastCreatedAt ? new Date(req.query.lastCreatedAt) : null;
    const limit = parseInt(req.query.limit) || 10;
    const firstShortId = req.query.firstShortId || null;
    const lastSeenShortTimestamp = req.query.lastSeenShortTimestamp ? new Date(req.query.lastSeenShortTimestamp) : null;
    
  
    
    // Defaults for hybrid response
    let freshUnviewedShorts = [];
    let standardUnviewedShorts = [];
    let viewedShorts = [];
    let recommendedMode = 'hybrid'; // Default mode recommendation for next fetch

   
    // Step 1: Get current user's data (interests, location, following)
    const currentUser = await Users.findOne({
      where: { id: userId },
      attributes: ['id', 'intrest', 'followers', 'following'],
      raw: true
    });
    
    if (!currentUser) {
      return res.status(404).json({ error: "User not found" });
    }
    
    const userInterests = currentUser.intrest || [];
    
    // Step 2: Get IDs of users the current user follows
    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });
    
    const followingIds = following.map(follow => follow.followingId);
    
    // Step 3: Get IDs of shorts the user has already viewed
    const viewedShortRecords = await PostView.findAll({
      where: { userId },
      attributes: ['postId']
    });
    
    const viewedShortIds = new Set(viewedShortRecords.map(view => view.postId));
    
    // Handle special case: if firstShortId is provided, fetch that short first
    let specificShort = null;
    if (firstShortId) {
      specificShort = await Post.findOne({
        where: { id: firstShortId, isShort: true },
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'Verified', 'followers', 'posts']
        }]
      });
      
      if (!specificShort) {
      } else {
      }
    }
    
    // HYBRID FETCHING STRATEGY
    
    // STEP 1: Fetch fresh unviewed shorts (created after lastSeenShortTimestamp)
    // These are prioritized as they're newest content the user hasn't seen
    const FRESH_SHORTS_LIMIT = 3; // Configurable: number of fresh shorts to fetch
    
    if (lastSeenShortTimestamp && (mode === 'hybrid' || mode === 'unviewed')) {
        freshUnviewedShorts = await Post.findAll({
        where: {
          isShort: true,
          inCommunity: false, // Exclude community-only shorts
          createdAt: { [Op.gt]: lastSeenShortTimestamp },
          id: { [Op.notIn]: Array.from(viewedShortIds) }
        },
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'Verified', 'followers', 'posts']
        }],
        limit: FRESH_SHORTS_LIMIT,
        order: [['createdAt', 'DESC']] // Most recent first
      });
      
    }
    
    // STEP 2: Calculate how many more unviewed shorts we need
    const remainingSlotsAfterFresh = limit - freshUnviewedShorts.length - (specificShort ? 1 : 0);
    
    // STEP 3: Fetch standard unviewed shorts (if we need more)
    if (remainingSlotsAfterFresh > 0 && (mode === 'hybrid' || mode === 'unviewed')) {
      
      // Exclude fresh shorts we already fetched
      const freshShortIds = freshUnviewedShorts.map(short => short.id);
      const excludeIds = [...Array.from(viewedShortIds), ...freshShortIds];
      
      // First prioritize shorts from followed users
      if (followingIds.length > 0) {        const followedUnviewedShorts = await Post.findAll({
          where: { 
            isShort: true,
            inCommunity: false, // Exclude community-only shorts
            authorId: { [Op.in]: followingIds },
            id: { [Op.notIn]: excludeIds }
          },
          include: [{
            model: Users,
            as: 'author',
            attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'Verified', 'followers', 'posts']
          }],
          limit: Math.ceil(remainingSlotsAfterFresh / 2), // Allocate ~half the slots to followed users' shorts
          order: [['createdAt', 'DESC']] 
        });
        
        standardUnviewedShorts = [...standardUnviewedShorts, ...followedUnviewedShorts];
        
        // Add these IDs to exclude list
        excludeIds.push(...followedUnviewedShorts.map(short => short.id));
      }
      
      // Then fetch discovery shorts (from users not followed)
      const remainingSlotsForDiscovery = remainingSlotsAfterFresh - standardUnviewedShorts.length;
      
      if (remainingSlotsForDiscovery > 0) {        const discoveryUnviewedShorts = await Post.findAll({
          where: { 
            isShort: true,
            inCommunity: false, // Exclude community-only shorts
            authorId: { 
              [Op.and]: [
                { [Op.notIn]: [...followingIds, userId] }, // Exclude followed users and self
                { [Op.ne]: null } // Ensure authorId is not null
              ]
            },
            id: { [Op.notIn]: excludeIds }
          },
          include: [{
            model: Users,
            as: 'author',
            attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'Verified', 'followers', 'posts']
          }],
          limit: remainingSlotsForDiscovery,
          order: [['createdAt', 'DESC']] 
        });
        
        standardUnviewedShorts = [...standardUnviewedShorts, ...discoveryUnviewedShorts];
      }
    }
    
    // STEP 4: Fetch viewed shorts as fallback if needed or if mode is 'viewed'
    let needViewedShorts = false;
    const totalUnviewedCount = freshUnviewedShorts.length + standardUnviewedShorts.length + (specificShort ? 1 : 0);
    
    if ((totalUnviewedCount < limit) || mode === 'viewed') {
      needViewedShorts = true;
      const viewedShortsNeeded = limit - totalUnviewedCount;
        // Apply time-based pagination instead of score-based pagination
      // since 'score' isn't a database column
      let viewedWhere = { 
        isShort: true,
        inCommunity: false, // Exclude community-only shorts
        id: { [Op.in]: Array.from(viewedShortIds) }
      };
      
      // Add cursor conditions if provided - use only createdAt for pagination
      if (lastCreatedAt !== null) {
        viewedWhere = {
          ...viewedWhere,
          createdAt: { [Op.lt]: lastCreatedAt }
        };
      }
      
      // Get viewed shorts
      const viewedShortsRows = await Post.findAll({
        where: viewedWhere,
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'Verified', 'followers', 'posts']
        }],
        limit: viewedShortsNeeded,
        order: [['createdAt', 'DESC']] // For viewed shorts, show most recent first
      });
      
      viewedShorts = viewedShortsRows;
    }
    
    // Function to calculate scores for shorts
    const calculateScores = (shorts, type) => {
      return shorts.map(short => {
        const plainShort = short.get({ plain: true });
        
        // Time Decay (40%): Calculate how fresh the post is
        const ageInHours = (currentTime - new Date(plainShort.createdAt)) / (1000 * 60 * 60);
        const timeDecay = Math.exp(-0.05 * ageInHours);
        
        // Engagement Score (40%): Weighted sum of engagement metrics
        const engagementScore = 
          (plainShort.views * 0.10) + 
          (plainShort.likes * 0.15) + 
          (plainShort.comments * 0.25) + 
          (plainShort.shared * 0.25) + 
          (plainShort.bookmarks * 0.25);
        
        const normalizedEngagement = Math.log(engagementScore + 1) / 10;
        
        // Author Credibility (10%)
        const isVerified = plainShort.author.Verified ? 1 : 0;
        const followersFactor = plainShort.author.followers / (plainShort.author.followers + 100);
        const postsFactor = plainShort.author.posts / (plainShort.author.posts + 50);
        
        const authorCredibility = 
          (isVerified * 0.5) + 
          (followersFactor * 0.4) + 
          (postsFactor * 0.1);
        
        // Category Interest Match (5%)
        const categories = plainShort.categories ? 
          (typeof plainShort.categories === 'string' ? plainShort.categories.split(',') : plainShort.categories) : 
          [];
        
        const categoryMatch = categories.some(category => 
          userInterests.includes(category)) ? 1 : 0;
        
        // Location Match (5%)
        const locationMatch = 0; // Default to 0 as we don't have user location in the model
        
        // Content type boost (fresh gets priority)
        const contentTypeBoost = type === 'fresh' ? 0.2 : type === 'standard' ? 0.1 : 0;
        
        // Calculate final score with weights
        const finalScore = 
          (timeDecay * 0.4) + 
          (normalizedEngagement * 0.4) + 
          (authorCredibility * 0.1) + 
          (categoryMatch * 0.05) + 
          (locationMatch * 0.05) + 
          contentTypeBoost;
        
        return {
          ...plainShort,
          score: finalScore,
          contentType: type,
          scoreComponents: {
            timeDecay,
            normalizedEngagement,
            authorCredibility,
            categoryMatch,
            locationMatch,
            contentTypeBoost
          }
        };
      });
    };
    
    // Calculate scores for each group
    let scoredFreshShorts = freshUnviewedShorts.length > 0 ? calculateScores(freshUnviewedShorts, 'fresh') : [];
    let scoredStandardShorts = standardUnviewedShorts.length > 0 ? calculateScores(standardUnviewedShorts, 'standard') : [];
    let scoredViewedShorts = viewedShorts.length > 0 ? calculateScores(viewedShorts, 'viewed') : [];
    
    // Handle the specific short if provided
    let scoredSpecificShort = null;
    if (specificShort) {
      const scoredSpecific = calculateScores([specificShort], 'specific');
      scoredSpecificShort = scoredSpecific[0];
    }
    
    // Sort each category by score
    scoredFreshShorts.sort((a, b) => b.score - a.score);
    scoredStandardShorts.sort((a, b) => b.score - a.score);
    scoredViewedShorts.sort((a, b) => b.score - a.score);
    
    // Combine shorts in priority order
    let rankedShorts = [];
    
    // Add specific short first if requested
    if (scoredSpecificShort) {
      rankedShorts.push(scoredSpecificShort);
    }
    
    // Then add fresh unviewed
    rankedShorts = [...rankedShorts, ...scoredFreshShorts];
    
    // Then add standard unviewed
    rankedShorts = [...rankedShorts, ...scoredStandardShorts];
    
    // Then add viewed shorts if needed
    if (needViewedShorts) {
      rankedShorts = [...rankedShorts, ...scoredViewedShorts];
    }
    
    // Limit to requested amount
    rankedShorts = rankedShorts.slice(0, limit);
    
    // Determine recommended mode for next fetch based on content availability
    if (freshUnviewedShorts.length > 0 || standardUnviewedShorts.length >= limit / 2) {
      recommendedMode = 'hybrid'; // Still have unviewed content, stay in hybrid
    } else if (viewedShortIds.size > 0) {
      recommendedMode = 'viewed'; // Running low on unviewed, switch to viewed
    }
    
    // Process the shorts to include interaction data
    const shortIds = rankedShorts.map(short => short.id);
    
    const [likeRecords, saveRecords, followRecords] = await Promise.all([
      PostLike.findAll({
        where: { userId, postId: { [Op.in]: shortIds } },
        attributes: ['postId']
      }),
      PostSaved.findAll({
        where: { userId, postId: { [Op.in]: shortIds } },
        attributes: ['postId']
      }),
      Follow.findAll({
        where: { 
          followerId: userId, 
          followingId: { [Op.in]: rankedShorts.map(short => short.author.id) }
        },
        attributes: ['followingId']
      })
    ]);
    
    const likedShortIds = new Set(likeRecords.map(record => record.postId));
    const savedShortIds = new Set(saveRecords.map(record => record.postId));
    const followingAuthorIds = new Set(followRecords.map(record => record.followingId));
    
    // Format the final response with pagination info
    const formattedShorts = rankedShorts.map(short => {
      // Flag whether this short has been viewed
      const isViewed = viewedShortIds.has(short.id);
      
      // Remove score components from final output
      const { scoreComponents, contentType, ...shortWithoutScoreComponents } = short;
      
      return {
        ...shortWithoutScoreComponents,
        author: {
          id: short.author.id,
          username: short.author.username,
          profilePicture: short.author.profilePicture,
          fullName: (short.author.firstName || '') + ' ' + (short.author.lastName || ''),
          verified: short.author.Verified
        },
        userInteraction: {
          liked: likedShortIds.has(short.id),
          saved: savedShortIds.has(short.id),
          isFollowing: followingAuthorIds.has(short.author.id),
          viewed: isViewed
        }
      };
    });
    
    // Get cursor values for next page
    const lastShort = formattedShorts.length > 0 ? formattedShorts[formattedShorts.length - 1] : null;
    
    // Create a timestamp for when this batch was fetched
    const currentTimestamp = new Date().toISOString();
    
    const nextCursor = lastShort ? {
      // Remove score from cursor and rely only on creation time for pagination
      lastCreatedAt: lastShort.createdAt,
      lastSeenShortTimestamp: currentTimestamp,
      recommendedMode  // Pass mode recommendation to client
    } : null;
    
    const response = {
      shorts: formattedShorts,
      pagination: {
        limit,
        hasMore: formattedShorts.length === limit,
        nextCursor
      },
      stats: {
        totalFresh: freshUnviewedShorts.length,
        totalStandardUnviewed: standardUnviewedShorts.length,
        totalViewed: viewedShorts.length,
        freshInResponse: scoredFreshShorts.filter(s => rankedShorts.includes(s)).length,
        standardInResponse: scoredStandardShorts.filter(s => rankedShorts.includes(s)).length,
        viewedInResponse: scoredViewedShorts.filter(s => rankedShorts.includes(s)).length
      }
    };
    

    res.json(response);
    
  } catch (error) {
    console.error('==== SHORTS FEED ROUTE ERROR ====');
    console.error('Error fetching shorts feed:', error);
    console.error('Stack trace:', error.stack);
    res.status(500).json({ error: 'Failed to fetch shorts feed', details: error.message });
  }
});

router.get('/user-posts', validateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const type = req.query.type; // 'liked' or 'saved'
    const isShort = req.query.isShort === 'true'; // Filter for shorts or regular posts
    const page = parseInt(req.query.page) || 1;
    const limit = parseInt(req.query.limit) || 10;
    const offset = (page - 1) * limit;
    

    
    // Validate type parameter
    if (type !== 'liked' && type !== 'saved') {
      return res.status(400).json({ error: 'Type must be either "liked" or "saved"' });
    }
    
    // Determine which model to use based on type
    const InteractionModel = type === 'liked' ? PostLike : PostSaved;
    
    // First, get total count for pagination with content type filter
    const totalCount = await InteractionModel.count({
      where: { userId },
      include: [{
        model: Post,
        required: true,
        where: { isShort } // Filter by content type
      }]
    });
    
    
    // Find all interactions with pagination and content type filter, ordered by most recent first
    const interactions = await InteractionModel.findAll({
      where: { userId },
      order: [['createdAt', 'DESC']], // Most recent interactions first
      limit,
      offset,
      include: [{
        model: Post,
        required: true,
        where: { isShort }, // Filter by content type
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'verified']
        }]
      }]
    });
    
    
    // Extract post IDs for additional queries
    const postIds = interactions.map(interaction => interaction.postId);
    
    // Get user interaction data for all posts
    const [likeRecords, saveRecords, followRecords] = await Promise.all([
      PostLike.findAll({
        where: { userId, postId: { [Op.in]: postIds } },
        attributes: ['postId']
      }),
      PostSaved.findAll({
        where: { userId, postId: { [Op.in]: postIds } },
        attributes: ['postId']
      }),
      // Also get follow status for authors
      Follow.findAll({
        where: { 
          followerId: userId, 
          followingId: { [Op.in]: interactions.map(item => item.Post.authorId) }
        },
        attributes: ['followingId']
      })
    ]);
    
    // Create lookup sets for faster checks
    const likedPostIds = new Set(likeRecords.map(record => record.postId));
    const savedPostIds = new Set(saveRecords.map(record => record.postId));
    const followingAuthorIds = new Set(followRecords.map(record => record.followingId));
    
    // Format the response
    const formattedPosts = interactions.map(interaction => {
      const post = interaction.Post.get({ plain: true });
      
      return {
        id: post.id,
        content: post.content,
        thumbnail: post.thumbnail,
        views: post.views,
        likes: post.likes,
        comments: post.comments,
        description: post.description,
        media: post.media || [],
        createdAt: post.createdAt,
        updatedAt: post.updatedAt,
        category: post.category || post.categories,
        shares: post.shared,
        bookmarks: post.bookmarks,
        isShort: post.isShort,
        interactionDate: interaction.createdAt, // When the post was liked/saved
        author: {
          id: post.author.id,
          username: post.author.username,
          profilePicture: post.author.profilePicture,
          fullName: (post.author.firstName || '') + ' ' + (post.author.lastName || ''),
          verified: post.author.verified
        },
        userInteraction: {
          liked: likedPostIds.has(post.id),
          saved: savedPostIds.has(post.id),
          isFollowing: followingAuthorIds.has(post.author.id)
        }
      };
    });
    
    // Create pagination info
    const pagination = {
      page,
      limit,
      totalCount,
      totalPages: Math.ceil(totalCount / limit),
      hasMore: page < Math.ceil(totalCount / limit)
    };
    

    res.json({
      posts: formattedPosts,
      pagination
    });
    
  } catch (error) {
    console.error('==== USER POSTS ROUTE ERROR ====');
    console.error(`Error fetching user posts:`, error);
    console.error('Stack trace:', error.stack);
    res.status(500).json({ error: 'Failed to fetch posts', details: error.message });
  }
});



router.get('/feed', validateToken, async (req, res) => {

  try {
    const userId = req.user.id;
    
    // Get pagination parameters from query string
    const page = parseInt(req.query.page) || 1;
    const limit = parseInt(req.query.limit) || 10;
    const offset = (page - 1) * limit;
    
    // Parse excludeIds if provided
    let excludeIds = [];
    if (req.query.excludeIds) {
      excludeIds = req.query.excludeIds.split(',').filter(id => id.trim() !== '');
    }
    
    // Get IDs of users the current user follows
    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });
    
    // Extract followingIds from the result
    const followingIds = following.map(follow => follow.followingId);
    
    // Add hard-coded user IDs
    followingIds.push('f9b6e0c3-19cd-4362-9e9d-07d41e9e62f7');
    followingIds.push('aff16b9a-8219-42e8-b5fa-e15a97517839');
    followingIds.push('95dc0512-63b6-4f5b-b0ef-eb044574eb2d');
    // Extract followingIds from the result

    
    // Add the user's own ID to include their posts in the feed
    const allRelevantUserIds = [...followingIds, userId];
      // Fetch posts from followed users and user's own posts
    // Adding isShort: false to exclude shorts and inCommunity: false to exclude community-only posts
    const posts = await Post.findAll({
      where: { 
        authorId: { [Op.in]: allRelevantUserIds },
        isShort: false, // This line excludes shorts
        inCommunity: false, // This line excludes community-only posts
        id: { [Op.notIn]: excludeIds } // Exclude already fetched posts
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'verified']
      }],
      order: [['createdAt', 'DESC']],
      limit,
      offset
    });
    
    // Also update the total count query to exclude shorts
    const totalCount = await Post.count({
      where: { 
        authorId: { [Op.in]: allRelevantUserIds },
        isShort: false, // This line excludes shorts from count
        id: { [Op.notIn]: excludeIds } // Exclude already fetched posts
      }
    });
    
    // Check if we need to backfill with prioritized accounts
    // This happens when user has no posts from followings or has scrolled to bottom
    const needBackfill = posts.length < limit || (offset + posts.length >= totalCount && page > 1);
    let backfillPosts = [];

    if (needBackfill) {
      // Priority accounts that get a boost in ranking
      const priorityUsernames = ['scubiee', 'scubiee.india', 'scubiee.karnataka'];
      
      // Find user IDs for these priority accounts
      const priorityUsers = await Users.findAll({
        where: { 
          username: { [Op.in]: priorityUsernames }
        },
        attributes: ['id', 'username']
      });
      
      const priorityUserIds = new Set(priorityUsers.map(user => user.id));
      const priorityUserMap = {};
      priorityUsers.forEach(user => {
        priorityUserMap[user.id] = user.username;
      });
      
      
      // Exclude IDs of posts we already have to avoid duplicates
      const existingPostIds = posts.map(post => post.id);
      
      // Calculate how many additional posts we need
      const backfillLimit = Math.max(limit - posts.length, limit);
      
      // Fetch a larger pool of posts to rank from - all users except those we're already showing
      const backfillPoolSize = backfillLimit * 3; // Get 3x the posts we need so we can rank them
        // Fetch potential backfill posts from the wider pool, excluding already followed users
      const backfillPool = await Post.findAll({
        where: { 
          authorId: { 
            [Op.notIn]: allRelevantUserIds // Don't include users already in main feed
          },
          isShort: false,
          inCommunity: false, // Exclude community-only posts
          ...(existingPostIds.length > 0 && { id: { [Op.notIn]: existingPostIds } })
        },
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'verified', 'followers', 'posts']
        }],
        order: [['createdAt', 'DESC']],
        limit: backfillPoolSize
      });
      
      
      // Rank the posts using a scoring algorithm similar to shorts
      if (backfillPool.length > 0) {
        // Get current time for age calculations
        const currentTime = new Date();
        
        // Calculate scores for each post
        const scoredPosts = backfillPool.map(post => {
          const plainPost = post.get({ plain: true });
          
          // Time Decay (30%): Calculate how fresh the post is
          const ageInHours = (currentTime - new Date(plainPost.createdAt)) / (1000 * 60 * 60);
          const timeDecay = Math.exp(-0.05 * ageInHours);
          
          // Engagement Score (40%): Weighted sum of engagement metrics
          const engagementScore = 
            (plainPost.views * 0.10) + 
            (plainPost.likes * 0.15) + 
            (plainPost.comments * 0.25) + 
            (plainPost.shared * 0.25) + 
            (plainPost.bookmarks * 0.25);
          
          const normalizedEngagement = Math.log(engagementScore + 1) / 10;
          
          // Author Credibility (20%)
          const isVerified = plainPost.author.verified ? 1 : 0;
          const followersFactor = (plainPost.author.followers || 0) / ((plainPost.author.followers || 0) + 100);
          const postsFactor = (plainPost.author.posts || 0) / ((plainPost.author.posts || 0) + 50);
          
          const authorCredibility = 
            (isVerified * 0.5) + 
            (followersFactor * 0.4) + 
            (postsFactor * 0.1);
          
          // Priority Account Boost (10%)
          // Give a significant boost to posts from priority accounts
          const priorityBoost = priorityUserIds.has(plainPost.author.id) ? 1 : 0;
          
          // Calculate final score with weights
          const finalScore = 
            (timeDecay * 0.3) + 
            (normalizedEngagement * 0.4) + 
            (authorCredibility * 0.2) + 
            (priorityBoost * 0.1);
          
          // Return the post with its score
          return {
            ...plainPost,
            score: finalScore,
            isPriorityAccount: priorityUserIds.has(plainPost.author.id),
            priorityUsername: priorityUserMap[plainPost.author.id] || null,
            scoreComponents: {
              timeDecay,
              normalizedEngagement,
              authorCredibility,
              priorityBoost
            }
          };
        });
        
        // Sort by score (highest first)
        scoredPosts.sort((a, b) => b.score - a.score);
        
        // For logging, check how priority accounts performed
        const priorityPostsInTop = scoredPosts.slice(0, backfillLimit)
          .filter(post => post.isPriorityAccount).length;
        
        
        // Take the top scored posts for backfill
        backfillPosts = scoredPosts.slice(0, backfillLimit);
        
        // Log the distribution of scores in our top posts
        const scoreStats = {
          highest: backfillPosts[0]?.score || 0,
          lowest: backfillPosts[backfillPosts.length - 1]?.score || 0,
          average: backfillPosts.reduce((sum, post) => sum + post.score, 0) / backfillPosts.length
        };
        
      }
    }

    // Clean up the backfill posts to match the format of regular posts
    const processedBackfillPosts = backfillPosts.map(post => {
      // Remove the scoring metadata before sending to client
      const { score, isPriorityAccount, priorityUsername, scoreComponents, ...cleanPost } = post;
      
      // Convert back to Sequelize model-like format for consistent processing
      return {
        get: () => ({ plain: true, ...cleanPost }),
        ...cleanPost
      };
    });

    // Combine regular posts with backfill posts
    const allPosts = [...posts, ...processedBackfillPosts];
    const postIds = allPosts.map(post => post.id);
    
    // If user wants interaction data for posts, get likes and saves
    
    // Process likes, saves, and follows in parallel for efficiency
    const [likeRecords, saveRecords, followRecords] = await Promise.all([
      PostLike.findAll({
        where: { userId, postId: { [Op.in]: postIds } },
        attributes: ['postId']
      }),
      PostSaved.findAll({
        where: { userId, postId: { [Op.in]: postIds } },
        attributes: ['postId']
      }),
      // Get follow status for all authors at once
      Follow.findAll({
        where: { 
          followerId: userId, 
          followingId: { [Op.in]: allPosts.map(post => post.author.id) }
        },
        attributes: ['followingId']
      })
    ]);
    

    
    // Create lookup sets for faster checks
    const likedPostIds = new Set(likeRecords.map(record => record.postId));
    const savedPostIds = new Set(saveRecords.map(record => record.postId));
    const followingAuthorIds = new Set(followRecords.map(record => record.followingId));
    
    // Format the response to match details/:id route format
    const formattedPosts = allPosts.map(post => {
      const plainPost = post.get({ plain: true });
      
      return {
        id: plainPost.id,
        content: plainPost.content,
        thumbnail: plainPost.thumbnail,
        views: plainPost.views,
        likes: plainPost.likes,
        comments: plainPost.comments,
        description: plainPost.description,
        media: plainPost.media || [],
        createdAt: plainPost.createdAt,
        updatedAt: plainPost.updatedAt,
        category: plainPost.category || plainPost.categories,
        shares: plainPost.shared,
        bookmarks: plainPost.bookmarks,
        recommendedby: plainPost.recommendedby,
        parentId: plainPost.parentId,
        authorId: plainPost.authorId,
        isShort: plainPost.isShort,
        isBackfill: backfillPosts.some(bp => bp.id === plainPost.id), // Add flag to identify backfill posts
        author: {
          id: plainPost.author.id,
          username: plainPost.author.username,
          profilePicture: plainPost.author.profilePicture,
          fullName: (plainPost.author.firstName || '') + ' ' + (plainPost.author.lastName || ''),
          verified: plainPost.author.verified
        },
        userInteraction: {
          liked: likedPostIds.has(plainPost.id),
          saved: savedPostIds.has(plainPost.id),
          isFollowing: followingAuthorIds.has(plainPost.author.id)
        }
      };
    });
    
    // Update the total count to include potential backfill posts
    // If the user has exhausted their regular feed, add the backfill count
    const updatedTotalCount = needBackfill && page > 1
      ? totalCount + await Post.count({
          where: { 
            authorId: { 
              [Op.notIn]: allRelevantUserIds 
            },
            isShort: false
          }
        })
      : totalCount;
    
    // Send response with pagination info
    const response = {
      posts: formattedPosts,
      pagination: {
        page,
        limit,
        totalCount: updatedTotalCount,
        totalPages: Math.ceil(updatedTotalCount / limit),
        hasMore: formattedPosts.length === limit // If we got a full page, there's likely more
      }
    };
 
    
    res.json(response);
    
  } catch (error) {
    console.error('==== FEED ROUTE ERROR ====');
    console.error('Error fetching feed:', error);
    console.error('Stack trace:', error.stack);
    res.status(500).json({ error: 'Failed to fetch feed', details: error.message });
  }
});

router.delete('/story-delete', validateToken, async (req, res) => {
  try {
    const { storyId } = req.body;
    const userId = req.user.id;

    // Find the story with matching storyId and userId
    const story = await Story.findOne({ where: { storyId, userId } });
    if (!story) {
      return res.json({ message: "Story not found or not owned by user" });
    }
    
    // Delete associated StoryView records to avoid foreign key constraint errors
    await StoryView.destroy({ where: { storyId } });
    
    // Delete associated metadata entries for the story
    await StoryMetaData.destroy({ where: { story_id: storyId } });
    
    // Delete the story itself
    await Story.destroy({ where: { storyId, userId } });
    
    res.json({ message: "Story and associated metadata deleted successfully" });
  } catch (error) {
    console.error("Error deleting story:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Route to fetch viewers for a story owned by the current user
router.get('/storyviewedBy/:storyId', validateToken, async (req, res) => {
  try {
    const { storyId } = req.params;
    const userId = req.user.id;
    
    // Find the story belonging to the current user
    const story = await Story.findOne({ where: { storyId, userId } });
    if (!story) {
      return res.json({ message: "Story not found or not owned by user" });
    }
    
    // Find all view records for this story and include viewer details from Users table
    const storyViews = await StoryView.findAll({
      where: { storyId },
      include: [{
        model: Users,
        as: 'viewer',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });
    
    // Filter out the owner's view using string comparison
    const filteredViews = storyViews.filter(view => {
      return String(view.userId) !== String(userId);
    });
    
    // Map the view records to extract viewer details
    const viewers = filteredViews.map(view => ({
      userId: view.userId,
      username: view.viewer ? view.viewer.username : null,
      profilePicture: view.viewer ? view.viewer.profilePicture : null
    }));
    
    res.json({ viewers });
  } catch (error) {
    console.error("Error fetching story views:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});
router.post('/storyviewed', validateToken, async (req, res) => {
  try {
    const { storyId } = req.body;
    if (!storyId) {
      return res.status(400).json({ error: "Story id is required" });
    }
    const userId = req.user.id;
    
    // Check if a view record already exists
    const existingView = await StoryView.findOne({
      where: { storyId, userId }
    });
    
    if (existingView) {
      return res.json({ message: "View already recorded" });
    }
    
    // Create a new view record
    await StoryView.create({ storyId, userId });
    return res.json({ message: "View recorded" });
  } catch (error) {
    console.error("Error recording story view:", error);
    return res.status(500).json({ error: "Internal server error" });
  }
});

router.post('/storylike', validateToken, async (req, res) => {
  try {
    const { storyId } = req.body;
    if (!storyId) {
      return res.status(400).json({ error: "Story id is required" });
    }
    const userId = req.user.id;
    
    // Check if a like record already exists
    const existingLike = await StoryLike.findOne({
      where: { storyId, userId }
    });
    
    if (existingLike) {
      // If like exists, remove it (unlike)
      await existingLike.destroy();
      return res.json({ liked: false, message: "Story unliked successfully" });
    } else {
      // If like doesn't exist, create it
      await StoryLike.create({ storyId, userId });
      return res.json({ liked: true, message: "Story liked successfully" });
    }
  } catch (error) {
    console.error("Error processing story like:", error);
    return res.status(500).json({ error: "Internal server error" });
  }
});
// First route: Get minimal story metadata for all users with active stories
router.get('/stories-metadata', validateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const last24Hours = new Date(Date.now() - 24 * 60 * 60 * 1000);

    // First, get all users that the current user follows
    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });

    // Get array of following IDs and include own id
    const followingIds = following.map(f => f.followingId);
    const allUserIds = [...followingIds, userId];

    // Get basic user info and story metadata (without full content)
    const storiesMetadata = await Users.findAll({
      where: { id: allUserIds },
      attributes: ['id', 'username', 'profilePicture', 'Verified'],
      include: [{
        model: Story,
        as: 'Stories',
        where: {
          createdAt: {
            [Op.gte]: last24Hours
          }
        },
        attributes: ['storyId', 'createdAt'], // Only get minimal story info
        required: false // Include users even if they don't have stories
      }]
    });

    // Format the response to include viewedAll flag
    const formattedResponse = await Promise.all(
      storiesMetadata.map(async user => {
        const userData = user.get({ plain: true });
        
        // If user has no stories, return minimal info
        if (!userData.Stories || userData.Stories.length === 0) {
          return {
            userId: userData.id,
            username: userData.username,
            profilePicture: userData.profilePicture,
            verified: userData.Verified, // Match your capitalization
            hasStories: false,
            storyCount: 0,
            viewedAll: true
          };
        }

        const storyIds = userData.Stories.map(story => story.storyId);
        
        // Check if the current user has viewed all stories from this user
        const viewRecords = await StoryView.findAll({
          where: { userId, storyId: { [Op.in]: storyIds } }
        });
        
        const viewedStoryIds = new Set(viewRecords.map(v => v.storyId));
        
        // viewedAll is true only if all stories have been viewed
        const viewedAll = storyIds.every(id => viewedStoryIds.has(id));
        
        // Get the latest story creation time for sorting
        const latestStoryTime = userData.Stories.reduce(
          (latest, story) => {
            const storyDate = new Date(story.createdAt);
            return storyDate > latest ? storyDate : latest;
          }, 
          new Date(0)
        );

        return {
          userId: userData.id,
          username: userData.username,
          profilePicture: userData.profilePicture,
          verified: userData.Verified, // Match your capitalization
          hasStories: true,
          storyCount: userData.Stories.length,
          viewedAll,
          latestStoryTime // Add this for sorting
        };
      })
    );

    // Filter out users with no stories
    const usersWithStories = formattedResponse.filter(user => user.hasStories);
    
    // Sort by latest story creation time (newest first)
    usersWithStories.sort((a, b) => {
      // Always put current user first if they have stories
      if (a.userId === userId) return -1;
      if (b.userId === userId) return 1;
      
      // Then sort by viewed status (unviewed first)
      if (!a.viewedAll && b.viewedAll) return -1;
      if (a.viewedAll && !b.viewedAll) return 1;
      
      // Then sort by story creation time (newest first)
      return b.latestStoryTime - a.latestStoryTime;
    });

    // Remove the latestStoryTime from the response
    const finalResponse = usersWithStories.map(({ latestStoryTime, ...user }) => user);
    
    res.json(finalResponse);
  } catch (error) {
    console.error("Error fetching stories metadata:", {
      message: error.message,
      stack: error.stack,
      userId: req.user?.id
    });
    res.status(500).json({ 
      error: 'Internal server error',
      details: process.env.NODE_ENV === 'development' ? error.message : undefined
    });
  }
});

router.get('/user-stories/:userId', validateToken, async (req, res) => {
  try {
    const viewerId = req.user.id; // The user viewing the stories
    const { userId } = req.params; // The user whose stories are being viewed
    const last24Hours = new Date(Date.now() - 24 * 60 * 60 * 1000);

    // Get all users that the current user follows to determine the order
    const following = await Follow.findAll({
      where: { followerId: viewerId },
      attributes: ['followingId']
    });
    
    // Create an ordered list of users (current user first, then followed users)
    let allUserIds = [viewerId, ...following.map(f => f.followingId)];
    
    // Find the user and their stories
    const userWithStories = await Users.findOne({
      where: { id: userId },
      attributes: ['id', 'username', 'profilePicture', 'verified'],
      include: [{
        model: Story,
        as: 'Stories',
        where: {
          createdAt: {
            [Op.gte]: last24Hours
          }
        },
        include: [{
          model: StoryMetaData,
          as: 'metadata',
          required: false,
          attributes: [
            'element_type',
            'background_color',
            'text_color',
            'content',
            'position_x',
            'position_y',
            'width',
            'height',
            'rotation',
            'scale',
            'isPost',
            'scaled',
            'z_index',
            'offset_x',
            'offset_y'
          ]
        }],
        required: false,
        order: [['createdAt', 'DESC']]
      }]
    });

    if (!userWithStories) {
      return res.status(404).json({ message: "User not found" });
    }

    const userData = userWithStories.get({ plain: true });
    
    // Get the index of the requested user in our ordered list
    const userIndex = allUserIds.indexOf(userId);
    
    // Determine the adjacent user IDs (wrap around if needed)
    let leftUserIndex = (userIndex - 1 + allUserIds.length) % allUserIds.length;
    let rightUserIndex = (userIndex + 1) % allUserIds.length;
    
    // Fetch minimal metadata for adjacent users
    let adjacentUsers = [];
    
    if (userIndex !== -1) {
      // Fetch metadata for adjacent users (left and right)
      adjacentUsers = await Users.findAll({
        where: { 
          id: [allUserIds[leftUserIndex], allUserIds[rightUserIndex]] 
        },
        attributes: ['id', 'username', 'profilePicture', 'verified'],
        include: [{
          model: Story,
          as: 'Stories',
          where: {
            createdAt: {
              [Op.gte]: last24Hours
            }
          },
          attributes: ['storyId', 'createdAt'],
          required: false
        }]
      });
    }

    // Format adjacent users data
    const adjacentUsersData = adjacentUsers.map(user => {
      const plainUser = user.get({ plain: true });
      return {
        userId: plainUser.id,
        username: plainUser.username,
        profilePicture: plainUser.profilePicture,
        verified: plainUser.verified,
        hasStories: plainUser.Stories && plainUser.Stories.length > 0,
        storyCount: plainUser.Stories ? plainUser.Stories.length : 0
      };
    });
    
    // If no stories, return empty array with adjacent users
    if (!userData.Stories || userData.Stories.length === 0) {
      return res.json({
        userId: userData.id,
        username: userData.username,
        profilePicture: userData.profilePicture,
        verified: userData.verified,
        stories: [],
        adjacentUsers: adjacentUsersData
      });
    }

    // The rest of the function remains the same for processing the requested user's stories
    const storyIds = userData.Stories.map(story => story.storyId);

    // Fetch view records for current viewer
    const viewRecords = await StoryView.findAll({
      where: { userId: viewerId, storyId: { [Op.in]: storyIds } }
    });
    const viewedSet = new Set(viewRecords.map(v => v.storyId));

    // Fetch like records for current viewer - NEW CODE
    const likeRecords = await StoryLike.findAll({
      where: { userId: viewerId, storyId: { [Op.in]: storyIds } }
    });
    const likedSet = new Set(likeRecords.map(l => l.storyId));

    const viewCounts = await StoryView.findAll({
      attributes: [
        'storyId',
        [Sequelize.fn('COUNT', Sequelize.col('storyId')), 'viewsCount']
      ],
      where: {
        storyId: { [Op.in]: storyIds },
        userId: { [Op.ne]: userData.id }
      },
      group: ['storyId']
    });

    const viewCountMap = {};
    viewCounts.forEach(vc => {
      viewCountMap[vc.storyId] = parseInt(vc.get('viewsCount'));
    });

    const stories = userData.Stories.map(story => ({
      storyId: story.storyId,
      bgcolor: story.bgcolor,
      stageHeight: story.height,
      stageWidth: story.width,
      createdAt: story.createdAt,
      viewed: viewedSet.has(story.storyId),
      viewsCount: viewCountMap[story.storyId] || 0,
      isLiked: likedSet.has(story.storyId), // NEW: Add isLiked flag
      elements: (story.metadata || []).map(meta => ({
        z_index: meta.z_index,
        type: meta.element_type,
        backgroundColor: meta.background_color,
        textColor: meta.text_color,
        content: meta.content,
        position: {
          x: meta.position_x || 0,
          y: meta.position_y || 0
        },
        dimensions: {
          width: meta.width || 0,
          height: meta.height || 0
        },
        transform: {
          rotation: meta.rotation || 0,
          scale: meta.scale || 1,
          isPost: meta.isPost || false
        }
      }))
    }));

    stories.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));


    // Add adjacentUsers to the response
    res.json({
      userId: userData.id,
      username: userData.username,
      profilePicture: userData.profilePicture,
      verified: userData.verified,
      stories,
      adjacentUsers: adjacentUsersData
    });
  } catch (error) {
    console.error("Error fetching user stories:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});
router.get("/summary/:id", async (req, res) => {
  const postId = req.params.id;
  try {
    const post = await Post.findOne({
      where: { id: postId },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['username', 'profilePicture', 'id', 'verified']
      }]
    });
    if (!post) {
      return res.status(404).json({ error: "Post not found" });
    }
    
    // Get the first media item for display
    let mainMedia = null;
    let mediaType = null;

    if (post.media && post.media.length > 0) {
      mainMedia = post.media[0].url;
      mediaType = post.media[0].type;
    }
    
    // For short posts, use truncated content as the title
    let displayTitle =  post.content;
    if (post.isShort && post.content) {
      displayTitle = post.content.length > 110 ? 
        post.content.substring(0, 110) + '...' : 
        post.content;
    }
    
    // Return the summary details with updated media structure and engagement metrics
    res.json({
      media: post.media,
      mainMedia,
      mediaType,
      title: displayTitle,
      author: {
        id: post.author.id,
        username: post.author.username,
        profilePicture: post.author.profilePicture,
        verified: post.author.verified
      },
      likes: post.likes || 0,
      comments: post.comments || 0,
      isShort: post.isShort
    });
  } catch (error) {
    console.error("Error fetching post summary:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});
router.get("/:id", validateToken, async (req, res) => {
  const postId = req.params.id;
  const userId = req.user.id || null;
  try {
    // Find post with author information
    const post = await Post.findOne({ 
      where: { id: postId },
      include: [
        {
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture' , 'firstName' , 'lastName','createdAt']
        }
      ]
    });
    
    if (!post) {
      return res.status(404).json({ error: "Post not found" });
    }
    
    let userInteraction = {
      liked: false,
      saved: false,
      isFollowing: false,
    };

    // If userId is provided, check if user has liked or saved the post
    if (userId) {
      const [likeStatus, saveStatus, followStatus] = await Promise.all([
        PostLike.findOne({
          where: { userId, postId },
          raw: true,
        }),
        PostSaved.findOne({
          where: { userId, postId },
          raw: true,
        }),
        Follow.findOne({
          where: { followerId: userId, followingId: post.author.id },
          raw: true,
        }),
      ]);

      userInteraction.liked = !!likeStatus;
      userInteraction.saved = !!saveStatus;
      userInteraction.isFollowing = !!followStatus;
    }

    
    // Format the response
    const response = {
      id: post.id,
      
      content: post.content,
      thumbnail: post.thumbnail,
      views: post.views , // Include the incremented view count
      likes: post.likes,
      comments: post.comments,
      description: post.description,
      media: post.media || [], // Include media field explicitly
      createdAt: post.createdAt,
      updatedAt: post.updatedAt,
      category: post.category,
      createdAt: post.createdAt,
      author: {
        id: post.author.id,
        username: post.author.username,
        fullName: post.author.firstName + ' ' + post.author.lastName,
        profilePicture: post.author.profilePicture
      },
      userInteraction: userInteraction
    };
    
    res.json(response);
    
  } catch (error) {
    console.error('Error fetching post:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});
// Helper function to get IDs of users the current user is following
async function getFollowingUserIds(userId) {
  const following = await Users.findAll({
    where: { followerId: userId },
    attributes: ['followingId'],
  });

  return following.map(user => user.followingId);
}

/// Fetch posts for the home page with detailed debug logging

router.get('/details/:id', validateToken, async (req, res) => {
  const postId = req.params.id;
  const userId = req.user?.id;

  try {
    const [post, likeStatus, saveStatus] = await Promise.all([
      Post.findOne({
        where: { id: postId },
        include: [{
          model: Users,
          as: 'author',
          attributes: ['username', 'profilePicture'],
        }],
      }),
      userId ? PostLike.findOne({ 
        where: { userId, postId },
        raw: true 
      }) : null,
      userId ? PostSaved.findOne({ 
        where: { userId, postId },
        raw: true 
      }) : null
    ]);

    if (!post) {
      return res.status(404).json({ error: 'Post not found' });
    }

    const response = {
      thumbnail: post.thumbnail,
      authorId: post.authorId,
      author: {
        username: post.author.username,
        profilePicture: post.author.profilePicture,
      },
      description: post.description,
      shares: post.shared,
      bookmarks: post.bookmarks,
      views: post.views,
      likes: post.likes,
      recommendedby: post.recommendedby,
      parentId: post.parentId,
      createdAt: post.createdAt,
      id: post.id,
      comments: post.comments,
      interactions: {
        liked: !!likeStatus,
        saved: !!saveStatus
      }
    };

    res.json(response);
  } catch (error) {
    console.error('Error fetching post:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Update the existing route to limit to 9 posts/shorts and order by creation time
router.get('/post/details/:userId', validateToken, async (req, res) => {
  const userId = req.params.userId;
  const currentUserId = req.user.id; // Get current user ID from token
  const isShort = req.query.isShort === 'true'; // Get from query parameter
    try {
    // Build where clause - if viewing own profile, show all posts, otherwise exclude community-only posts
    const whereClause = { 
      authorId: userId,
      isShort: isShort
    };
    
    // If viewing another user's profile (not own), exclude community-only posts
    if (currentUserId !== userId) {
      whereClause.inCommunity = false;
    }
    
    const posts = await Post.findAll({
      where: whereClause,
      attributes: [
        'content', 
        'description', 
        'media',
        'id', 
        'createdAt', 
        'views',
        'isShort',
        'likes',
        'comments',
        'shared' // Include share count
      ],
      order: [['createdAt', 'DESC']], // Order by creation time, newest first
      limit: 9 // Limit to 9 posts
    });

    // If we have posts, fetch interaction data for each one
    if (posts.length > 0) {
      const postIds = posts.map(post => post.id);
      
      // Fetch like status for all posts in one query
      const likeStatuses = await PostLike.findAll({
        where: { 
          userId: currentUserId,
          postId: { [Op.in]: postIds }
        },
        attributes: ['postId']
      });
      
      // Convert to a map for easy lookup
      const likedPostIds = new Set(likeStatuses.map(like => like.postId));
      
      // Fetch save status for all posts in one query
      const saveStatuses = await PostSaved.findAll({
        where: {
          userId: currentUserId,
          postId: { [Op.in]: postIds }
        },
        attributes: ['postId']
      });
      
      // Convert to a map for easy lookup
      const savedPostIds = new Set(saveStatuses.map(save => save.postId));
      
      // Add interaction data to each post
      const postsWithInteractions = posts.map(post => {
        const plainPost = post.get({ plain: true });
        
        plainPost.interactions = {
          liked: likedPostIds.has(plainPost.id),
          saved: savedPostIds.has(plainPost.id)
        };
        
        // For posts, ensure we have media URLs correctly formatted
        if (plainPost.media && Array.isArray(plainPost.media)) {
          plainPost.media = plainPost.media.map(item => ({
            type: item.type || 'image',
            url: item.url || '',
            originalName: item.originalName || ''
          }));
        }
        
        return plainPost;
      });
      
      res.json(postsWithInteractions);
    } else {
      res.status(404).json({ error: 'No posts found for this user' });
    }
  } catch (error) {
    console.error('Error fetching user posts:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Simplified route for pagination - fetching more posts or shorts
router.post('/more-posts', validateToken, async (req, res) => {
  const { isShort, postId } = req.body;
  const currentUserId = req.user.id;
  
  // Input validation
  if (isShort === undefined) {
    return res.status(400).json({ error: 'isShort parameter is required' });
  }
    try {
    // Define where clause for the query
    const whereClause = { isShort };
    
    // If postId is provided, we need to find older posts than that specific one
    if (postId) {
      // Get the reference post's creation date
      const referencePost = await Post.findOne({
        where: { id: postId }
      });

      if (!referencePost) {
        return res.status(404).json({ error: 'Reference post not found' });
      }
      
      // Use the author from the reference post
      whereClause.authorId = referencePost.authorId;
      
      // If viewing another user's posts (not own), exclude community-only posts
      if (currentUserId !== referencePost.authorId) {
        whereClause.inCommunity = false;
      }
      
      // Add creation date condition to get older posts
      whereClause.createdAt = {
        [Op.lt]: referencePost.createdAt // Less than (older than) the reference post's creation date
      };
    } else {
      // If no postId provided, we can't determine the author
      return res.status(400).json({ error: 'postId is required' });
    }

    // Fetch posts with updated attributes including comments and shares
    const posts = await Post.findAll({
      where: whereClause,
      attributes: [
        'content',
        'description', 
        'media',
        'id', 
        'createdAt', 
        'views',
        'isShort',
        'likes',
        'comments',
        'shared' // Include share count
      ],
      order: [['createdAt', 'DESC']], // Order by creation time, newest first
      limit: 9 // Limit to 9 more posts
    });

    // If we have posts, fetch interaction data for each one
    if (posts.length > 0) {
      const postIds = posts.map(post => post.id);
      
      // Fetch like status for all posts in one query
      const likeStatuses = await PostLike.findAll({
        where: { 
          userId: currentUserId,
          postId: { [Op.in]: postIds }
        },
        attributes: ['postId']
      });
      
      // Convert to a map for easy lookup
      const likedPostIds = new Set(likeStatuses.map(like => like.postId));
      
      // Fetch save status for all posts in one query
      const saveStatuses = await PostSaved.findAll({
        where: {
          userId: currentUserId,
          postId: { [Op.in]: postIds }
        },
        attributes: ['postId']
      });
      
      // Convert to a map for easy lookup
      const savedPostIds = new Set(saveStatuses.map(save => save.postId));
      
      // Process the posts to format them correctly for the frontend
      const formattedPosts = posts.map(post => {
        const plainPost = post.get({ plain: true });
        
        // Add interaction data
        plainPost.interactions = {
          liked: likedPostIds.has(plainPost.id),
          saved: savedPostIds.has(plainPost.id)
        };
        
        // For regular posts, ensure we have media URLs correctly formatted
        if (plainPost.media && Array.isArray(plainPost.media)) {
          // Keep media but ensure it's correctly formatted
          plainPost.media = plainPost.media.map(item => ({
            type: item.type || 'image',
            url: item.url || '',
            originalName: item.originalName || ''
          }));
        }
        
        return plainPost;
      });

      res.json({
        posts: formattedPosts,
        hasMore: formattedPosts.length === 9 // Indicate if there are likely more posts
      });
    } else {
      res.json({
        posts: [],
        hasMore: false
      });
    }
  } catch (error) {
    console.error('Error fetching more posts:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});
  // Set up multer storage for file uploads
  const storage = multer.memoryStorage();
  const upload = multer({ storage });
  
  //------Create Post----------------------------------------------------------------------------------------------------------------------//
  
  const storagePostImages = multer.memoryStorage();
  const uploadPostImages = multer({ storage: storagePostImages });
  
  router.post('/upload-images', uploadPostImages.single('tempPostImages'), async (req, res) => {
    try {
      if (!req.file) {
        return res.status(400).json({ error: 'No file uploaded' });
      }
      
      // Generate unique filename
      const filename = generateUniqueFilename(req.file.originalname);
      
      // Upload to B2 with virtual folder
      const result = await uploadToB2(req.file.buffer, filename, 'tempPostImages');
      
      // Return the file URL and filename
      res.json({ 
        filename: filename,
        url: result.url
      });
    } catch (error) {
      console.error('Error uploading image:', error);
      res.status(500).json({ error: 'Failed to upload image' });
    }
  });

const storageShortMedia = multer.memoryStorage();

// Configure multer for short media uploads (supporting multiple files)
const uploadShortMedia = multer({ 
  storage: storageShortMedia,
  limits: {
    fileSize: 120 * 1024 * 1024, // 120MB limit per file
  },
  fileFilter: (req, file, cb) => {
    // Validate file types - only allow JPG, JPEG, PNG for images and MP4 for videos
    const allowedImageTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    const allowedVideoTypes = ['video/mp4'];
    
    if (file.mimetype.startsWith('image/')) {
      if (allowedImageTypes.includes(file.mimetype)) {
        return cb(null, true);
      }
      return cb(new Error('Only JPG, JPEG, and PNG image files are allowed'), false);
    } 
    else if (file.mimetype.startsWith('video/')) {
      if (allowedVideoTypes.includes(file.mimetype)) {
        return cb(null, true);
      }
      return cb(new Error('Only MP4 video files are allowed'), false);
    }
    
    return cb(new Error('Unsupported file type'), false);
  }
});
  
router.post("/create-short", validateToken, uploadShortMedia.array("media", 4), async (req, res) => {
  console.log("\n=== [DEBUG] /create-short called ===");
  const t = await sequelize.transaction();  try {
    const userId = req.user.id;
    const content = req.body.content || "";
    const selectedCommunities = req.body.selectedCommunities;
    const parsedSelectedCommunities = selectedCommunities ? JSON.parse(selectedCommunities) : [];
    console.log("[DEBUG] userId:", userId);
    console.log("[DEBUG] content:", content);
    console.log("[DEBUG] selectedCommunities:", selectedCommunities);

    // Auto-detect categories using AI if content is available
    let categories = ["General"];
    if (content && content.trim().length > 0) {
      try {
        console.log("[DEBUG] Detecting categories for short content:", content.substring(0, 100) + "...");
        categories = await GoogleApi.detectPostCategories(content);
        console.log("[DEBUG] AI detected categories for short:", categories);
      } catch (error) {
        console.error("[ERROR] Failed to detect categories with AI for short:", error);
        // Fallback to manual categories if provided, otherwise use General
        categories = req.body.categories ? JSON.parse(req.body.categories) : ["General"];
        console.log("[DEBUG] Using fallback categories for short:", categories);
      }
    } else {
      // If no content, use manual categories if provided
      categories = req.body.categories ? JSON.parse(req.body.categories) : ["General"];
      console.log("[DEBUG] No content for AI detection, using manual categories for short:", categories);
    }
    console.log("[DEBUG] Final categories:", categories);
    console.log("[DEBUG] req.files:", req.files);

    // Set isPosting to true immediately when upload starts
    try {
      await Users.update(
        { isPosting: true },
        { where: { id: userId } }
      );
      console.log("[DEBUG] Set isPosting=true for user:", userId);
    } catch (error) {
      console.error("[ERROR] Failed to set isPosting=true:", error);
    }

    if (!req.files || req.files.length === 0) {
      console.log("[ERROR] No files uploaded");
      return res.status(400).json({ error: "At least one media file is required" });
    }

    // Process all uploaded files into media objects
    const mediaObjects = await Promise.all(req.files.map(async (file, idx) => {
      const folder = file.mimetype.startsWith('video/') ? 'shortVideos' : 'shortImages';
      const filename = generateUniqueFilename(file.originalname);
      // Defensive check
      if (typeof filename !== 'string' || !filename) {
        throw new Error('Invalid filename generated for upload');
      }
      console.log(`[DEBUG] Processing file[${idx}]:`, {
        originalname: file.originalname,
        mimetype: file.mimetype,
        folder,
        filename
      });
      try {
        const result = await uploadToB2(file.buffer, filename, folder);
        console.log(`[DEBUG] uploadToB2 result for file[${idx}]:`, result);
        return {
          type: file.mimetype.startsWith('video/') ? 'video' : 'image',
          url: filename,
          originalName: file.originalname,
          folder
        };
      } catch (err) {
        console.error(`[ERROR] uploadToB2 failed for file[${idx}]:`, err);
        throw err;
      }
    }));

    console.log("[DEBUG] mediaObjects:", mediaObjects);

    // Use the first file as the thumbnail
    const thumbnail = mediaObjects[0]?.url;
    console.log("[DEBUG] thumbnail:", thumbnail);

    const mediaMetadata = {
      aspectRatio: "9:16",
      originalFilenames: req.files.map(file => file.originalname),
      totalSize: req.files.reduce((total, file) => total + file.size, 0)
    };
    console.log("[DEBUG] mediaMetadata:", mediaMetadata);

    // Extract hashtags and mentions from the content
    const hashtagRegex = /#[a-zA-Z0-9_]+/g;
    const mentionRegex = /@[a-zA-Z0-9_]+/g;
    const hashtags = content.match(hashtagRegex) || [];
    const mentions = content.match(mentionRegex) || [];
    const normalizedHashtags = hashtags.map((tag) => tag.slice(1).toLowerCase());
    const normalizedMentions = mentions.map((mention) => mention.slice(1).toLowerCase());
    console.log("[DEBUG] hashtags:", normalizedHashtags, "mentions:", normalizedMentions);

    // Detect location in content
    let location = null;
    try {
      location = await detectLocations(content);
      console.log("[DEBUG] location:", location);
    } catch (error) {
      console.error("[ERROR] Error detecting location:", error);
    }    // Create the short post with media information
    const isInCommunity = parsedSelectedCommunities.length > 0;
    
    const newShort = await Post.create({
      content,
      authorId: userId,
      media: mediaObjects,
      thumbnail,
      isShort: true,
      categories: categories.join(","),
      mediaMetadata,
      location,
      inCommunity: isInCommunity,
    }, { transaction: t });
    console.log("[DEBUG] Post.create result:", newShort);

    // Increment the user's post count
    await Users.increment('posts', { where: { id: userId }, transaction: t });

    // Process hashtags
    for (const tag of normalizedHashtags) {
      let hashtag = await Hashtag.findOne({ where: { name: tag }, transaction: t });
      if (hashtag) {
        hashtag.Count += 1;
        await hashtag.save({ transaction: t });
      } else {
        hashtag = await Hashtag.create({ name: tag, Count: 1 }, { transaction: t });
      }
      await PostHashtags.create({ postId: newShort.id, hashtagId: hashtag.id }, { transaction: t });
    }    // Process mentions
    for (const mention of normalizedMentions) {
      const mentionedUser = await Users.findOne({ where: { username: mention }, transaction: t });
      if (mentionedUser) {
        await Mention.create({ postId: newShort.id, userId: mentionedUser.id }, { transaction: t });
      }
    }    // Process Community Posts for shorts
    console.log("[DEBUG] Processing community posts for short:", parsedSelectedCommunities);
    
    if (parsedSelectedCommunities.length > 0) {
      const { CommunityPosts, CommunityMemberships } = require('../models');
      
      for (const communityId of parsedSelectedCommunities) {
        try {          // Verify user can post in this community
          const membership = await CommunityMemberships.findOne({
            where: {
              user_id: userId,
              community_id: communityId,
              status: 'active'
            },
            include: [{
              model: Communities,
              as: 'community',
              attributes: ['access_type', 'creator_id']
            }],
            transaction: t
          });

          if (membership) {
            const community = membership.community;
            const isCreator = community.creator_id === userId;
            let canPost = false;

            // New simplified logic based on access_type
            switch (community.access_type) {
              case 'admin':
                // Only creator/admin can post
                canPost = isCreator || membership.role === 'admin';
                break;
              case 'moderator':
                // Creator, admin, and moderators can post
                canPost = isCreator || membership.role === 'admin' || membership.role === 'moderator';
                break;
              case 'everyone':
                // All active members can post
                canPost = true;
                break;
              default:
                canPost = false;
            }

            if (canPost) {
              await CommunityPosts.create({
                community_id: communityId,
                post_id: newShort.id,
                posted_by: userId
              }, { transaction: t });
                console.log(`[DEBUG] Posted short to community: ${communityId} (access_type: ${community.access_type})`);
            } else {
              console.log(`[DEBUG] User ${userId} cannot post short in community ${communityId} (access_type: ${community.access_type}, role: ${membership.role})`);
            }
          }
        } catch (error) {
          console.error(`[ERROR] Failed to post short to community ${communityId}:`, error);
          // Continue with other communities
        }
      }
    }

    await t.commit();
    console.log("[DEBUG] Transaction committed");
    
    // Set isPosting to false after successful completion
    try {
      await Users.update(
        { isPosting: false },
        { where: { id: userId } }
      );
      console.log("[DEBUG] Set isPosting=false for user:", userId);
    } catch (error) {
      console.error("[ERROR] Failed to set isPosting=false:", error);
    }
    
    res.json(newShort);
  } catch (error) {
    await t.rollback();
    console.error("[ERROR] Error creating short:", error);
    
    // Set isPosting to false on error
    try {
      await Users.update(
        { isPosting: false },
        { where: { id: userId } }
      );
      console.log("[DEBUG] Set isPosting=false for user (error case):", userId);
    } catch (cleanupError) {
      console.error("[ERROR] Failed to cleanup isPosting on error:", cleanupError);
    }
    
    res.status(500).json({ error: "Internal server error", details: error.message });
  }
});

router.get('/short/details/:id', validateToken, async (req, res) => {
  const postId = req.params.id;
  const currentUserId = req.user.id;
  try {
    // Fetch the post (short) and include the associated author
    const post = await Post.findOne({
      where: { id: postId },
      include: [
        {
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'profilePicture']
        }
      ]
    });
    if (!post) {
      return res.status(404).json({ error: "Post not found" });
    }

    // Check if the current user follows the post's author
    const followRecord = await require("../models").Follow.findOne({
      where: {
        followerId: currentUserId,
        followingId: post.author.id
      }
    });
    const isFollowing = !!followRecord;
    
    // Check if the user has liked the post
    const likeRecord = await PostLike.findOne({
      where: {
        userId: currentUserId,
        postId: postId
      }
    });
    const isLiked = !!likeRecord;
    
    // Check if the user has saved the post
    const saveRecord = await PostSaved.findOne({
      where: {
        userId: currentUserId,
        postId: postId
      }
    });
    const isSaved = !!saveRecord;

    // Prepare and return the response
    const result = {
      ...post.get({ plain: true }),
      author: post.author,
      isFollowing,
      isLiked,
      isSaved
    };

    res.json(result);
  } catch (error) {
    console.error("Error fetching short details:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

router.delete('/delete-image/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    
    // Delete from B2 with virtual folder
    const result = await deleteFromB2(filename, 'tempPostImages');
    
    if (result) {
      res.json({ message: 'Image deleted successfully' });
    } else {
      res.status(404).json({ error: 'Image not found' });
    }
  } catch (error) {
    console.error('Error deleting image:', error);
    res.status(500).json({ error: 'Failed to delete image' });
  }
});

const storagePostMedia = multer.memoryStorage();

const uploadPostMedia = multer({
  storage: storagePostMedia,
  limits: {
    fileSize: 100 * 1024 * 1024, // 100MB limit
  },
  fileFilter: (req, file, cb) => {
    const allowedImageTypes = ['image/jpeg', 'image/jpg', 'image/png'];
    const allowedVideoTypes = ['video/mp4'];
    
    if (file.fieldname === 'postImages') {
      if (!file.mimetype.startsWith('image/')) {
        return cb(new Error('Only image files are allowed for postImages field'), false);
      }
      if (!allowedImageTypes.includes(file.mimetype)) {
        return cb(new Error('Only JPG, JPEG, and PNG image files are allowed'), false);
      }
    }
    
    if (file.fieldname === 'postVideos') {
      if (!file.mimetype.startsWith('video/')) {
        return cb(new Error('Only video files are allowed for postVideos field'), false);
      }
      if (!allowedVideoTypes.includes(file.mimetype)) {
        return cb(new Error('Only MP4 video files are allowed'), false);
      }
    }
    
    cb(null, true);
  }
});

router.post('/create-post', validateToken, uploadPostMedia.fields([
  { name: 'postImages', maxCount: 4 },
  { name: 'postVideos', maxCount: 1 },
]), async (req, res) => {
  console.log("\n=== [DEBUG] /create-post called ===");
  const { content, hashtags, mentions, categories, selectedCommunities } = req.body;
  const userId = req.user.id;
  const files = req.files || {};
  console.log("[DEBUG] userId:", userId);
  console.log("[DEBUG] content:", content);
  console.log("[DEBUG] hashtags:", hashtags);
  console.log("[DEBUG] mentions:", mentions);
  console.log("[DEBUG] selectedCommunities:", selectedCommunities);
  console.log("[DEBUG] categories:", categories);
  console.log("[DEBUG] req.files:", files);

  if (!userId) {
    console.log("[ERROR] No userId found in token");
    return res.status(401).json({ error: 'User is not logged in or token is invalid.' });
  }

  // Set isPosting to true immediately when upload starts
  try {
    await Users.update(
      { isPosting: true },
      { where: { id: userId } }
    );
    console.log("[DEBUG] Set isPosting=true for user:", userId);
  } catch (error) {
    console.error("[ERROR] Failed to set isPosting=true:", error);
  }

  const hasContent = content && content.trim().length > 0;
  const hasMedia = files.postImages?.length > 0 || files.postVideos?.length > 0;
  console.log("[DEBUG] hasContent:", hasContent, "hasMedia:", hasMedia);

  if (!hasContent && !hasMedia) {
    console.log("[ERROR] Post must have either content or media.");
    return res.status(400).json({ error: 'Post must have either content or media.' });
  }  // Parse JSON fields
  const parsedHashtags = hashtags ? JSON.parse(hashtags) : [];
  const parsedMentions = mentions ? JSON.parse(mentions) : [];
  const parsedSelectedCommunities = selectedCommunities ? JSON.parse(selectedCommunities) : [];
  const normalizedHashtags = parsedHashtags.map(tag => tag.slice(1).toLowerCase());
  const normalizedMentions = parsedMentions.map(mention => mention.slice(1).toLowerCase());

  // Auto-detect categories using AI if content is available
  let parsedCategories = ["General"];
  if (hasContent) {
    try {
      console.log("[DEBUG] Detecting categories for content:", content.substring(0, 100) + "...");
      parsedCategories = await GoogleApi.detectPostCategories(content);
      console.log("[DEBUG] AI detected categories:", parsedCategories);
    } catch (error) {
      console.error("[ERROR] Failed to detect categories with AI:", error);
      // Fallback to manual categories if provided, otherwise use General
      parsedCategories = categories ? JSON.parse(categories) : ["General"];
      console.log("[DEBUG] Using fallback categories:", parsedCategories);
    }
  } else {
    // If no content, use manual categories if provided
    parsedCategories = categories ? JSON.parse(categories) : ["General"];
    console.log("[DEBUG] No content for AI detection, using manual categories:", parsedCategories);
  }

  const mediaArray = [];

  // Add images
  if (files.postImages) {
    for (const [idx, file] of files.postImages.entries()) {
      const filename = generateUniqueFilename(file.originalname);
      console.log(`[DEBUG] Uploading postImages[${idx}]:`, file.originalname, file.mimetype, filename);
      try {
        const result = await uploadToB2(file.buffer, filename, 'postImages');
        console.log(`[DEBUG] uploadToB2 result for postImages[${idx}]:`, result);
        mediaArray.push({
          type: 'image',
          url: filename,
          originalName: file.originalname,
          folder: 'postImages'
        });
      } catch (err) {
        console.error(`[ERROR] uploadToB2 failed for postImages[${idx}]:`, err);
        throw err;
      }
    }
  }

  // Add video
  if (files.postVideos && files.postVideos.length > 0) {
    const file = files.postVideos[0];
    const filename = generateUniqueFilename(file.originalname);
    console.log(`[DEBUG] Uploading postVideos:`, file.originalname, file.mimetype, filename);
    try {
      const result = await uploadToB2(file.buffer, filename, 'postVideos');
      console.log(`[DEBUG] uploadToB2 result for postVideos:`, result);
      mediaArray.push({
        type: 'video',
        url: filename,
        originalName: file.originalname,
        folder: 'postVideos'
      });
    } catch (err) {
      console.error(`[ERROR] uploadToB2 failed for postVideos:`, err);
      throw err;
    }
  }

  // Set thumbnail to the first media item if available
  const thumbnail = mediaArray.length > 0 ? mediaArray[0].url : null;
  console.log("[DEBUG] thumbnail:", thumbnail);

  // Detect location in content
  let location = null;
  try {
    location = await detectLocations(content);
    console.log("[DEBUG] location:", location);
  } catch (error) {
    console.error("[ERROR] Error detecting location:", error);
  }  const t = await sequelize.transaction();

  try {
    // Check if this is a community-only post (created from within a community)
    // vs a regular post that's shared to communities
    const isDirectCommunityPost = req.body.isDirectCommunityPost === 'true';
    
    // Determine if this is a community-only post
    const isInCommunity = isDirectCommunityPost;
    
    const newPost = await Post.create({
      content,
      media: mediaArray,
      thumbnail,
      authorId: userId,
      categories: parsedCategories.join(","),
      location,
      inCommunity: isInCommunity,
    }, { transaction: t });
    console.log("[DEBUG] Post.create result:", newPost);

    // Increment user's post count
    await Users.increment('posts', { where: { id: userId }, transaction: t });

    // Process Hashtags
    for (const tag of normalizedHashtags) {
      let hashtag = await Hashtag.findOne({ where: { name: tag }, transaction: t });
      if (hashtag) {
        hashtag.Count += 1;
        await hashtag.save({ transaction: t });
      } else {
        hashtag = await Hashtag.create({ name: tag, Count: 1 }, { transaction: t });
      }
      await PostHashtags.create({ postId: newPost.id, hashtagId: hashtag.id }, { transaction: t });
    }    // Process Mentions
    for (const mention of normalizedMentions) {
      const mentionedUser = await Users.findOne({ where: { username: mention }, transaction: t });
      if (mentionedUser) {
        await Mention.create({ postId: newPost.id, userId: mentionedUser.id }, { transaction: t });
      }
    }    // Process Community Posts
    console.log("[DEBUG] Processing community posts for:", parsedSelectedCommunities);
    console.log("[DEBUG] isDirectCommunityPost:", isDirectCommunityPost);
    
    if (parsedSelectedCommunities.length > 0) {
      console.log("[DEBUG] Creating CommunityPosts entries for", parsedSelectedCommunities.length, "communities");
      
      for (const communityId of parsedSelectedCommunities) {
        try {          // Verify user can post in this community
          const membership = await CommunityMemberships.findOne({
            where: {
              user_id: userId,
              community_id: communityId,
              status: 'active'
            },
            include: [{
              model: Communities,
              as: 'community',
              attributes: ['access_type', 'creator_id']
            }],
            transaction: t
          });

          if (membership) {
            const community = membership.community;
            const isCreator = community.creator_id === userId;
            let canPost = false;

            // New simplified logic based on access_type
            switch (community.access_type) {
              case 'admin':
                // Only creator/admin can post
                canPost = isCreator || membership.role === 'admin';
                break;
              case 'moderator':
                // Creator, admin, and moderators can post
                canPost = isCreator || membership.role === 'admin' || membership.role === 'moderator';
                break;
              case 'everyone':
                // All active members can post
                canPost = true;
                break;
              default:
                canPost = false;
            }            if (canPost) {
              try {
                const communityPost = await CommunityPosts.create({
                  community_id: communityId,
                  post_id: newPost.id,
                  // For original posts by the author, reposted_by should be null
                  // The original author is tracked through the Post.authorId relationship
                  reposted_by: null,
                  is_author_original: true
                }, { transaction: t });
                
                console.log(`[DEBUG] Successfully created CommunityPost entry: ${communityPost.id} for community: ${communityId} (access_type: ${community.access_type})`);
              } catch (createError) {
                console.error(`[ERROR] Failed to create CommunityPost entry for community ${communityId}:`, createError);
                throw createError; // Re-throw to trigger transaction rollback
              }
            } else {
              console.log(`[DEBUG] User ${userId} cannot post in community ${communityId} (access_type: ${community.access_type}, role: ${membership.role})`);
            }
          }
        } catch (error) {          console.error(`[ERROR] Failed to post to community ${communityId}:`, error);
          // Continue with other communities
        }
      }
    } else {
      console.log("[DEBUG] No communities selected for this post");
    }

    await t.commit();
    console.log("[DEBUG] Transaction committed");
    
    // Set isPosting to false after successful completion
    try {
      await Users.update(
        { isPosting: false },
        { where: { id: userId } }
      );
      console.log("[DEBUG] Set isPosting=false for user:", userId);
    } catch (error) {
      console.error("[ERROR] Failed to set isPosting=false:", error);
    }
    
    res.json(newPost);
  } catch (error) {
    await t.rollback();
    console.error("[ERROR] Error creating post:", error);
    
    // Set isPosting to false on error
    try {
      await Users.update(
        { isPosting: false },
        { where: { id: userId } }
      );
      console.log("[DEBUG] Set isPosting=false for user (error case):", userId);
    } catch (cleanupError) {
      console.error("[ERROR] Failed to cleanup isPosting on error:", cleanupError);
    }
    
    res.status(500).json({ error: 'Internal server error', details: error.message });
  }
});

router.post('/hashtag-search', async (req, res) => {
  const { searchTerm } = req.body;

  if (!searchTerm) {
    return res.status(400).json({ error: "Search term is required" });
  }

  try {
    const hashtags = await Hashtag.findAll({
      attributes: ['id', 'name', 'Count', 'createdAt', 'updatedAt'],
      limit: 30  // Restrict to 30 results
    });

    const fuse = new Fuse(hashtags, {
      keys: ["name"],
      threshold: 0.3,
    });

    let results = fuse.search(searchTerm).map(result => result.item);

    // Sort results by Count in descending order
    results = results.sort((a, b) => b.Count - a.Count);

    res.json(results);
  } catch (error) {
    console.error('Error fetching hashtags:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});
// User search route
router.post('/username-search', async (req, res) => {
  const { searchTerm } = req.body;
  
  if (!searchTerm) {
    return res.status(400).json({ error: "Username is required" });
  }

  try {
    const users = await Users.findAll({
      attributes: ['username' ,'profilePicture',"verified"],
      limit: 30  // Restrict to 30 results

    });

    const fuse = new Fuse(users, {
      keys: ["username"],
      threshold: 0.3,
    });

    const results = fuse.search(searchTerm);
    res.json(results.map(result => result.item));
  } catch (error) {
    console.error('Error fetching users:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});

const storageStoryMedia = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, './cloud/storyMedia'); // Folder for story uploads
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + path.extname(file.originalname));
  }
});

const uploadStoryMedia = multer({ storage: storageStoryMedia });

// Replace the existing create-story route with the following:

const uploadStoryMediaFields = multer({ storage: storageStoryMedia }).fields([
  { name: "video", maxCount: 1 },
  { name: "images", maxCount: 20 }
]);

router.post('/create-story', validateToken, uploadStoryMediaFields, async (req, res) => {
  try {
    // Parse storyDetails JSON string from req.body
    const storyDetails = req.body.storyDetails ? JSON.parse(req.body.storyDetails) : {};
    const canvasBgColor = storyDetails.bgcolor;
    const stageWidth = storyDetails.width;
    const stageHeight = storyDetails.height;

    // Parse metadata (ensure it's coming as a JSON string)
    let parsedMetadata = JSON.parse(req.body.metadata || '[]');
    const userId = req.user.id;

    // Retrieve files from both fields.
    const videoFiles = req.files.video || [];
    const imageFiles = req.files.images || [];

    // Start a transaction
    const t = await sequelize.transaction();
    try {
      // Create the Story, now including stage dimensions
      const newStory = await Story.create(
        { 
          userId, 
          bgcolor: canvasBgColor,
          width: stageWidth,
          height: stageHeight 
        },
        { transaction: t }
      );

      await Users.increment('posts', {
        where: { id: userId },
        transaction: t
      });
  
       
      // Update each metadata item with the uploaded file filename.
      // For video element use the first file from the video field;
      // For images, use the order of the imageFiles array.
      parsedMetadata = parsedMetadata.map(item => {
        if (item.element_type === "video") {
          if (videoFiles.length) {
            item.content = videoFiles[0].filename;
          }
        } else {
          // Assume non-video items are images.
          if (imageFiles.length) {
            // Assign in order and remove the file from array.
            const file = imageFiles.shift();
            if (file) {
              item.content = file.filename;
            }
          }
        }
        // Ensure a default element_type exists.
        item.element_type = item.element_type || (item.content && item.content.endsWith('.mp4') ? "video" : "image");
        // default isPost if missing
        item.isPost = item.isPost || false;
        return item;
      });

      // Insert each metadata record; attach text_color only when element_type is "text"
      for (const item of parsedMetadata) {
        await StoryMetaData.create(
          {
            story_id: newStory.storyId,
            element_type: item.element_type,
            background_color: item.background_color,
            content: item.content,
            position_x: item.position_x,
            position_y: item.position_y,
            width: item.width,
            height: item.height,
            rotation: item.rotation,
            scale: item.scale,
            isPost: item.isPost,
            offset_x: item.offset_x,
            offset_y: item.offset_y,
            z_index: item.z_index,
            scaled: item.scaled, // carry over the scaled boolean
            text_color: item.element_type === "text" ? item.text_color : null,
          },
          { transaction: t }
        );
      }

      await t.commit();
      res.json({ success: true, storyId: newStory});
    } catch (error) {
      await t.rollback();
      console.error("Transaction error:", error);
      res.status(500).json({ error: "Internal server error" });
    }
  } catch (error) {
    console.error("Error creating story:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// New route for fetching story metadata without full content
router.get('/stories-metadata', validateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const last24Hours = new Date(Date.now() - 24 * 60 * 60 * 1000);

    // First, get all users that the current user follows
    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });

    // Get array of following IDs and include own id
    const followingIds = following.map(f => f.followingId);
    const allUserIds = [...followingIds, userId];

    // Get basic user info and story metadata (without full content)
    const storiesMetadata = await Users.findAll({
      where: { id: allUserIds },
      attributes: ['id', 'username', 'profilePicture', 'verified'],
      include: [{
        model: Story,
        as: 'Stories',
        where: {
          createdAt: {
            [Op.gte]: last24Hours
          }
        },
        attributes: ['storyId', 'createdAt'],
        required: false
      }]
    });

    // Format the response to include allViewed flag
    const formattedResponse = await Promise.all(
      storiesMetadata.map(async user => {
        const userData = user.get({ plain: true });
        if (!userData.Stories || userData.Stories.length === 0) {
          return {
            userId: userData.id,
            username: userData.username,
            profilePicture: userData.profilePicture,
            verified: userData.verified,
            stories: [],
            hasStories: false,
            allViewed: true
          };
        }

        const storyIds = userData.Stories.map(story => story.storyId);

        // Get view status only for current user
        const viewRecords = await StoryView.findAll({
          where: { userId, storyId: { [Op.in]: storyIds } }
        });
        
        const viewedStoryIds = new Set(viewRecords.map(v => v.storyId));
        
        // Check if all stories have been viewed
        const allViewed = storyIds.every(id => viewedStoryIds.has(id));
        
        // For prefetching, provide full data for user's own stories and first 2 users
        const shouldPrefetch = 
          String(userData.id) === String(userId) || 
          userData.id === followingIds[0] || 
          userData.id === followingIds[1];

        return {
          userId: userData.id,
          username: userData.username,
          profilePicture: userData.profilePicture,
          verified: userData.verified,
          stories: shouldPrefetch ? [] : [], // We'll fetch the full stories on demand
          hasStories: userData.Stories.length > 0,
          allViewed,
          storyCount: userData.Stories.length
        };
      })
    );

    // Sort - current user first, then users with unviewed stories
    const result = formattedResponse.sort((a, b) => {
      if (a.userId === userId) return -1;
      if (b.userId === userId) return 1;
      if (a.allViewed && !b.allViewed) return 1;
      if (!a.allViewed && b.allViewed) return -1;
      return 0;
    });

    res.json(result);
  } catch (error) {
    console.error("Error fetching stories metadata:", error);
    res.status(500).json({ 
      error: 'Internal server error',
      details: process.env.NODE_ENV === 'development' ? error.message : undefined
    });
  }
});

// Add a route to fetch a specific user's stories
router.get('/user-stories/:userId', validateToken, async (req, res) => {
  try {
    const viewerId = req.user.id;
    const { userId } = req.params;
    const last24Hours = new Date(Date.now() - 24 * 60 * 60 * 1000);

    // Find the user and their stories
    const userWithStories = await Users.findOne({
      where: { id: userId },
      attributes: ['id', 'username', 'profilePicture', 'verified'],
      include: [{
        model: Story,
        as: 'Stories',
        where: {
          createdAt: {
            [Op.gte]: last24Hours
          }
        },
        include: [{
          model: StoryMetaData,
          as: 'metadata',
          required: false,
          attributes: [
            'element_type',
            'background_color',
            'text_color',
            'content',
            'position_x',
            'position_y',
            'width',
            'height',
            'rotation',
            'scale',
            'isPost',
            'scaled',
            'z_index',
          ]
        }],
        required: false,
        order: [['createdAt', 'DESC']]
      }]
    });

    if (!userWithStories) {
      return res.status(404).json({ message: "User not found" });
    }

    const userData = userWithStories.get({ plain: true });
    
    // If no stories, return empty array
    if (!userData.Stories || userData.Stories.length === 0) {
      return res.json({
        userId: userData.id,
        username: userData.username,
        profilePicture: userData.profilePicture,
        verified: userData.verified,
        stories: []
      });
    }

    // Extract storyIds to fetch view records in one go
    const storyIds = userData.Stories.map(story => story.storyId);

    // Fetch view records for current viewer
    const viewRecords = await StoryView.findAll({
      where: { userId: viewerId, storyId: { [Op.in]: storyIds } }
    });
    const viewedSet = new Set(viewRecords.map(v => v.storyId));

    // Get view counts for each story
    const viewCounts = await StoryView.findAll({
      attributes: [
        'storyId',
        [Sequelize.fn('COUNT', Sequelize.col('storyId')), 'viewsCount']
      ],
      where: {
        storyId: { [Op.in]: storyIds },
        userId: { [Op.ne]: userData.id }
      },
      group: ['storyId']
    });

    const viewCountMap = {};
    viewCounts.forEach(vc => {
      viewCountMap[vc.storyId] = parseInt(vc.get('viewsCount'));
    });

    // Format the stories with view information
    const stories = userData.Stories.map(story => ({
      storyId: story.storyId,
      bgcolor: story.bgcolor,
      stageHeight: story.height,
      stageWidth: story.width,
      createdAt: story.createdAt,
      viewed: viewedSet.has(story.storyId),
      viewsCount: viewCountMap[story.storyId] || 0,
      isLiked: likedSet.has(story.storyId), // NEW: Add isLiked flag
      elements: (story.metadata || []).map(meta => ({
        z_index: meta.z_index,
        type: meta.element_type,
        backgroundColor: meta.background_color,
        textColor: meta.text_color,
        content: meta.content,
        position: {
          x: meta.position_x || 0,
          y: meta.position_y || 0
        },
        dimensions: {
          width: meta.width || 0,
          height: meta.height || 0
        },
        transform: {
          rotation: meta.rotation || 0,
          scale: meta.scale || 1,
          isPost: meta.isPost || false
        }
      }))
    }));

    res.json({
      userId: userData.id,
      username: userData.username,
      profilePicture: userData.profilePicture,
      verified: userData.verified,
      stories
    });
  } catch (error) {
    console.error("Error fetching user stories:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Add a new route to get shorts details
router.get('/shorts/:id', validateToken, async (req, res) => {
  const shortId = req.params.id;
  const userId = req.user?.id;

  try {
    const short = await Post.findOne({
      where: { id: shortId, isShort: true },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });

    if (!short) {
      return res.status(404).json({ error: "Short not found" });
    }

    // Get interactions if userId is provided
    let userInteraction = {
      liked: false,
      saved: false,
      isFollowing: false,
    };

    if (userId) {
      const [likeStatus, saveStatus, followStatus] = await Promise.all([
        PostLike.findOne({
          where: { userId, postId: shortId },
          raw: true,
        }),
        PostSaved.findOne({
          where: { userId, postId: shortId },
          raw: true,
        }),
        Follow.findOne({
          where: { followerId: userId, followingId: short.author.id },
          raw: true,
        }),
      ]);

      userInteraction.liked = !!likeStatus;
      userInteraction.saved = !!saveStatus;
      userInteraction.isFollowing = !!followStatus;
    }

    // Format the response with the updated structure
    const response = {
      id: short.id,
      content: short.content,
      media: short.media || [], // Array of media objects
      views: short.views,
      likes: short.likes,
      comments: short.comments,
      createdAt: short.createdAt,
      updatedAt: short.updatedAt,
      author: {
        id: short.author.id,
        username: short.author.username,
        profilePicture: short.author.profilePicture
      },
      userInteraction: userInteraction
    };
    
    res.json(response);
    
  } catch (error) {
    console.error('Error fetching short:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Delete post route with authorization check and cleanup
router.delete('/:id', validateToken, async (req, res) => {
  const t = await sequelize.transaction();
  
  try {
    const postId = req.params.id;
    const userId = req.user.id; // User ID from access token

    // Find the post with media information
    const post = await Post.findOne({
      where: { id: postId }
    });

    // Check if post exists
    if (!post) {
      return res.status(404).json({ error: "Post not found" });
    }

    // Check if user is the author of the post
    if (post.authorId !== userId) {
      return res.status(403).json({ error: "Unauthorized: You can only delete your own posts" });
    }

    // Delete related records in transaction
    await PostLike.destroy({ where: { postId }, transaction: t });
    await PostSaved.destroy({ where: { postId }, transaction: t });
    await PostHashtags.destroy({ where: { postId }, transaction: t });
    await Mention.destroy({ where: { postId }, transaction: t });
    
    // Fix: Use correct column names in PostRelation model
    // Based on your model definition, PostRelation uses ancestorId and descendantId
    await PostRelation.destroy({ where: { ancestorId: postId }, transaction: t });
    await PostRelation.destroy({ where: { descendantId: postId }, transaction: t });
    
    // Delete the post itself
    await Post.destroy({ where: { id: postId }, transaction: t });
    
    // Decrement the user's post count
    await Users.decrement('posts', { where: { id: userId }, transaction: t });
    
    // Commit the transaction
    await t.commit();
    
    
    // Track deleted files for logging
    const deletedFiles = [];
    const failedFiles = [];
    
    // Delete media files after transaction succeeds
    if (post.media && Array.isArray(post.media)) {
      for (const media of post.media) {
        try {
          // Skip if no URL is provided
          if (!media.url) continue;
          
          // Extract filename from URL
          const urlParts = media.url.split('/');
          const filename = urlParts[urlParts.length - 1];
          
          // Determine correct virtual folder based on media type and post type
          let folder;
          if (post.isShort) {
            folder = media.type === 'video' ? 'shortVideos' : 'shortImages';
          } else {
            folder = media.type === 'video' ? 'postVideos' : 'postImages';
          }
          
          // Delete from B2
          await deleteFromB2(filename, folder);
        } catch (fileError) {
          console.error(`Error deleting media file for post ${postId}:`, fileError);
        }
      }
    }
    
    // Also delete the thumbnail if it exists and is different from media files
    if (post.thumbnail && (!post.media || !post.media.some(m => m.url === post.thumbnail))) {
      try {
        // Extract filename from URL
        const urlParts = post.thumbnail.split('/');
        const filename = urlParts[urlParts.length - 1];
        
        await deleteFromB2(filename, 'postThumbnails');
      } catch (thumbError) {
        console.error(`Error deleting thumbnail for post ${postId}:`, thumbError);
      }
    }
    

    res.json({ 
      success: true,
      message: "Post deleted successfully",
      mediaDeleted: deletedFiles.length,
      mediaFailed: failedFiles.length
    });
  } catch (error) {
    // Rollback transaction in case of error
    await t.rollback();
    console.error("Error deleting post:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

module.exports = router;

