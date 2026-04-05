const express = require('express');
const router = express.Router();
const moment = require('moment-timezone');
const { Papers, Users, Post, PostView, PostLike, PostSaved, Follow, PaperPosts } = require('../models');
const { Op } = require('sequelize');
const GoogleApi = require('../middlewares/GoogleApi');
const { validateToken, authenticateToken } = require('../middlewares/AuthMiddleware');
const paperScheduler = require('../schedulers/paperScheduler');

// NEW: Main paper fetching algorithm for "the-paper" page
// Implements the 5-step process: check scheduled paper, verify time, check existing paper, generate if needed
router.get('/the-paper', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const currentTime = new Date();
    
    // Use IST timezone for consistent date handling
    const moment = require('moment-timezone');
    const todayDate = moment().tz('Asia/Kolkata').format('YYYY-MM-DD');
    const currentIST = moment().tz('Asia/Kolkata');
    const currentHour = currentIST.hour();
    const currentMinute = currentIST.minute();
    const currentTimeString = `${currentHour.toString().padStart(2, '0')}:${currentMinute.toString().padStart(2, '0')}`;

    console.log(`🕐 [DATE DEBUG] Current IST date: ${todayDate}, time: ${currentTimeString}`);

    // Step 1: Check if user has a scheduled paper today
    const scheduledPaper = await Papers.findOne({
      where: {
        authorId: userId,
        status: 'active',
        processingStatus: 'completed'
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });

    if (!scheduledPaper) {
      return res.json({
        success: false,
        message: 'No active paper found for today',
        paper: null,
        posts: []
      });
    }    // Step 2: Verify current time has passed the scheduled delivery time
    // Parse 12-hour format (e.g., "12:00 AM", "10:00 PM") to 24-hour format
    const [time, period] = scheduledPaper.deliveryTime.split(' ');
    const [hour, minute] = time.split(':').map(Number);
    
    let scheduledHour24 = hour;
    if (period === 'PM' && hour !== 12) {
      scheduledHour24 = hour + 12;
    } else if (period === 'AM' && hour === 12) {
      scheduledHour24 = 0;
    }
    
    const scheduledTimeInMinutes = scheduledHour24 * 60 + minute;
    const currentTimeInMinutes = currentHour * 60 + currentMinute;

    console.log(`🕐 [TIME DEBUG] Scheduled: ${scheduledPaper.deliveryTime} (${scheduledHour24}:${minute.toString().padStart(2, '0')}), Current: ${currentTimeString}`);

    if (currentTimeInMinutes < scheduledTimeInMinutes) {
      return res.json({
        success: false,
        message: `Paper will be available at ${scheduledPaper.deliveryTime}`,
        paper: null,
        posts: [],
        scheduledTime: scheduledPaper.deliveryTime,
        currentTime: currentTimeString
      });
    }

    // Step 3: Check if today's paper already exists in PaperPosts
    let existingPaperPost = await PaperPosts.findOne({
      where: {
        paperId: scheduledPaper.id,
        paperDate: todayDate
      }
    });

    // Step 4: If not found, generate it using the paper generation algorithm
    if (!existingPaperPost) {
      console.log(`Generating new paper for ${scheduledPaper.title} on ${todayDate}`);
        try {
        // Generate recommendations using the existing sophisticated algorithm
        const recommendationsData = await generatePaperRecommendations(scheduledPaper, userId);
        
        if (!recommendationsData || !recommendationsData.recommendations || recommendationsData.recommendations.length === 0) {
          return res.json({
            success: false,
            message: 'No suitable content found for today\'s paper',
            paper: null,
            posts: []
          });
        }        // Create new PaperPost with generated recommendations
        const postIds = recommendationsData.recommendations.map(rec => rec.id);
        existingPaperPost = await PaperPosts.create({
          paperId: scheduledPaper.id,
          paperDate: todayDate,
          deliveryTime: scheduledPaper.deliveryTime,
          posts: postIds,
          status: 'delivered'
        });

        console.log(`Successfully generated paper with ${postIds.length} posts`);
      } catch (generationError) {
        console.error('Error generating paper:', generationError);
        return res.status(500).json({
          success: false,
          message: 'Failed to generate today\'s paper',
          error: generationError.message
        });
      }
    }    // Step 5: Get the posts with full details and return to client
    const postsWithDetails = await PaperPosts.getPaperPostsWithDetails(existingPaperPost.id);

    res.json({
      success: true,      paper: {        ...existingPaperPost.toJSON(),
        title: scheduledPaper.title,
        description: scheduledPaper.description,
        isRead: existingPaperPost.read || false, // Use actual read field from database
        userReadStatus: existingPaperPost.read || false, // Alias for frontend compatibility
        isNewlyGenerated: !existingPaperPost.createdAt || new Date() - existingPaperPost.createdAt < 60000 // Less than 1 minute old
      },
      posts: postsWithDetails,
      metadata: {
        deliveryTime: scheduledPaper.deliveryTime,
        postCount: scheduledPaper.postCount,
        generatedAt: existingPaperPost.createdAt,
        paperDate: todayDate
      }
    });

  } catch (error) {
    console.error('Error in main paper fetching algorithm:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch today\'s paper',
      error: error.message
    });
  }
});

// Helper function to generate paper recommendations (extracted from existing algorithm)
async function generatePaperRecommendations(paper, userId) {
  try {
    const currentTime = new Date();
    
    // Get user data (interests and location)
    const currentUser = await Users.findOne({
      where: { id: userId },
      attributes: ['id', 'intrest', 'state'],
      raw: true
    });

    if (!currentUser) {
      throw new Error('User not found');
    }

    const userInterests = currentUser.intrest || [];
    const userState = currentUser.state;
    
    // Get posts user has already viewed to exclude them
    const viewedPostRecords = await PostView.findAll({
      where: { userId },
      attributes: ['postId']
    });
    const viewedPostIds = new Set(viewedPostRecords.map(view => view.postId));
    
    // Get user's followed users for social signals
    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });
    const followingIds = following.map(follow => follow.followingId);
    
    // Extract recommendation criteria from paper metadata
    const metadata = paper.metadata || {};
    const {
      tone,
      regions = [],
      summary,
      audience,
      language = 'english',
      focus_level,
      intent_type,
      primary_topics = [],
      content_filters = [],
      excluded_topics = [],
      secondary_topics = [],
      preferred_sources = []
    } = metadata;
    
    // Build dynamic query conditions
    let whereConditions = {
      isShort: false, // Focus on full posts for papers
      id: { [Op.notIn]: Array.from(viewedPostIds) } // Exclude viewed posts
    };
    
    // Time-based prioritization (last 24 hours preference)
    const last24Hours = new Date(currentTime.getTime() - 24 * 60 * 60 * 1000);
    
    // Fetch posts with sophisticated filtering
    let posts = await Post.findAll({
      where: whereConditions,
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'verified', 'state', 'followers', 'posts']
      }],
      limit: paper.postCount * 3, // Fetch more than needed for better scoring
      order: [['createdAt', 'DESC']]
    });

    // Use the existing sophisticated scoring algorithm
    const calculatePostScore = (post) => {
      const plainPost = post.get({ plain: true });
      let totalScore = 0;
      let scoreBreakdown = {};
      
      // 1. Time Decay Score (25%) - Prioritize recent content, especially last 24h
      const ageInHours = (currentTime - new Date(plainPost.createdAt)) / (1000 * 60 * 60);
      let timeScore;
      if (ageInHours <= 24) {
        timeScore = 1.0; // Maximum score for last 24 hours
      } else {
        timeScore = Math.exp(-0.03 * ageInHours); // Slower decay than shorts
      }
      scoreBreakdown.timeScore = timeScore * 0.25;
      
      // 2. Description Context Matching (30%) - Most important factor
      let contextScore = 0;
      const postContent = (plainPost.content || plainPost.description || '').toLowerCase();
      const paperDescription = (paper.description || '').toLowerCase();
      
      // Extract key terms from paper description for context matching
      const paperKeywords = paperDescription.split(/\s+/).filter(word => word.length > 3);
      const matchingKeywords = paperKeywords.filter(keyword => 
        postContent.includes(keyword)
      ).length;
      
      contextScore = Math.min(matchingKeywords / Math.max(paperKeywords.length, 1), 1.0);
      
      // Boost for primary topics matching
      if (primary_topics && primary_topics.length > 0) {
        const topicMatches = primary_topics.filter(topic => 
          postContent.includes(topic.toLowerCase())
        ).length;
        contextScore += (topicMatches / primary_topics.length) * 0.3;
      }
        // Boost for secondary topics
      if (secondary_topics && secondary_topics.length > 0) {
        const secondaryMatches = secondary_topics.filter(topic => 
          postContent.includes(topic.toLowerCase())
        ).length;
        contextScore += (secondaryMatches / secondary_topics.length) * 0.1;
      }
      
      contextScore = Math.min(contextScore, 1.0);
      scoreBreakdown.contextScore = contextScore * 0.30;
      
      // 3. User Region/State Matching (15%)
      let regionScore = 0;
      if (userState && plainPost.author.state) {
        if (userState === plainPost.author.state) {
          regionScore = 1.0; // Same state
        } else if (regions.includes(userState) || regions.includes(plainPost.author.state)) {
          regionScore = 0.7; // State mentioned in metadata regions
        }
      }
      scoreBreakdown.regionScore = regionScore * 0.15;
      
      // 4. Metadata Quality Scoring (10%)
      let metadataScore = 0;
      
      // Language matching
      if (language === 'english') metadataScore += 0.3;
      
      // Audience matching - could be enhanced with user profile data
      if (audience && userInterests.length > 0) {
        const audienceMatch = userInterests.some(interest => 
          audience.toLowerCase().includes(interest.toLowerCase())
        );
        if (audienceMatch) metadataScore += 0.3;
      }
      
      // Intent type boost for news content
      if (intent_type === 'news' || intent_type === 'informational') {
        metadataScore += 0.2;
      }
      
      // Focus level consideration
      if (focus_level === 'high' || focus_level === 'medium') {
        metadataScore += 0.2;
      }
      
      scoreBreakdown.metadataScore = metadataScore * 0.10;
      
      // 5. Engagement Score (10%)
      const engagementScore = 
        (plainPost.views * 0.10) + 
        (plainPost.likes * 0.20) + 
        (plainPost.comments * 0.35) + 
        (plainPost.shared * 0.35);
      
      const normalizedEngagement = Math.log(engagementScore + 1) / 15;
      scoreBreakdown.engagementScore = normalizedEngagement * 0.10;
      
      // 6. Author Credibility (5%)
      const isVerified = plainPost.author.verified ? 1 : 0;
      const followersFactor = plainPost.author.followers / (plainPost.author.followers + 200);
      const postsFactor = plainPost.author.posts / (plainPost.author.posts + 100);
      
      const authorCredibility = 
        (isVerified * 0.5) + 
        (followersFactor * 0.3) + 
        (postsFactor * 0.2);
      
      scoreBreakdown.authorScore = authorCredibility * 0.05;
      
      // 7. Social Signals (3%)
      let socialScore = 0;
      if (followingIds.includes(plainPost.author.id)) {
        socialScore = 1.0; // User follows the author
      }
      scoreBreakdown.socialScore = socialScore * 0.03;
      
      // 8. Content Filters and Exclusions (2%)
      let filterScore = 1.0;
      
      // Check excluded topics
      if (excluded_topics && excluded_topics.length > 0) {
        const hasExcludedContent = excluded_topics.some(topic => 
          postContent.includes(topic.toLowerCase())
        );
        if (hasExcludedContent) filterScore = 0.1; // Heavy penalty
      }
      
      // Check content filters
      if (content_filters && content_filters.length > 0) {
        const passesFilters = content_filters.every(filter => {
          // Implement filter logic based on filter type
          return true; // Placeholder - would need specific filter implementation
        });
        if (!passesFilters) filterScore *= 0.5;
      }
      
      scoreBreakdown.filterScore = filterScore * 0.02;
      
      // Calculate total score
      totalScore = Object.values(scoreBreakdown).reduce((sum, score) => sum + score, 0);
      
      return {
        post: plainPost,
        score: totalScore,
        breakdown: scoreBreakdown
      };
    };

    // Score and rank all posts
    const scoredPosts = posts.map(calculatePostScore);
    
    // Sort by score and take top posts
    const rankedPosts = scoredPosts
      .sort((a, b) => b.score - a.score)
      .slice(0, paper.postCount);
    
    // Get interaction data for final posts
    const finalPostIds = rankedPosts.map(item => item.post.id);
    
    const [likeRecords, saveRecords] = await Promise.all([
      PostLike.findAll({
        where: { userId, postId: { [Op.in]: finalPostIds } },
        attributes: ['postId']
      }),
      PostSaved.findAll({
        where: { userId, postId: { [Op.in]: finalPostIds } },
        attributes: ['postId']
      })
    ]);
    
    const likedPostIds = new Set(likeRecords.map(like => like.postId));
    const savedPostIds = new Set(saveRecords.map(save => save.postId));
    
    // Format final response
    const recommendations = rankedPosts.map(item => ({
      id: item.post.id,
      title: item.post.title,
      content: item.post.content,
      description: item.post.description,
      thumbnail: item.post.thumbnail,
      media: item.post.media || [],
      views: item.post.views,
      likes: item.post.likes,
      comments: item.post.comments,
      shares: item.post.shared,
      bookmarks: item.post.bookmarks,
      createdAt: item.post.createdAt,
      updatedAt: item.post.updatedAt,
      category: item.post.category || item.post.categories,
      isShort: item.post.isShort,
      score: item.score,
      scoreBreakdown: item.breakdown,
      author: {
        id: item.post.author.id,
        username: item.post.author.username,
        profilePicture: item.post.author.profilePicture,
        fullName: (item.post.author.firstName || '') + ' ' + (item.post.author.lastName || ''),
        verified: item.post.author.verified,
        state: item.post.author.state
      },
      userInteraction: {
        liked: likedPostIds.has(item.post.id),
        saved: savedPostIds.has(item.post.id),
        viewed: false
      }
    }));

    return {
      success: true,
      recommendations,
      totalFound: recommendations.length
    };

  } catch (error) {
    console.error('Error generating recommendations:', error);
    return {
      success: false,
      error: error.message
    };
  }
}

// NEW: Mark paper as read for a user
router.post('/mark-read/:paperPostId', authenticateToken, async (req, res) => {
  try {
    const { paperPostId } = req.params;
    const userId = req.user.id;

    await PaperPosts.markAsRead(paperPostId, userId);

    res.json({
      success: true,
      message: 'Paper marked as read'
    });
  } catch (error) {
    console.error('Error marking paper as read:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to mark paper as read',
      error: error.message
    });
  }
});

// NEW: Mark paper as unread for a user
router.post('/mark-unread/:paperPostId', authenticateToken, async (req, res) => {
  try {
    const { paperPostId } = req.params;
    const userId = req.user.id;

    await PaperPosts.markAsUnread(paperPostId, userId);

    res.json({
      success: true,
      message: 'Paper marked as unread'
    });
  } catch (error) {
    console.error('Error marking paper as unread:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to mark paper as unread',
      error: error.message
    });
  }
});

// NEW: Get papers list with read status for MyPapers page
router.get('/my-papers-list', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const { 
      filter = 'all', // 'all', 'today', 'yesterday', 'unread', 'read'
      limit = 20, 
      page = 1 
    } = req.query;
    
    const moment = require('moment-timezone');
    const todayDate = moment().tz('Asia/Kolkata').format('YYYY-MM-DD');
    const yesterdayDate = moment().tz('Asia/Kolkata').subtract(1, 'day').format('YYYY-MM-DD');
    
    console.log(`📋 [MY-PAPERS LIST] Fetching papers for user: ${userId}, filter: ${filter}, today: ${todayDate}, yesterday: ${yesterdayDate}`);

    // Get user's papers first
    const userPapers = await Papers.findAll({
      where: { 
        authorId: userId,
        status: 'active'
      },
      attributes: ['id', 'title', 'description', 'deliveryTime', 'postCount']
    });

    if (userPapers.length === 0) {
      console.log(`❌ [MY-PAPERS LIST] No active papers found for user: ${userId}`);
      return res.json({
        success: true,
        papers: [],
        message: 'No active papers found'
      });
    }
    
    console.log(`📄 [MY-PAPERS LIST] User has ${userPapers.length} active papers`);

    const paperIds = userPapers.map(p => p.id);

    // Build where clause for PaperPosts based on filter
    let whereClause = {
      paperId: { [Op.in]: paperIds }
    };

    // Apply date filters
    if (filter === 'today') {
      whereClause.paperDate = todayDate;
    } else if (filter === 'yesterday') {
      whereClause.paperDate = yesterdayDate;
    }

    // Get paper posts with pagination
    const paperPosts = await PaperPosts.findAll({
      where: whereClause,
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'deliveryTime', 'postCount'],
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username']
        }]
      }],
      order: [['paperDate', 'DESC'], ['deliveryTime', 'DESC']],
      limit: parseInt(limit),
      offset: (parseInt(page) - 1) * parseInt(limit)
    });
    
    console.log(`🔍 [MY-PAPERS LIST] Found ${paperPosts.length} paper posts`);

    // Add read status and filter by read/unread if needed
    const papersWithReadStatus = paperPosts
      .map(paperPost => {
        const plainPaperPost = paperPost.get({ plain: true });
        const isRead = plainPaperPost.read || false;
        
        return {
          id: plainPaperPost.id,
          paperId: plainPaperPost.paperId,
          paperDate: plainPaperPost.paperDate,
          deliveryTime: plainPaperPost.deliveryTime,
          status: plainPaperPost.status,
          createdAt: plainPaperPost.createdAt,
          isRead,
          readAt: isRead ? plainPaperPost.updatedAt : null,
          paper: plainPaperPost.paper,
          postCount: plainPaperPost.posts ? plainPaperPost.posts.length : 0
        };
      })
      .filter(paper => {
        if (filter === 'unread') return !paper.isRead;
        if (filter === 'read') return paper.isRead;
        return true;
      });

    // Sort: Unread first, then by date
    papersWithReadStatus.sort((a, b) => {
      // Primary sort: unread papers first
      if (a.isRead !== b.isRead) {
        return a.isRead ? 1 : -1;
      }
      
      // Secondary sort: by date (most recent first)
      const dateA = new Date(a.paperDate + ' ' + a.deliveryTime);
      const dateB = new Date(b.paperDate + ' ' + b.deliveryTime);
      return dateB - dateA;
    });
    
    console.log(`✅ [MY-PAPERS LIST] Returning ${papersWithReadStatus.length} filtered papers`);

    res.json({
      success: true,
      papers: papersWithReadStatus,
      totalCount: papersWithReadStatus.length,
      filter,
      currentPage: parseInt(page)
    });

  } catch (error) {
    console.error('❌ [MY-PAPERS LIST] Error fetching papers list:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch papers list',
      error: error.message
    });
  }
});
// POST create new paper with enhanced validation (from Paper.js)
router.post('/create', validateToken, async (req, res) => {
  try {
    const { title, description, deliveryTime, postCount } = req.body;
    const authorId = req.user.id;

    // Validate required fields
    if (!title || !description || !deliveryTime || !postCount) {
      return res.status(400).json({
        error: 'Missing required fields',
        required: ['title', 'description', 'deliveryTime', 'postCount']
      });
    }

    // Validate field lengths
    if (title.length > 35) {
      return res.status(400).json({
        error: 'Title must be 35 characters or less'
      });
    }

    if (description.length > 4000) {
      return res.status(400).json({
        error: 'Description must be 4000 characters or less'
      });
    }

    // Create the paper record first
    const paper = await Papers.create({
      title: title.trim(),
      description: description.trim(),
      authorId,
      deliveryTime,
      postCount,
      processingStatus: 'processing'
    });

    // Process the description with Google GenAI in background
    try {
      const metadata = await GoogleApi.processDescription(description);
      
      // Update paper with generated metadata
      await paper.update({
        metadata,
        processingStatus: 'completed'
      });

      // Return success response with paper data
      const updatedPaper = await Papers.findByPk(paper.id, {
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'firstName', 'lastName']
        }]
      });

      res.status(201).json({
        success: true,
        message: 'Paper created successfully',
        paper: updatedPaper
      });

    } catch (aiError) {
      console.error('AI Processing Error:', aiError);
      
      // Update paper with error status
      await paper.update({
        processingStatus: 'failed',
        processingError: aiError.message
      });

      // Still return success since paper was created, just AI processing failed
      res.status(201).json({
        success: true,
        message: 'Paper created successfully, but AI processing failed',
        paper: await Papers.findByPk(paper.id, {
          include: [{
            model: Users,
            as: 'author',
            attributes: ['id', 'username', 'firstName', 'lastName']
          }]
        }),
        warning: 'AI metadata generation failed'
      });
    }

  } catch (error) {
    console.error('Paper Creation Error:', error);
    res.status(500).json({
      error: 'Failed to create paper',
      details: error.message
    });
  }
});

// GET user's own papers (from Paper.js)
router.get('/my-papers', validateToken, async (req, res) => {
  try {
    const authorId = req.user.id;
    
    const papers = await Papers.findAll({
      where: { authorId },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'firstName', 'lastName']
      }],
      order: [['createdAt', 'DESC']]
    });

    res.json({
      success: true,
      papers
    });

  } catch (error) {
    console.error('Get Papers Error:', error);
    res.status(500).json({
      error: 'Failed to fetch papers',
      details: error.message
    });
  }
});

// PATCH update paper status (from Paper.js)
router.patch('/:id/status', validateToken, async (req, res) => {
  try {
    const { id } = req.params;
    const { status } = req.body;
    
    if (!['active', 'paused', 'archived'].includes(status)) {
      return res.status(400).json({
        error: 'Invalid status. Must be: active, paused, or archived'
      });
    }

    const paper = await Papers.findByPk(id);
    
    if (!paper) {
      return res.status(404).json({
        error: 'Paper not found'
      });
    }

    if (paper.authorId !== req.user.id) {
      return res.status(403).json({
        error: 'Access denied'
      });
    }

    await paper.update({ status });

    res.json({
      success: true,
      message: 'Paper status updated successfully',
      paper
    });

  } catch (error) {
    console.error('Update Paper Status Error:', error);
    res.status(500).json({
      error: 'Failed to update paper status',
      details: error.message
    });
  }
});

// GET all papers for a user
router.get('/user/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
      const papers = await Papers.findAll({
      where: { authorId: userId },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }],
      order: [['createdAt', 'DESC']]
    });
    
    res.json({ success: true, papers });
  } catch (error) {
    console.error('Error fetching user papers:', error);
    res.status(500).json({ success: false, message: 'Failed to fetch papers' });
  }
});

// GET all papers (for admin or public view)
router.get('/', async (req, res) => {
  try {
    const { page = 1, limit = 10, status = 'active' } = req.query;
    const offset = (page - 1) * limit;
      const papers = await Papers.findAndCountAll({
      where: { status },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }],
      limit: parseInt(limit),
      offset: parseInt(offset),
      order: [['createdAt', 'DESC']]
    });
    
    res.json({ 
      success: true, 
      papers: papers.rows,
      totalCount: papers.count,
      currentPage: parseInt(page),
      totalPages: Math.ceil(papers.count / limit)
    });
  } catch (error) {
    console.error('Error fetching papers:', error);
    res.status(500).json({ success: false, message: 'Failed to fetch papers' });
  }
});

// GET single paper by ID
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    
    const paper = await Papers.findByPk(id, {
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });
    
    if (!paper) {
      return res.status(404).json({ success: false, message: 'Paper not found' });
    }
    
    res.json({ success: true, paper });
  } catch (error) {
    console.error('Error fetching paper:', error);
    res.status(500).json({ success: false, message: 'Failed to fetch paper' });
  }
});

// POST create new paper
router.post('/', async (req, res) => {
  try {
    const { title, description, authorId, deliveryTime, postCount } = req.body;
    
    // Validate required fields
    if (!title || !description || !authorId || !deliveryTime) {
      return res.status(400).json({ 
        success: false, 
        message: 'Missing required fields: title, description, authorId, deliveryTime' 
      });
    }
    
    // Validate author exists
    const author = await Users.findByPk(authorId);
    if (!author) {
      return res.status(404).json({ success: false, message: 'Author not found' });
    }
    
    // Create the paper
    const paper = await Papers.create({
      title,
      description,
      authorId,
      deliveryTime,
      postCount: postCount || 30,
      status: 'active',
      processingStatus: 'pending'
    });
    
    // Process with Google GenAI in background
    try {
      const aiResponse = await GoogleApi.processDescription(description);
      
      await Papers.update({
        metadata: aiResponse,
        processingStatus: 'completed'
      }, {
        where: { id: paper.id }
      });
      
      console.log('Paper processed successfully with AI:', paper.id);
    } catch (aiError) {
      console.error('AI processing failed:', aiError);
      await Papers.update({
        processingStatus: 'failed',
        processingError: aiError.message
      }, {
        where: { id: paper.id }
      });
    }
    
    // Fetch the created paper with author info
    const createdPaper = await Papers.findByPk(paper.id, {
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });
    
    res.status(201).json({ success: true, paper: createdPaper });
  } catch (error) {
    console.error('Error creating paper:', error);
    res.status(500).json({ success: false, message: 'Failed to create paper' });
  }
});

// PUT update paper
router.put('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { title, description, deliveryTime, postCount, status } = req.body;
    
    const paper = await Papers.findByPk(id);
    if (!paper) {
      return res.status(404).json({ success: false, message: 'Paper not found' });
    }
    
    // Update the paper
    await Papers.update({
      title,
      description,
      deliveryTime,
      postCount,
      status
    }, {
      where: { id }
    });
    
    // If description changed, reprocess with AI
    if (description && description !== paper.description) {
      try {
        const aiResponse = await GoogleApi.processDescription(description);
        
        await Papers.update({
          metadata: aiResponse,
          processingStatus: 'completed'
        }, {
          where: { id }
        });
      } catch (aiError) {
        console.error('AI reprocessing failed:', aiError);
        await Papers.update({
          processingStatus: 'failed',
          processingError: aiError.message
        }, {
          where: { id }
        });
      }
    }
    
    // Fetch updated paper
    const updatedPaper = await Papers.findByPk(id, {
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });
    
    res.json({ success: true, paper: updatedPaper });
  } catch (error) {
    console.error('Error updating paper:', error);
    res.status(500).json({ success: false, message: 'Failed to update paper' });
  }
});

// DELETE paper
router.delete('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    
    const paper = await Papers.findByPk(id);
    if (!paper) {
      return res.status(404).json({ success: false, message: 'Paper not found' });
    }
    
    await Papers.destroy({ where: { id } });
    
    res.json({ success: true, message: 'Paper deleted successfully' });
  } catch (error) {
    console.error('Error deleting paper:', error);
    res.status(500).json({ success: false, message: 'Failed to delete paper' });
  }
});

// POST toggle paper status (pause/activate)
router.post('/:id/toggle-status', async (req, res) => {
  try {
    const { id } = req.params;
    
    const paper = await Papers.findByPk(id);
    if (!paper) {
      return res.status(404).json({ success: false, message: 'Paper not found' });
    }
    
    const newStatus = paper.status === 'active' ? 'paused' : 'active';
    
    await Papers.update({ status: newStatus }, { where: { id } });
    
    const updatedPaper = await Papers.findByPk(id, {
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });
    
    res.json({ success: true, paper: updatedPaper });
  } catch (error) {
    console.error('Error toggling paper status:', error);
    res.status(500).json({ success: false, message: 'Failed to toggle paper status' });
  }
});

// NEW: Sophisticated recommendation algorithm for papers
router.get('/recommendations/:paperId', validateToken, async (req, res) => {
  try {
    const { paperId } = req.params;
    const userId = req.user.id;
    const currentTime = new Date();
    
    // Step 1: Get the paper and validate it
    const paper = await Papers.findOne({
      where: { 
        id: paperId, 
        status: 'active',
        processingStatus: 'completed'
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'state']
      }]
    });
    
    if (!paper) {
      return res.status(404).json({ 
        success: false, 
        message: 'Paper not found or not available for recommendations' 
      });
    }
    
    // Step 2: Get user data (interests and location)
    const currentUser = await Users.findOne({
      where: { id: userId },
      attributes: ['id', 'intrest', 'state'],
      raw: true
    });
    
    if (!currentUser) {
      return res.status(404).json({ error: "User not found" });
    }
    
    const userInterests = currentUser.intrest || [];
    const userState = currentUser.state;
    
    // Step 3: Get posts user has already viewed to exclude them
    const viewedPostRecords = await PostView.findAll({
      where: { userId },
      attributes: ['postId']
    });
    const viewedPostIds = new Set(viewedPostRecords.map(view => view.postId));
    
    // Step 4: Get user's followed users for social signals
    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });
    const followingIds = following.map(follow => follow.followingId);
    
    // Step 5: Extract recommendation criteria from paper metadata
    const metadata = paper.metadata || {};
    const {
      tone,
      regions = [],
      summary,
      audience,
      language = 'english',
      focus_level,
      intent_type,
      primary_topics = [],
      content_filters = [],
      excluded_topics = [],
      secondary_topics = [],
      preferred_sources = []
    } = metadata;
    
    // Step 6: Build dynamic query conditions based on metadata
    let whereConditions = {
      isShort: false, // Focus on full posts for papers
      id: { [Op.notIn]: Array.from(viewedPostIds) } // Exclude viewed posts
    };
    
    // Step 7: Time-based prioritization (last 24 hours preference)
    const last24Hours = new Date(currentTime.getTime() - 24 * 60 * 60 * 1000);
    
    // Step 8: Fetch posts with sophisticated filtering
    let posts = await Post.findAll({
      where: whereConditions,
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'verified', 'state', 'followers', 'posts']
      }],
      limit: paper.postCount * 3, // Fetch more than needed for better scoring
      order: [['createdAt', 'DESC']]
    });
    
    // Step 9: Advanced scoring algorithm
    const calculatePostScore = (post) => {
      const plainPost = post.get({ plain: true });
      let totalScore = 0;
      let scoreBreakdown = {};
      
      // 1. Time Decay Score (25%) - Prioritize recent content, especially last 24h
      const ageInHours = (currentTime - new Date(plainPost.createdAt)) / (1000 * 60 * 60);
      let timeScore;
      if (ageInHours <= 24) {
        timeScore = 1.0; // Maximum score for last 24 hours
      } else {
        timeScore = Math.exp(-0.03 * ageInHours); // Slower decay than shorts
      }
      scoreBreakdown.timeScore = timeScore * 0.25;
      
      // 2. Description Context Matching (30%) - Most important factor
      let contextScore = 0;
      const postContent = (plainPost.content || plainPost.description || '').toLowerCase();
      const paperDescription = (paper.description || '').toLowerCase();
      
      // Extract key terms from paper description for context matching
      const paperKeywords = paperDescription.split(/\s+/).filter(word => word.length > 3);
      const matchingKeywords = paperKeywords.filter(keyword => 
        postContent.includes(keyword)
      ).length;
      
      contextScore = Math.min(matchingKeywords / Math.max(paperKeywords.length, 1), 1.0);
      
      // Boost for primary topics matching
      if (primary_topics && primary_topics.length > 0) {
        const topicMatches = primary_topics.filter(topic => 
          postContent.includes(topic.toLowerCase())
        ).length;
        contextScore += (topicMatches / primary_topics.length) * 0.3;
      }
      
      // Boost for secondary topics
      if (secondary_topics && secondary_topics.length > 0) {
        const secondaryMatches = secondary_topics.filter(topic => 
          postContent.includes(topic.toLowerCase())
        ).length;
        contextScore += (secondaryMatches / secondary_topics.length) * 0.1;
      }
      
      contextScore = Math.min(contextScore, 1.0);
      scoreBreakdown.contextScore = contextScore * 0.30;
      
      // 3. User Region/State Matching (15%)
      let regionScore = 0;
      if (userState && plainPost.author.state) {
        if (userState === plainPost.author.state) {
          regionScore = 1.0; // Same state
        } else if (regions.includes(userState) || regions.includes(plainPost.author.state)) {
          regionScore = 0.7; // State mentioned in metadata regions
        }
      }
      scoreBreakdown.regionScore = regionScore * 0.15;
      
      // 4. Metadata Quality Scoring (10%)
      let metadataScore = 0;
      
      // Language matching
      if (language === 'english') metadataScore += 0.3;
      
      // Audience matching - could be enhanced with user profile data
      if (audience && userInterests.length > 0) {
        const audienceMatch = userInterests.some(interest => 
          audience.toLowerCase().includes(interest.toLowerCase())
        );
        if (audienceMatch) metadataScore += 0.3;
      }
      
      // Intent type boost for news content
      if (intent_type === 'news' || intent_type === 'informational') {
        metadataScore += 0.2;
      }
      
      // Focus level consideration
      if (focus_level === 'high' || focus_level === 'medium') {
        metadataScore += 0.2;
      }
      
      scoreBreakdown.metadataScore = metadataScore * 0.10;
      
      // 5. Engagement Score (10%)
      const engagementScore = 
        (plainPost.views * 0.10) + 
        (plainPost.likes * 0.20) + 
        (plainPost.comments * 0.35) + 
        (plainPost.shared * 0.35);
      
      const normalizedEngagement = Math.log(engagementScore + 1) / 15;
      scoreBreakdown.engagementScore = normalizedEngagement * 0.10;
      
      // 6. Author Credibility (5%)
      const isVerified = plainPost.author.verified ? 1 : 0;
      const followersFactor = plainPost.author.followers / (plainPost.author.followers + 200);
      const postsFactor = plainPost.author.posts / (plainPost.author.posts + 100);
      
      const authorCredibility = 
        (isVerified * 0.5) + 
        (followersFactor * 0.3) + 
        (postsFactor * 0.2);
      
      scoreBreakdown.authorScore = authorCredibility * 0.05;
      
      // 7. Social Signals (3%)
      let socialScore = 0;
      if (followingIds.includes(plainPost.author.id)) {
        socialScore = 1.0; // User follows the author
      }
      scoreBreakdown.socialScore = socialScore * 0.03;
      
      // 8. Content Filters and Exclusions (2%)
      let filterScore = 1.0;
      
      // Check excluded topics
      if (excluded_topics && excluded_topics.length > 0) {
        const hasExcludedContent = excluded_topics.some(topic => 
          postContent.includes(topic.toLowerCase())
        );
        if (hasExcludedContent) filterScore = 0.1; // Heavy penalty
      }
      
      // Check content filters
      if (content_filters && content_filters.length > 0) {
        const passesFilters = content_filters.every(filter => {
          // Implement filter logic based on filter type
          return true; // Placeholder - would need specific filter implementation
        });
        if (!passesFilters) filterScore *= 0.5;
      }
      
      scoreBreakdown.filterScore = filterScore * 0.02;
      
      // Calculate total score
      totalScore = Object.values(scoreBreakdown).reduce((sum, score) => sum + score, 0);
      
      return {
        post: plainPost,
        score: totalScore,
        breakdown: scoreBreakdown
      };
    };
    
    // Step 10: Score and rank all posts
    const scoredPosts = posts.map(calculatePostScore);
    
    // Step 11: Sort by score and take top posts based on postCount
    const rankedPosts = scoredPosts
      .sort((a, b) => b.score - a.score)
      .slice(0, paper.postCount);
    
    // Step 12: Get interaction data for final posts
    const finalPostIds = rankedPosts.map(item => item.post.id);
    
    const [likeRecords, saveRecords] = await Promise.all([
      PostLike.findAll({
        where: { userId, postId: { [Op.in]: finalPostIds } },
        attributes: ['postId']
      }),
      PostSaved.findAll({
        where: { userId, postId: { [Op.in]: finalPostIds } },
        attributes: ['postId']
      })
    ]);
    
    const likedPostIds = new Set(likeRecords.map(like => like.postId));
    const savedPostIds = new Set(saveRecords.map(save => save.postId));
    
    // Step 13: Format final response
    const recommendations = rankedPosts.map(item => ({
      id: item.post.id,
      title: item.post.title,
      content: item.post.content,
      description: item.post.description,
      thumbnail: item.post.thumbnail,
      media: item.post.media || [],
      views: item.post.views,
      likes: item.post.likes,
      comments: item.post.comments,
      shares: item.post.shared,
      bookmarks: item.post.bookmarks,
      createdAt: item.post.createdAt,
      updatedAt: item.post.updatedAt,
      category: item.post.category || item.post.categories,
      isShort: item.post.isShort,
      score: item.score,
      scoreBreakdown: item.breakdown,
      author: {
        id: item.post.author.id,
        username: item.post.author.username,
        profilePicture: item.post.author.profilePicture,
        fullName: (item.post.author.firstName || '') + ' ' + (item.post.author.lastName || ''),
        verified: item.post.author.verified,
        state: item.post.author.state
      },
      userInteraction: {
        liked: likedPostIds.has(item.post.id),
        saved: savedPostIds.has(item.post.id),
        viewed: false
      }    }));
    
    res.json({
      success: true,
      paper: {
        id: paper.id,
        title: paper.title,
        description: paper.description,
        postCount: paper.postCount,
        deliveryTime: paper.deliveryTime,
        metadata: paper.metadata,
        author: {
          id: paper.author.id,
          username: paper.author.username,
          state: paper.author.state
        }
      },
      recommendations,
      totalFound: recommendations.length,
      algorithm: {
        version: '1.0',
        weightings: {
          timeDecay: '25%',
          contextMatching: '30%',
          regionMatching: '15%',
          metadataQuality: '10%',
          engagement: '10%',
          authorCredibility: '5%',
          socialSignals: '3%',
          contentFilters: '2%'
        },
        processingTime: new Date() - currentTime
      }
    });
    
  } catch (error) {
    console.error('Error generating paper recommendations:', error);
    res.status(500).json({ 
      success: false, 
      message: 'Failed to generate recommendations',
      error: error.message 
    });
  }
});

// NEW: Quick recommendations without detailed scoring (for faster responses)
router.get('/quick-recommendations/:paperId', validateToken, async (req, res) => {
  try {
    const { paperId } = req.params;
    const userId = req.user.id;
    const { limit = 10 } = req.query;
    
    // Get paper and user data
    const [paper, currentUser] = await Promise.all([
      Papers.findOne({
        where: { 
          id: paperId, 
          status: 'active',
          processingStatus: 'completed'
        }
      }),
      Users.findOne({
        where: { id: userId },
        attributes: ['id', 'state'],
        raw: true
      })
    ]);
    
    if (!paper || !currentUser) {
      return res.status(404).json({ 
        success: false, 
        message: 'Paper or user not found' 
      });
    }
    
    // Get viewed posts to exclude
    const viewedPostIds = await PostView.findAll({
      where: { userId },
      attributes: ['postId']
    }).then(views => new Set(views.map(v => v.postId)));
    
    // Simple query for recent, unviewed posts
    const posts = await Post.findAll({
      where: {
        isShort: false,
        id: { [Op.notIn]: Array.from(viewedPostIds) },
        createdAt: { [Op.gte]: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000) } // Last 7 days
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'verified', 'state']
      }],
      limit: parseInt(limit),
      order: [['createdAt', 'DESC']]
    });
    
    // Format response
    const recommendations = posts.map(post => {
      const plainPost = post.get({ plain: true });
      return {
        id: plainPost.id,
        title: plainPost.title,
        content: plainPost.content,
        description: plainPost.description,
        thumbnail: plainPost.thumbnail,
        media: plainPost.media || [],
        views: plainPost.views,
        likes: plainPost.likes,
        comments: plainPost.comments,
        createdAt: plainPost.createdAt,
        author: {
          id: plainPost.author.id,
          username: plainPost.author.username,
          profilePicture: plainPost.author.profilePicture,
          verified: plainPost.author.verified
        }
      };
    });
    
    res.json({
      success: true,
      recommendations,
      totalFound: recommendations.length,
      algorithm: 'quick'
    });
    
  } catch (error) {
    console.error('Error generating quick recommendations:', error);
    res.status(500).json({ 
      success: false, 
      message: 'Failed to generate quick recommendations' 
    });
  }
});

// NEW: Get paper analytics and delivery stats
router.get('/analytics/:paperId', validateToken, async (req, res) => {
  try {
    const { paperId } = req.params;
    const userId = req.user.id;
    
    const paper = await Papers.findOne({
      where: { id: paperId, authorId: userId },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username']
      }]
    });
    
    if (!paper) {
      return res.status(404).json({ 
        success: false, 
        message: 'Paper not found or access denied' 
      });
    }
    
    // Calculate analytics
    const now = new Date();
    const analytics = {
      id: paper.id,
      title: paper.title,
      status: paper.status,      processingStatus: paper.processingStatus,
      postCount: paper.postCount,
      deliveryTime: paper.deliveryTime,
      createdAt: paper.createdAt,
      daysSinceCreation: Math.floor((now - paper.createdAt) / (1000 * 60 * 60 * 24)),
      metadata: paper.metadata,
      hasMetadata: !!paper.metadata,
      metadataTopics: paper.metadata?.primary_topics || [],
      metadataRegions: paper.metadata?.regions || []
    };
    
    res.json({ success: true, analytics });
    
  } catch (error) {
    console.error('Error fetching paper analytics:', error);
    res.status(500).json({ 
      success: false, 
      message: 'Failed to fetch analytics' 
    });
  }
});

// NEW: Test metadata processing for a paper description
router.post('/test-metadata', validateToken, async (req, res) => {
  try {
    const { description } = req.body;
    
    if (!description) {
      return res.status(400).json({ 
        success: false, 
        message: 'Description is required' 
      });
    }
    
    // Process with Google GenAI
    const aiResponse = await GoogleApi.processDescription(description);
    
    res.json({
      success: true,
      metadata: aiResponse,
      description: description,
      processingTime: new Date()
    });
    
  } catch (error) {
    console.error('Error testing metadata processing:', error);
    res.status(500).json({ 
      success: false, 
      message: 'Failed to process metadata',
      error: error.message 
    });  }
});

// MyPaper API Routes

// GET today's paper for a user
router.get('/my-paper/today', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const moment = require('moment-timezone');
    const todayDate = moment().tz('Asia/Kolkata').format('YYYY-MM-DD');
    
    console.log(`📅 [TODAY DEBUG] Fetching papers for date: ${todayDate}, user: ${userId}`);
    
    // Get user's papers first
    const userPapers = await Papers.findAll({
      where: { 
        authorId: userId,
        status: 'active'
      },
      attributes: ['id']
    });
    
    if (userPapers.length === 0) {
      console.log(`❌ [TODAY DEBUG] No active papers found for user: ${userId}`);
      return res.json({ 
        success: false,
        message: 'No active papers found',
        paper: null, 
        posts: [] 
      });
    }
    
    const paperIds = userPapers.map(p => p.id);
    console.log(`📋 [TODAY DEBUG] User paper IDs: ${paperIds.join(', ')}`);
    
    // Find today's paper post for any of user's papers
    const paperPost = await PaperPosts.findOne({
      where: {
        paperId: { [Op.in]: paperIds },
        paperDate: todayDate
      },
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'authorId']
      }],
      order: [['createdAt', 'DESC']] // Get the most recent if multiple
    });
    
    console.log(`🔍 [TODAY DEBUG] Found paper post:`, paperPost ? {
      id: paperPost.id,
      paperId: paperPost.paperId,
      paperDate: paperPost.paperDate,
      deliveryTime: paperPost.deliveryTime,
      read: paperPost.read
    } : 'None');
    
    if (!paperPost) {
      return res.json({ 
        success: false,
        message: `No paper found for today (${todayDate})`,
        paper: null, 
        posts: [] 
      });
    }

    const postsWithDetails = await PaperPosts.getPaperPostsWithDetails(paperPost.id);

    res.json({
      success: true,
      paper: {
        ...paperPost.toJSON(),
        isRead: paperPost.read || false,
        userReadStatus: paperPost.read || false
      },
      posts: postsWithDetails || []
    });
  } catch (error) {
    console.error('❌ [TODAY ERROR] Error fetching today\'s paper:', error);
    res.status(500).json({ 
      success: false,
      message: 'Failed to fetch today\'s paper',
      error: error.message 
    });
  }
});

// GET yesterday's paper for a user
router.get('/my-paper/yesterday', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const moment = require('moment-timezone');
    const yesterdayDate = moment().tz('Asia/Kolkata').subtract(1, 'day').format('YYYY-MM-DD');
    
    console.log(`📅 [YESTERDAY DEBUG] Fetching papers for date: ${yesterdayDate}, user: ${userId}`);
    
    // Get user's papers first
    const userPapers = await Papers.findAll({
      where: { 
        authorId: userId,
        status: 'active'
      },
      attributes: ['id']
    });
    
    if (userPapers.length === 0) {
      console.log(`❌ [YESTERDAY DEBUG] No active papers found for user: ${userId}`);
      return res.json({ 
        success: false,
        message: 'No active papers found',
        paper: null, 
        posts: [] 
      });
    }
    
    const paperIds = userPapers.map(p => p.id);
    console.log(`📋 [YESTERDAY DEBUG] User paper IDs: ${paperIds.join(', ')}`);

    const paperPost = await PaperPosts.findOne({
      where: { 
        paperId: { [Op.in]: paperIds },
        paperDate: yesterdayDate 
      },
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'authorId']
      }],
      order: [['createdAt', 'DESC']] // Get the most recent if multiple
    });
    
    console.log(`🔍 [YESTERDAY DEBUG] Found paper post:`, paperPost ? {
      id: paperPost.id,
      paperId: paperPost.paperId,
      paperDate: paperPost.paperDate,
      deliveryTime: paperPost.deliveryTime,
      read: paperPost.read
    } : 'None');

    if (!paperPost) {
      return res.json({ 
        success: false,
        message: `No paper found for yesterday (${yesterdayDate})`,
        paper: null, 
        posts: [] 
      });
    }

    const postsWithDetails = await PaperPosts.getPaperPostsWithDetails(paperPost.id);

    res.json({
      success: true,
      paper: {
        ...paperPost.toJSON(),
        isRead: paperPost.read || false,
        userReadStatus: paperPost.read || false
      },
      posts: postsWithDetails || []
    });
  } catch (error) {
    console.error('❌ [YESTERDAY ERROR] Error fetching yesterday\'s paper:', error);
    res.status(500).json({ 
      success: false,
      message: 'Failed to fetch yesterday\'s paper',
      error: error.message 
    });
  }
});

// GET paper for a specific date
router.get('/my-paper/date/:date', authenticateToken, async (req, res) => {
  try {
    const { date } = req.params;
    const userId = req.user.id;
    
    // Validate date format (YYYY-MM-DD)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      return res.status(400).json({ 
        success: false,
        message: 'Invalid date format. Use YYYY-MM-DD' 
      });
    }
    
    console.log(`📅 [DATE DEBUG] Fetching papers for date: ${date}, user: ${userId}`);
    
    // Get user's papers first
    const userPapers = await Papers.findAll({
      where: { 
        authorId: userId,
        status: 'active'
      },
      attributes: ['id']
    });
    
    if (userPapers.length === 0) {
      console.log(`❌ [DATE DEBUG] No active papers found for user: ${userId}`);
      return res.json({ 
        success: false,
        message: 'No active papers found',
        paper: null, 
        posts: [] 
      });
    }
    
    const paperIds = userPapers.map(p => p.id);
    console.log(`📋 [DATE DEBUG] User paper IDs: ${paperIds.join(', ')}`);

    const paperPost = await PaperPosts.findOne({
      where: { 
        paperId: { [Op.in]: paperIds },
        paperDate: date 
      },
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'authorId']
      }],
      order: [['createdAt', 'DESC']] // Get the most recent if multiple
    });
    
    console.log(`🔍 [DATE DEBUG] Found paper post:`, paperPost ? {
      id: paperPost.id,
      paperId: paperPost.paperId,
      paperDate: paperPost.paperDate,
      deliveryTime: paperPost.deliveryTime,
      read: paperPost.read
    } : 'None');

    if (!paperPost) {
      return res.json({ 
        success: false,
        message: `No paper found for date (${date})`,
        paper: null, 
        posts: [] 
      });
    }

    const postsWithDetails = await PaperPosts.getPaperPostsWithDetails(paperPost.id);

    res.json({
      success: true,
      paper: {
        ...paperPost.toJSON(),
        isRead: paperPost.read || false,
        userReadStatus: paperPost.read || false
      },
      posts: postsWithDetails || []
    });
  } catch (error) {
    console.error('❌ [DATE ERROR] Error fetching paper for date:', error);
    res.status(500).json({ 
      success: false,
      message: 'Failed to fetch paper for specified date',
      error: error.message 
    });
  }
});

// GET all available paper dates (for date picker)
router.get('/my-paper/dates', authenticateToken, async (req, res) => {
  try {
    const { limit = 30 } = req.query;
    
    const dates = await PaperPosts.findAll({
      attributes: ['paperDate'],
      order: [['paperDate', 'DESC']],
      limit: parseInt(limit),
      raw: true
    });

    res.json({ dates: dates.map(d => d.paperDate) });
  } catch (error) {
    console.error('Error fetching paper dates:', error);
    res.status(500).json({ message: 'Failed to fetch paper dates' });
  }
});

// POST update paper read status
router.post('/update-read-status/:paperId', authenticateToken, async (req, res) => {
  try {
    const { paperId } = req.params;
    const { isRead } = req.body;
    const userId = req.user.id;

    console.log('🔄 [READ STATUS] Received request:', {
      paperId,
      isRead,
      userId,
      body: req.body,
      params: req.params
    });

    // Validate paperId
    const paperPost = await PaperPosts.findByPk(paperId);
    if (!paperPost) {
      console.log('❌ [READ STATUS] Paper not found:', paperId);
      return res.status(404).json({ 
        success: false, 
        message: 'Paper not found' 
      });
    }

    console.log('📄 [READ STATUS] Found paper:', {
      id: paperPost.id,
      currentReadStatus: paperPost.read,
      paperId: paperPost.paperId,
      paperDate: paperPost.paperDate
    });

    // Update read status using the model methods
    if (isRead) {
      const result = await PaperPosts.markAsRead(paperId, userId);
      console.log('✅ [READ STATUS] markAsRead result:', result);
    } else {
      const result = await PaperPosts.markAsUnread(paperId, userId);
      console.log('✅ [READ STATUS] markAsUnread result:', result);
    }

    // Fetch the updated paper to verify the change
    const updatedPaper = await PaperPosts.findByPk(paperId);
    console.log('📊 [READ STATUS] Updated paper status:', {
      id: updatedPaper.id,
      newReadStatus: updatedPaper.read,
      wasUpdated: updatedPaper.read === isRead
    });
    
    res.json({ 
      success: true, 
      message: `Paper marked as ${isRead ? 'read' : 'unread'}`,
      isRead: isRead,
      actualReadStatus: updatedPaper.read
    });
  } catch (error) {
    console.error('❌ [READ STATUS] Error updating paper read status:', error);
    res.status(500).json({ 
      success: false,
      message: 'Failed to update paper read status',
      error: error.message
    });
  }
});

// POST mark paper as read (legacy endpoint - kept for compatibility)
router.post('/my-paper/:paperId/mark-read', authenticateToken, async (req, res) => {
  try {
    const { paperId } = req.params;
    const userId = req.user.id;

    const paperPost = await PaperPosts.findByPk(paperId);
    if (!paperPost) {
      return res.status(404).json({ message: 'Paper not found' });
    }    await PaperPosts.markAsRead(paperId, userId);
    
    res.json({ 
      success: true, 
      message: 'Paper marked as read',
      isRead: true
    });
  } catch (error) {
    console.error('Error marking paper as read:', error);
    res.status(500).json({ message: 'Failed to mark paper as read' });
  }
});

// POST mark paper as unread
router.post('/my-paper/:paperId/mark-unread', authenticateToken, async (req, res) => {
  try {
    const { paperId } = req.params;
    const userId = req.user.id;

    const paperPost = await PaperPosts.findByPk(paperId);
    if (!paperPost) {
      return res.status(404).json({ message: 'Paper not found' });
    }    await PaperPosts.markAsUnread(paperId, userId);
      res.json({ 
      success: true, 
      message: 'Paper marked as unread',
      isRead: false // This endpoint marks as unread, so false is correct
    });
  } catch (error) {
    console.error('Error marking paper as unread:', error);
    res.status(500).json({ message: 'Failed to mark paper as unread' });
  }
});

// GET papers with filtering and sorting (unread first, then read, time as secondary)
router.get('/my-paper/filtered', authenticateToken, async (req, res) => {
  try {
    const { 
      filter = 'today', // 'today', 'yesterday', 'date'
      date,
      page = 1,
      limit = 10 
    } = req.query;
    
    const userId = req.user.id;
    const offset = (page - 1) * limit;
    
    // Use IST timezone for consistent date handling
    const todayDate = moment().tz('Asia/Kolkata').format('YYYY-MM-DD');
    const yesterdayDate = moment().tz('Asia/Kolkata').subtract(1, 'day').format('YYYY-MM-DD');
    
    console.log(`🔍 [FILTERED] Filter: ${filter}, user: ${userId}, today: ${todayDate}, yesterday: ${yesterdayDate}`);
    
    // Get user's papers first
    const userPapers = await Papers.findAll({
      where: { 
        authorId: userId,
        status: 'active'
      },
      attributes: ['id']
    });
    
    if (userPapers.length === 0) {
      return res.json({
        papers: [],
        totalCount: 0,
        currentPage: parseInt(page),
        totalPages: 0,
        message: 'No active papers found'
      });
    }
    
    const paperIds = userPapers.map(p => p.id);
    
    let whereClause = {
      paperId: { [Op.in]: paperIds }
    };
    
    if (filter === 'today') {
      whereClause.paperDate = todayDate;
    } else if (filter === 'yesterday') {
      whereClause.paperDate = yesterdayDate;
    } else if (filter === 'date' && date) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        return res.status(400).json({ message: 'Invalid date format. Use YYYY-MM-DD' });
      }
      whereClause.paperDate = date;
    }

    const papers = await PaperPosts.findAndCountAll({
      where: whereClause,
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'authorId']
      }],
      order: [['paperDate', 'DESC'], ['createdAt', 'DESC']],
      limit: parseInt(limit),
      offset: parseInt(offset)
    });

    // Get papers with posts and read status
    const papersWithDetails = await Promise.all(
      papers.rows.map(async (paper) => {
        const postsWithDetails = await PaperPosts.getPaperPostsWithDetails(paper.id);
        return {
          paper: {
            ...paper.toJSON(),
            isRead: paper.read || false
          },
          posts: postsWithDetails || []
        };
      })
    );

    // Sort by read status (unread first) and then by time
    papersWithDetails.sort((a, b) => {
      // Unread first
      if (a.paper.isRead !== b.paper.isRead) {
        return a.paper.isRead ? 1 : -1;
      }
      // Then by date (newest first)
      return new Date(b.paper.createdAt) - new Date(a.paper.createdAt);
    });

    res.json({
      papers: papersWithDetails,
      totalCount: papers.count,
      currentPage: parseInt(page),
      totalPages: Math.ceil(papers.count / limit)
    });
    
  } catch (error) {
    console.error('❌ [FILTERED] Error fetching filtered papers:', error);
    res.status(500).json({ 
      success: false,
      message: 'Failed to fetch filtered papers',
      error: error.message 
    });
  }
});

// NEW: Simple route to fetch posts directly from PaperPosts table
router.get('/simple-posts/:paperPostId', authenticateToken, async (req, res) => {
  try {
    const { paperPostId } = req.params;
    const userId = req.user.id;
    
    // Fetch the PaperPost record with Paper details
    const paperPost = await PaperPosts.findByPk(paperPostId, {
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'authorId']
      }]
    });
    
    if (!paperPost) {
      return res.status(404).json({
        success: false,
        message: 'Paper not found'
      });
    }
    
    // Get posts directly using the posts column with user interaction data
    const postsWithDetails = await PaperPosts.getPaperPostsWithDetails(paperPostId);    if (!postsWithDetails || postsWithDetails.length === 0) {
      console.log(`🔍 [EMPTY PAPER DEBUG] Processing empty paper:`, {
        paperPostId,  
        userId,
        currentReadStatus: paperPost.read,
        hasNoPosts: true
      });

      // Mark paper as read even if no posts are found
      try {
        const markResult = await PaperPosts.markAsRead(paperPostId, userId);
        console.log(`📖 [EMPTY PAPER READ] Mark as read result:`, markResult);
        
        // Verify the update
        const verifyPaper = await PaperPosts.findByPk(paperPostId);
        console.log(`✅ [EMPTY PAPER VERIFY] Post-update status:`, {
          paperPostId,
          oldReadStatus: paperPost.read,
          newReadStatus: verifyPaper.read,
          updateSuccessful: verifyPaper.read === true
        });
        
      } catch (error) {
        console.error('❌ [EMPTY PAPER ERROR] Error auto-marking empty paper as read:', {
          paperPostId,
          userId,
          error: error.message,
          stack: error.stack
        });
      }

      return res.json({
        success: true,
        paper: {
          id: paperPost.id,
          paperId: paperPost.paperId,
          paperDate: paperPost.paperDate,
          deliveryTime: paperPost.deliveryTime,
          status: paperPost.status,
          title: paperPost.paper?.title,
          description: paperPost.paper?.description,
          isRead: true // Marked as read
        },
        posts: []
      });
    }
    
    // Get user interaction data for the posts
    const postIds = postsWithDetails.map(post => post.id);
    
    const [likeRecords, saveRecords] = await Promise.all([
      PostLike.findAll({
        where: { userId, postId: { [Op.in]: postIds } },
        attributes: ['postId']
      }),
      PostSaved.findAll({
        where: { userId, postId: { [Op.in]: postIds } },
        attributes: ['postId']
      })
    ]);
    
    const likedPostIds = new Set(likeRecords.map(like => like.postId));
    const savedPostIds = new Set(saveRecords.map(save => save.postId));
      // Add user interaction data to posts
    const postsWithInteractions = postsWithDetails.map(post => ({
      ...post,
      userInteraction: {
        liked: likedPostIds.has(post.id),
        saved: savedPostIds.has(post.id),
        viewed: false
      }
    }));    // Automatically mark paper as read when user opens it
    console.log(`🔍 [PAPER READ DEBUG] Starting auto-mark as read process:`, {
      paperPostId,
      userId,
      currentReadStatus: paperPost.read,
      paperDate: paperPost.paperDate,
      paperId: paperPost.paperId
    });

    try {
      const markResult = await PaperPosts.markAsRead(paperPostId, userId);
      console.log(`📖 [PAPER READ] Mark as read result:`, markResult);
      
      // Verify the update by re-fetching the paper
      const verifyPaper = await PaperPosts.findByPk(paperPostId);
      console.log(`✅ [PAPER READ VERIFY] Post-update status:`, {
        paperPostId,
        oldReadStatus: paperPost.read,
        newReadStatus: verifyPaper.read === true,
        updatedAt: verifyPaper.updatedAt
      });
      
    } catch (error) {
      console.error('❌ [PAPER READ ERROR] Error auto-marking paper as read:', {
        paperPostId,
        userId,
        error: error.message,
        stack: error.stack
      });
      // Don't fail the request if marking as read fails
    }
      
    res.json({
      success: true,
      paper: {
        id: paperPost.id,
        paperId: paperPost.paperId,
        paperDate: paperPost.paperDate,
        deliveryTime: paperPost.deliveryTime,
        status: paperPost.status,
        title: paperPost.paper?.title,
        description: paperPost.paper?.description,
        isRead: true // Now marked as read
      },
      posts: postsWithInteractions,
      totalFound: postsWithInteractions.length
    });
    
  } catch (error) {
    console.error('Error fetching simple posts:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch posts',
      error: error.message
    });
  }
});

// NEW: Debug endpoint to inspect PaperPosts table structure and data
router.get('/debug/paper-posts', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    
    console.log(`🔍 [DEBUG] Inspecting PaperPosts table for user ${userId}`);
    
    // Get all PaperPosts records
    const allPaperPosts = await PaperPosts.findAll({
      limit: 10,
      order: [['createdAt', 'DESC']],
      include: [{
        model: Papers,
        as: 'paper',
        attributes: ['id', 'title', 'description', 'authorId']
      }]
    });
    
    console.log(`📊 [DEBUG] Found ${allPaperPosts.length} PaperPosts records`);
    
    // Get database table info
    const tableInfo = await PaperPosts.describe();
    
    res.json({
      success: true,
      debug: {
        userId,
        tableStructure: tableInfo,
        totalRecords: allPaperPosts.length,
        sampleRecords: allPaperPosts.map(pp => ({
          id: pp.id,
          paperId: pp.paperId,
          paperDate: pp.paperDate,
          deliveryTime: pp.deliveryTime,
          read: pp.read,
          status: pp.status,
          createdAt: pp.createdAt,
          updatedAt: pp.updatedAt,
          paperTitle: pp.paper?.title,
          paperAuthorId: pp.paper?.authorId
        }))
      }
    });
    
  } catch (error) {
    console.error('❌ [DEBUG] Error inspecting PaperPosts:', error);
    res.status(500).json({
      success: false,
      message: 'Debug inspection failed',
      error: error.message
    });
  }
});

// NEW: Debug endpoint to check current date handling and user papers
router.get('/debug/date-check', authenticateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    const currentUTC = new Date();
    const currentIST = moment().tz('Asia/Kolkata');
    const todayIST = currentIST.format('YYYY-MM-DD');
    const yesterdayIST = moment().tz('Asia/Kolkata').subtract(1, 'day').format('YYYY-MM-DD');
    
    console.log(`🔍 [DATE CHECK] Debug for user: ${userId}`);
    
    // Get user's papers
    const userPapers = await Papers.findAll({
      where: { 
        authorId: userId,
        status: 'active'
      },
      attributes: ['id', 'title', 'deliveryTime', 'createdAt']
    });
    
    // Get all paper posts for this user
    const paperIds = userPapers.map(p => p.id);
    const paperPosts = await PaperPosts.findAll({
      where: {
        paperId: { [Op.in]: paperIds }
      },
      order: [['paperDate', 'DESC'], ['createdAt', 'DESC']],
      limit: 20
    });
    
    // Group papers by date
    const papersByDate = {};
    paperPosts.forEach(pp => {
      const date = pp.paperDate;
      if (!papersByDate[date]) {
        papersByDate[date] = [];
      }
      papersByDate[date].push({
        id: pp.id,
        paperId: pp.paperId,
        deliveryTime: pp.deliveryTime,
        read: pp.read,
        status: pp.status,
        createdAt: pp.createdAt,
        postsCount: pp.posts ? pp.posts.length : 0
      });
    });
    
    res.json({
      success: true,
      debug: {
        userId,
        timezone: 'Asia/Kolkata',
        currentUTC: currentUTC.toISOString(),
        currentIST: currentIST.format(),
        todayIST,
        yesterdayIST,
        userPapersCount: userPapers.length,
        userPapers: userPapers.map(p => ({
          id: p.id,
          title: p.title,
          deliveryTime: p.deliveryTime,
          createdAt: p.createdAt
        })),
        totalPaperPosts: paperPosts.length,
        papersByDate,
        availableDates: Object.keys(papersByDate).sort().reverse()
      }
    });
    
  } catch (error) {
    console.error('❌ [DATE CHECK] Error:', error);
    res.status(500).json({
      success: false,
      message: 'Debug check failed',
      error: error.message
    });
  }
});

// Scheduler-related endpoints

// GET scheduler status
router.get('/scheduler/status', authenticateToken, async (req, res) => {
  try {
    const status = paperScheduler.getStatus();
    res.json({
      success: true,
      scheduler: status,
      message: 'Scheduler status retrieved successfully'
    });
  } catch (error) {
    console.error('Error getting scheduler status:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to get scheduler status',
      error: error.message
    });
  }
});

// POST trigger manual paper generation (for testing)
router.post('/scheduler/trigger', authenticateToken, async (req, res) => {
  try {
    console.log(`🔧 [MANUAL TRIGGER] User ${req.user.id} triggered manual paper generation`);
    
    // Run the paper generation in background
    paperScheduler.triggerManualGeneration().catch(error => {
      console.error('❌ [MANUAL TRIGGER] Error in background generation:', error);
    });
    
    res.json({
      success: true,
      message: 'Manual paper generation triggered successfully. Check server logs for progress.'
    });
  } catch (error) {
    console.error('❌ [MANUAL TRIGGER] Error triggering manual generation:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to trigger manual generation',
      error: error.message
    });
  }
});

// GET next scheduled run time
router.get('/scheduler/next-run', authenticateToken, async (req, res) => {
  try {
    const moment = require('moment-timezone');
    const now = moment().tz('Asia/Kolkata');
    const nextRun = now.clone().add(1, 'hour').minute(55).second(0);
    
    // If we're past 55 minutes, the next run is in the next hour
    if (now.minute() >= 55) {
      nextRun.add(1, 'hour');
    }
    
    res.json({
      success: true,
      nextRun: {
        datetime: nextRun.format('YYYY-MM-DD HH:mm:ss'),
        fromNow: nextRun.fromNow(),
        minutesUntil: Math.ceil(nextRun.diff(now, 'minutes', true))
      },
      current: {
        datetime: now.format('YYYY-MM-DD HH:mm:ss'),
        timezone: 'Asia/Kolkata'
      }
    });
  } catch (error) {
    console.error('Error calculating next run time:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to calculate next run time',
      error: error.message
    });
  }
});

module.exports = router;
