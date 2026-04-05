const express = require('express');
const router = express.Router();
const { Communities, Users, CommunityMemberships, CommunityPosts, Post, PostLike, PostSaved } = require('../models');
const { Op } = require('sequelize');
const { validateToken } = require('../middlewares/AuthMiddleware');
const multer = require('multer');
const { uploadToB2, deleteFromB2, generateUniqueFilename } = require('../utils/backblaze');

// Set up multer for file uploads
const storage = multer.memoryStorage();
const upload = multer({ 
  storage,
  limits: { fileSize: 10 * 1024 * 1024 }, // 10MB limit
  fileFilter: (req, file, cb) => {
    if (file.mimetype.startsWith('image/')) {
      cb(null, true);
    } else {
      cb(new Error('Only image files are allowed'), false);
    }  }
});

// Get user's communities where they can post
router.get('/user-communities', validateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    console.log('[DEBUG] /user-communities called for userId:', userId);
    
    // Get user's community memberships with community details
    const memberships = await CommunityMemberships.findAll({
      where: {
        user_id: userId,
        status: 'active'
      },      include: [{
        model: Communities,
        as: 'community',
        attributes: ['id', 'name', 'description', 'profile_icon', 'member_count', 'creator_id', 'post_access_users', 'post_access_type'],
        include: [{
          model: Users,
          as: 'creator',
          attributes: ['id', 'username']
        }]
      }],
      attributes: ['id', 'role', 'user_id', 'community_id', 'joined_at']
    });

    console.log('[DEBUG] Found memberships:', memberships.length);
    console.log('[DEBUG] Raw memberships:', JSON.stringify(memberships, null, 2));    // Format the response
    const communities = memberships.map(membership => ({
      id: membership.community.id,
      name: membership.community.name,
      description: membership.community.description,
      profile_icon: membership.community.profile_icon,
      member_count: membership.community.member_count,      creator_id: membership.community.creator_id,
      post_access_users: membership.community.post_access_users || [],
      post_access_type: membership.community.post_access_type,
      membership: {
        id: membership.id,
        role: membership.role,
        user_id: membership.user_id,
        joined_at: membership.joined_at
      }
    }));

    console.log('[DEBUG] Formatted communities:', JSON.stringify(communities, null, 2));

    res.json({
      success: true,
      communities
    });

  } catch (error) {
    console.error('Error fetching user communities:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch user communities',
      error: error.message
    });
  }
});

// Create a new community
router.post('/', validateToken, async (req, res) => {
  try {
    const { 
      name, 
      description, 
      hot_topics = [], 
      banner_url, 
      profile_icon, 
      post_access_type = 'everyone',
      post_access_users = []
    } = req.body;
    
    if (!name) {
      return res.status(400).json({ error: 'Community name is required' });
    }

    // Validate post_access_type
    const validPostAccessTypes = ['everyone', 'creator', 'moderators'];
    if (post_access_type && !validPostAccessTypes.includes(post_access_type)) {
      return res.status(400).json({ error: 'Invalid post_access_type. Must be everyone, creator, or moderators' });
    }

    // Check if community name already exists
    const existingCommunity = await Communities.findOne({ where: { name } });
    if (existingCommunity) {
      return res.status(400).json({ error: 'Community name already exists' });
    }

    // Determine post access users based on type
    let finalPostAccessUsers = [];
    let memberRole = 'member';

    if (post_access_type === 'everyone') {
      finalPostAccessUsers = [];
      memberRole = 'member';
    } else if (post_access_type === 'creator') {
      finalPostAccessUsers = [];
      memberRole = 'admin'; // Creator gets admin role
    } else if (post_access_type === 'moderators') {
      // Parse and validate moderator IDs
      const moderatorIds = Array.isArray(post_access_users) 
        ? post_access_users.map(user => typeof user === 'object' ? user.id : user)
        : [];
      finalPostAccessUsers = moderatorIds;
      memberRole = 'admin'; // Creator gets admin role
    }

    const community = await Communities.create({
      name,
      description,
      visibility: 'public', // Default to public since we removed visibility selection
      hot_topics,
      banner_url,
      profile_icon,
      post_access_type,
      post_access_users: finalPostAccessUsers,
      creator_id: req.user.id,
      member_count: 1 // Creator is automatically a member
    });

    // Add creator as member with appropriate role
    await CommunityMemberships.create({
      community_id: community.id,
      user_id: req.user.id,
      role: 'admin', // Creator is always admin
      status: 'active'
    });

    // If post_access_type is moderators, add moderators to membership
    if (post_access_type === 'moderators' && finalPostAccessUsers.length > 0) {
      const moderatorMemberships = finalPostAccessUsers.map(userId => ({
        community_id: community.id,
        user_id: userId,
        role: 'moderator',
        status: 'active'
      }));

      await CommunityMemberships.bulkCreate(moderatorMemberships, {
        ignoreDuplicates: true // Avoid duplicate entries
      });

      // Update member count
      await community.update({
        member_count: 1 + finalPostAccessUsers.length
      });
    }

    // Fetch the complete community with creator info
    const fullCommunity = await Communities.findByPk(community.id, {
      include: [
        {
          model: Users,
          as: 'creator',
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        }
      ]
    });

    res.status(201).json(fullCommunity);
  } catch (error) {
    console.error('Error creating community:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Get all communities (with pagination and filtering)
router.get('/', async (req, res) => {
  try {
    const { 
      page = 1, 
      limit = 20, 
      search, 
      visibility = 'public',
      sort = 'member_count' 
    } = req.query;
    
    const offset = (page - 1) * limit;
    const whereClause = {};    // Add search filter
    if (search) {
      whereClause[Op.or] = [
        { name: { [Op.like]: `%${search}%` } },
        { description: { [Op.like]: `%${search}%` } }
      ];
    }

    // Add visibility filter
    if (visibility !== 'all') {
      whereClause.visibility = visibility;
    }

    // Sort options
    let orderClause;
    switch (sort) {
      case 'newest':
        orderClause = [['createdAt', 'DESC']];
        break;
      case 'oldest':
        orderClause = [['createdAt', 'ASC']];
        break;
      case 'name':
        orderClause = [['name', 'ASC']];
        break;
      default:
        orderClause = [['member_count', 'DESC']];
    }

    const { count, rows: communities } = await Communities.findAndCountAll({
      where: whereClause,
      include: [
        {
          model: Users,
          as: 'creator',
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        }
      ],
      order: orderClause,
      limit: parseInt(limit),
      offset: parseInt(offset)
    });

    res.json({
      communities,
      pagination: {
        total: count,
        page: parseInt(page),
        limit: parseInt(limit),
        totalPages: Math.ceil(count / limit)
      }
    });
  } catch (error) {
    console.error('Error fetching communities:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Get a specific community by ID
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user?.id; // Get user ID if authenticated

    const community = await Communities.findByPk(id, {
      include: [
        {
          model: Users,
          as: 'creator',
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        }
      ]
    });

    if (!community) {
      return res.status(404).json({ error: 'Community not found' });
    }    // Get post access users (contributors)
    let postAccessUsers = [];
    if (community.post_access_users && Array.isArray(community.post_access_users) && community.post_access_users.length > 0) {
      // Ensure we have valid user IDs (strings, not objects)
      const validUserIds = community.post_access_users.filter(userId => 
        typeof userId === 'string' && userId.length > 0
      );
      
      if (validUserIds.length > 0) {
        postAccessUsers = await Users.findAll({
          where: {
            id: { [Op.in]: validUserIds }
          },
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        });
      }
    }

    // Get community members if needed
    const members = await CommunityMemberships.findAll({
      where: {
        community_id: id,
        status: 'active'
      },
      include: [
        {
          model: Users,
          as: 'user',
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        }
      ]
    });

    // Add the additional data to the community object
    const communityData = {
      ...community.toJSON(),
      post_access_users: postAccessUsers,
      members: members
    };

    res.json(communityData);
  } catch (error) {
    console.error('Error fetching community:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Update a community
router.put('/:id', validateToken, upload.fields([
  { name: 'profile_icon', maxCount: 1 },
  { name: 'banner_url', maxCount: 1 }
]), async (req, res) => {
  const transaction = await CommunityMemberships.sequelize.transaction();
  
  try {
    const { id } = req.params;
    const { 
      name, 
      description, 
      visibility, 
      hot_topics, 
      post_access_type, 
      post_access_users 
    } = req.body;

    const community = await Communities.findByPk(id, { transaction });
    if (!community) {
      await transaction.rollback();
      return res.status(404).json({ error: 'Community not found' });
    }

    // Check if user is the creator or admin
    const membership = await CommunityMemberships.findOne({
      where: {
        community_id: id,
        user_id: req.user.id,
        role: { [Op.in]: ['admin', 'moderator'] },
        status: 'active'
      },
      transaction
    });

    if (community.creator_id !== req.user.id && !membership) {
      await transaction.rollback();
      return res.status(403).json({ error: 'Only community admins can update the community' });
    }

    // Check if new name already exists (if name is being changed)
    if (name && name !== community.name) {
      const existingCommunity = await Communities.findOne({ 
        where: { name },
        transaction 
      });
      if (existingCommunity) {
        await transaction.rollback();        return res.status(400).json({ error: 'Community name already exists' });
      }
    }

    // Extract files like in Users route
    const profileIconFile = req.files['profile_icon'] ? req.files['profile_icon'][0] : null;
    const bannerFile = req.files['banner_url'] ? req.files['banner_url'][0] : null;

    // Handle file uploads
    let profileIconFilename = community.profile_icon;
    let bannerFilename = community.banner_url;
    let uploadErrors = [];

    try {
      // Upload new profile icon if provided
      if (profileIconFile) {
        try {
          // Delete old profile icon if exists
          if (community.profile_icon) {
            try {
              await deleteFromB2(community.profile_icon, 'communityProfile');
            } catch (deleteError) {
              console.log('Could not delete old profile icon:', deleteError.message);
            }
          }
          
          // Upload new profile icon
          const filename = generateUniqueFilename(profileIconFile.originalname);
          const result = await uploadToB2(profileIconFile.buffer, filename, 'communityProfile');
          
          // Store just the filename
          profileIconFilename = filename;
          
        } catch (uploadError) {
          uploadErrors.push("Profile icon: " + uploadError.message);
          // Continue with other updates even if profile icon upload fails
        }
      }

      // Upload new banner if provided
      if (bannerFile) {
        try {
          // Delete old banner if exists
          if (community.banner_url) {
            try {
              await deleteFromB2(community.banner_url, 'communityBanner');
            } catch (deleteError) {
              console.log('Could not delete old banner:', deleteError.message);
            }
          }
          
          // Upload new banner
          const filename = generateUniqueFilename(bannerFile.originalname);
          const result = await uploadToB2(bannerFile.buffer, filename, 'communityBanner');
          
          // Store just the filename
          bannerFilename = filename;
          
        } catch (uploadError) {
          uploadErrors.push("Banner: " + uploadError.message);
          // Continue with other updates even if banner upload fails
        }    }
    } catch (uploadError) {
      console.error('File upload error:', uploadError);
      uploadErrors.push("General upload error: " + uploadError.message);
      // Continue with community update even if uploads fail
    }

    // Parse JSON strings if they exist
    let parsedHotTopics = community.hot_topics;
    let parsedPostAccessUsers = community.post_access_users;

    if (hot_topics) {
      try {
        parsedHotTopics = typeof hot_topics === 'string' ? JSON.parse(hot_topics) : hot_topics;
      } catch (error) {
        console.error('Error parsing hot_topics:', error);
      }
    }

    if (post_access_users) {
      try {
        const parsed = typeof post_access_users === 'string' ? JSON.parse(post_access_users) : post_access_users;
        // Extract only user IDs if we have user objects
        if (Array.isArray(parsed)) {
          parsedPostAccessUsers = parsed.map(user => {
            // If it's an object with an id, extract the id
            if (typeof user === 'object' && user.id) {
              return user.id;
            }
            // If it's already just an ID, return as is
            return user;
          });
        } else {
          parsedPostAccessUsers = parsed;
        }
      } catch (error) {
        console.error('Error parsing post_access_users:', error);
      }
    }    // Handle post access type changes and role transitions
    const isPostAccessTypeChanging = post_access_type && post_access_type !== community.post_access_type;
    const currentModeratorIds = community.post_access_users || [];
    const newModeratorIds = parsedPostAccessUsers || [];
    const isModeratorListChanging = community.post_access_type === 'moderators' && 
      JSON.stringify(currentModeratorIds.sort()) !== JSON.stringify(newModeratorIds.sort());

    if (isPostAccessTypeChanging || isModeratorListChanging) {
      console.log('Updating roles in CommunityMemberships...');
      console.log('Old moderators:', currentModeratorIds);
      console.log('New moderators:', newModeratorIds);
      
      const oldType = community.post_access_type;
      const newType = post_access_type || community.post_access_type;

      if (newType === 'moderators' && newModeratorIds && newModeratorIds.length > 0) {
        console.log('Setting users as moderators:', newModeratorIds);
        // Update specified users to moderators
        const moderatorUpdateResult = await CommunityMemberships.update(
          { role: 'moderator' },
          {
            where: {
              community_id: id,
              user_id: { [Op.in]: newModeratorIds },
              status: 'active'
            },
            transaction
          }
        );
        console.log(`Updated ${moderatorUpdateResult[0]} users to moderators`);

        // Update non-moderators to members (if they were moderators before)
        const memberUpdateResult = await CommunityMemberships.update(
          { role: 'member' },
          {
            where: {
              community_id: id,
              user_id: { 
                [Op.and]: [
                  { [Op.ne]: community.creator_id },
                  { [Op.notIn]: newModeratorIds }
                ]
              },
              role: 'moderator',
              status: 'active'
            },
            transaction
          }
        );
        console.log(`Updated ${memberUpdateResult[0]} former moderators to members`);
      } else if (oldType === 'moderators' && (newType === 'everyone' || newType === 'creator')) {
        console.log('Converting all moderators to members');
        // Convert all moderators to members when changing away from moderators
        const demoteResult = await CommunityMemberships.update(
          { role: 'member' },
          {
            where: {
              community_id: id,
              user_id: { [Op.ne]: community.creator_id },
              role: 'moderator',
              status: 'active'
            },
            transaction
          }
        );
        console.log(`Updated ${demoteResult[0]} moderators to members`);
      }
    }

    // Set final post access users based on type
    let finalPostAccessUsers = parsedPostAccessUsers;
    if (post_access_type === 'everyone' || post_access_type === 'creator') {
      finalPostAccessUsers = [];
    }

    console.log('Final post_access_users:', finalPostAccessUsers);

    // Update the community
    await community.update({
      ...(name && { name }),
      ...(description !== undefined && { description }),
      ...(visibility && { visibility }),
      ...(parsedHotTopics && { hot_topics: parsedHotTopics }),
      ...(post_access_type && { post_access_type }),
      post_access_users: finalPostAccessUsers,
      profile_icon: profileIconFilename,
      banner_url: bannerFilename
    }, { transaction });

    // Commit the transaction
    await transaction.commit();    const updatedCommunity = await Communities.findByPk(id, {
      include: [
        {
          model: Users,
          as: 'creator',
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        }
      ]
    });

    const response = { success: true, community: updatedCommunity };
    
    if (uploadErrors.length > 0) {
      response.warnings = uploadErrors;
    }
    
    res.json(response);
  } catch (error) {
    await transaction.rollback();
    console.error('Error updating community:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Delete a community
router.delete('/:id', validateToken, async (req, res) => {
  const transaction = await Communities.sequelize.transaction();
  
  try {
    const { id } = req.params;

    const community = await Communities.findByPk(id, { transaction });
    if (!community) {
      await transaction.rollback();
      return res.status(404).json({ error: 'Community not found' });
    }

    // Only creator can delete the community
    if (community.creator_id !== req.user.id) {
      await transaction.rollback();
      return res.status(403).json({ error: 'Only the community creator can delete the community' });
    }

    console.log(`Starting deletion of community: ${community.name} (ID: ${id})`);

    // Step 1: Delete all community posts
    const deletedPosts = await CommunityPosts.destroy({
      where: { community_id: id },
      transaction
    });
    console.log(`Deleted ${deletedPosts} community posts`);

    // Step 2: Delete all community memberships
    const deletedMemberships = await CommunityMemberships.destroy({
      where: { community_id: id },
      transaction
    });
    console.log(`Deleted ${deletedMemberships} community memberships`);

    // Step 3: Delete the community itself
    await community.destroy({ transaction });
    console.log(`Deleted community: ${community.name}`);

    // Commit the transaction
    await transaction.commit();

    res.json({ 
      success: true,
      message: 'Community deleted successfully',
      deletedData: {
        posts: deletedPosts,
        memberships: deletedMemberships,
        community: community.name
      }
    });
  } catch (error) {
    await transaction.rollback();
    console.error('Error deleting community:', error);
    res.status(500).json({ error: 'Failed to delete community' });
  }
});

// Get communities user has joined
router.get('/user/:userId/joined', async (req, res) => {
  try {
    const { userId } = req.params;
    const { page = 1, limit = 20 } = req.query;
    const offset = (page - 1) * limit;

    const memberships = await CommunityMemberships.findAndCountAll({
      where: { 
        user_id: userId,
        status: 'active'
      },
      include: [
        {
          model: Communities,
          as: 'community',
          include: [
            {
              model: Users,
              as: 'creator',
              attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
            }
          ]
        }
      ],
      order: [['joined_at', 'DESC']],
      limit: parseInt(limit),
      offset: parseInt(offset)
    });

    const communities = memberships.rows.map(membership => ({
      ...membership.community.toJSON(),
      user_role: membership.role,
      joined_at: membership.joined_at
    }));

    res.json({
      communities,
      pagination: {
        total: memberships.count,
        page: parseInt(page),
        limit: parseInt(limit),
        totalPages: Math.ceil(memberships.count / limit)
      }
    });
  } catch (error) {
    console.error('Error fetching user communities:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Get communities created by user
router.get('/user/:userId/created', async (req, res) => {
  try {
    const { userId } = req.params;
    const { page = 1, limit = 20 } = req.query;
    const offset = (page - 1) * limit;

    const { count, rows: communities } = await Communities.findAndCountAll({
      where: { creator_id: userId },
      include: [
        {
          model: Users,
          as: 'creator',
          attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
        }
      ],
      order: [['createdAt', 'DESC']],
      limit: parseInt(limit),
      offset: parseInt(offset)
    });

    res.json({
      communities,
      pagination: {
        total: count,
        page: parseInt(page),
        limit: parseInt(limit),
        totalPages: Math.ceil(count / limit)
      }
    });
  } catch (error) {
    console.error('Error fetching created communities:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Join a community
router.post('/:id/join', validateToken, async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user.id;

    // Check if community exists
    const community = await Communities.findByPk(id);
    if (!community) {
      return res.status(404).json({ error: 'Community not found' });
    }

    // Check if user is already a member
    const existingMembership = await CommunityMemberships.findOne({
      where: {
        community_id: id,
        user_id: userId
      }
    });

    if (existingMembership) {
      if (existingMembership.status === 'active') {
        return res.status(400).json({ error: 'Already a member of this community' });
      } else {
        // Reactivate membership
        await existingMembership.update({ status: 'active', joined_at: new Date() });
      }
    } else {
      // Create new membership
      await CommunityMemberships.create({
        community_id: id,
        user_id: userId,
        role: 'member',
        status: 'active',
        joined_at: new Date()
      });
    }

    // Increment member count
    await community.increment('member_count');

    res.json({ message: 'Successfully joined community' });
  } catch (error) {
    console.error('Error joining community:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Leave a community
router.delete('/:id/leave', validateToken, async (req, res) => {
  try {
    const { id } = req.params;
    const userId = req.user.id;

    // Check if community exists
    const community = await Communities.findByPk(id);
    if (!community) {
      return res.status(404).json({ error: 'Community not found' });
    }

    // Check if user is the creator
    if (community.creator_id === userId) {
      return res.status(400).json({ error: 'Community creator cannot leave the community' });
    }

    // Find membership
    const membership = await CommunityMemberships.findOne({
      where: {
        community_id: id,
        user_id: userId,
        status: 'active'
      }
    });

    if (!membership) {
      return res.status(400).json({ error: 'Not a member of this community' });
    }

    // Remove membership
    await membership.destroy();

    // Decrement member count
    await community.decrement('member_count');

    res.json({ message: 'Successfully left community' });
  } catch (error) {
    console.error('Error leaving community:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Get posts from a specific community
router.get('/:id/posts', validateToken, async (req, res) => {
  try {
    const { id } = req.params;
    const { page = 1, limit = 20 } = req.query;
    const offset = (page - 1) * limit;

    // Check if community exists
    const community = await Communities.findByPk(id);
    if (!community) {
      return res.status(404).json({ error: 'Community not found' });
    }

    // Get community posts with post details and interactions
    const communityPosts = await CommunityPosts.findAndCountAll({
      where: { 
        community_id: id,
        removed: false 
      },
      include: [        {
          model: Post,
          as: 'post',
          where: { isShort: false }, // Only fetch posts, not shorts
          include: [
            {
              model: Users,
              as: 'author',
              attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
            }
          ]
        }
      ],
      order: [['pinned', 'DESC'], ['date_posted', 'DESC']],
      limit: parseInt(limit),
      offset: parseInt(offset)
    });    // Format posts with interaction data
    const posts = communityPosts.rows.map(cp => cp.post);
    const postIds = posts.map(post => post.id);
    
    // Get user interactions for all posts in one query
    let likedPostIds = new Set();
    let savedPostIds = new Set();
    
    if (req.user && postIds.length > 0) {
      const [likeStatuses, saveStatuses] = await Promise.all([
        PostLike.findAll({
          where: { 
            userId: req.user.id,
            postId: { [Op.in]: postIds }
          },
          attributes: ['postId']
        }),
        PostSaved.findAll({
          where: {
            userId: req.user.id,
            postId: { [Op.in]: postIds }
          },
          attributes: ['postId']
        })
      ]);
      
      likedPostIds = new Set(likeStatuses.map(like => like.postId));
      savedPostIds = new Set(saveStatuses.map(save => save.postId));
    }
    
    const postsWithInteractions = communityPosts.rows.map((communityPost) => {
      const post = communityPost.post;
      
      return {
        ...post.toJSON(),
        interactions: {
          liked: likedPostIds.has(post.id),
          saved: savedPostIds.has(post.id)
        },
        community_post_id: communityPost.id,
        pinned: communityPost.pinned,
        date_posted: communityPost.date_posted
      };
    });

    res.json({
      posts: postsWithInteractions,
      pagination: {
        currentPage: parseInt(page),
        totalPages: Math.ceil(communityPosts.count / limit),
        totalPosts: communityPosts.count,
        hasMore: (page * limit) < communityPosts.count
      }
    });
  } catch (error) {
    console.error('Error fetching community posts:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});



module.exports = router;
