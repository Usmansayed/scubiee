const express = require("express");
const router = express.Router();
const { Post, Users, Hashtag, sequelize } = require("../models");
const { Op } = require("sequelize");
const { validateToken } = require("../middlewares/AuthMiddleware");

// Search for posts
router.post("/posts", validateToken, async (req, res, next) => {
  try {
    const { query, page = 1 } = req.body;
    const pageSize = 10;
    const offset = (page - 1) * pageSize;

    const posts = await Post.findAll({
      where: {
        [Op.or]: [
          { content: { [Op.like]: `%${query}%` } },
          { title: { [Op.like]: `%${query}%` } }
        ]
      },
      include: [
        {
          model: Hashtag,
          through: { attributes: [] },
          attributes: ["id", "name"],
        },
        {
          model: Users,
          as: "author",
          attributes: ["id", "username", "profilePicture", "firstName", "lastName", "Verified"],
        },
      ],
      attributes: ["id", "title", "description", "content", "views", "likes", "media", "createdAt", "isShort"],
      limit: pageSize,
      offset: offset,
      order: [["createdAt", "DESC"]],
      distinct: true,
    });

    const formattedPosts = posts.map(post => {
      const postData = post.get({ plain: true });
      
      if (!postData.thumbnail && postData.media && Array.isArray(postData.media) && postData.media.length > 0) {
        postData.thumbnail = postData.media[0].url;
      }
      
      return postData;
    });

    const totalCount = await Post.count({
      where: {
        [Op.or]: [
          { content: { [Op.like]: `%${query}%` } },
          { title: { [Op.like]: `%${query}%` } }
        ]
      },
      distinct: true,
      include: [
        {
          model: Hashtag,
          through: { attributes: [] },
          attributes: [],
        }
      ]
    });

    res.json({
      posts: formattedPosts,
      pagination: {
        page,
        pageSize,
        totalPages: Math.ceil(totalCount / pageSize),
        totalCount,
        hasMore: page * pageSize < totalCount
      }
    });
  } catch (error) {
    next(error);
  }
});

// Search for hashtags
router.post("/tags", validateToken, async (req, res, next) => {
  try {
    const { tag } = req.body;
    const hashtags = await Hashtag.findAll({
      where: {
        name: { [Op.like]: `%${tag}%` }
      },
      attributes: ["id", "name", "Count"],
      order: [["Count", "DESC"]],
      limit: 10
    });
    res.json(hashtags);
  } catch (error) {
    next(error);
  }
});

// Search for users
router.post("/users", validateToken, async (req, res, next) => {
  try {
    const UsersName = req.user.username;
    const { username } = req.body;
    const users = await Users.findAll({
      where: {
        [Op.and]: [
          { username: { [Op.ne]: UsersName } },
          {
            [Op.or]: [
              { username: { [Op.like]: `%${username}%` } },
              { firstName: { [Op.like]: `%${username}%` } },
              { lastName: { [Op.like]: `%${username}%` } }
            ]
          }
        ]
      },
      attributes: ["id", "username", "profilePicture", "firstName", "lastName", "Verified"],
      limit: 10
    });
    res.json(users);
  } catch (error) {
    next(error);
  }
});

// Get posts by hashtag
router.get("/posts/hashtag/:tagName", validateToken, async (req, res, next) => {
  try {
    const { tagName } = req.params;
    
    const hashtag = await Hashtag.findOne({
      where: { name: tagName }
    });
    
    if (!hashtag) {
      return res.status(404).json({ error: "Hashtag not found" });
    }
    
    const posts = await Post.findAll({
      include: [
        {
          model: Hashtag,
          where: { id: hashtag.id },
          through: { attributes: [] },
          attributes: []
        },
        {
          model: Users,
          as: "author",
          attributes: ["id", "username", "profilePicture", "Verified"]
        }
      ],
      attributes: ["id", "title", "content", "views", "likes", "media", "createdAt", "isShort"],
      limit: 20,
      order: [["createdAt", "DESC"]],
      distinct: true
    });
    
    const formattedPosts = posts.map(post => {
      const postData = post.get({ plain: true });
      
      if (!postData.thumbnail && postData.media && Array.isArray(postData.media) && postData.media.length > 0) {
        postData.thumbnail = postData.media[0].url;
      }
      
      return postData;
    });

    res.json({
      hashtag: {
        name: hashtag.name,
        count: hashtag.Count
      },
      posts: formattedPosts
    });
  } catch (error) {
    next(error);
  }
});

router.post('/posts/by-tags', validateToken, async (req, res, next) => {
  const { tags } = req.body;
  if (!tags || !tags.length) {
    return res.status(400).json({ error: 'Tags are required' });
  }

  try {
    const posts = await Posts.findAll({
      attributes: [
        'id',
        'title',
        'description',
        'hashtags',
        'views',
        'likes',
        'comments',
        'shares',
        'recommended',
        'readBy',
        'dislikes',
        'reports',
      ],
    });

    const results = posts.filter((post) =>
      post.hashtags.some((hashtag) => tags.includes(hashtag))
    );

    res.json(results);
  } catch (error) {
    next(error);
  }
});

// Combined route to get profile information for the current or another user
router.get('/profile-info', validateToken, async (req, res, next) => {
  const userId = req.body.userId || req.user.id;

  try {
    const user = await Users.findOne({
      where: { id: userId },
      attributes: ['firstName', 'lastName', 'username', 'Bio', 'SocialMedia', 'profilePicture']
    });

    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }

    const postCount = await Post.count({
      where: { authorId: userId }
    });

    const following = await Follow.findAll({
      where: { followerId: userId },
      attributes: ['followingId']
    });

    const followers = await Follow.findAll({
      where: { followingId: userId },
      attributes: ['followerId']
    });

    const followingIds = following.map(f => f.followingId);
    const followerIds = followers.map(f => f.followerId);

    res.json({
      user,
      postCount,
      following: followingIds,
      followers: followerIds
    });
  } catch (error) {
    next(error);
  }
});

// Advanced route to fetch posts by hashtag using ranking algorithm
router.get('/posts/hashtag/:tag', validateToken, async (req, res, next) => {
  const { tag } = req.params;
  const limit = parseInt(req.query.limit) || 18;
  const lastScore = parseFloat(req.query.lastScore) || null;
  const lastCreatedAt = req.query.lastCreatedAt ? new Date(req.query.lastCreatedAt) : null;
  
  try {
    const hashtag = await Hashtag.findOne({
      where: { name: tag.toLowerCase() }
    });

    if (!hashtag) {
      return res.status(404).json({ error: "Hashtag not found" });
    }

    const posts = await Post.findAll({
      attributes: [
        'id',
        'title',
        'description',
        'content',
        'views',
        'likes',
        'comments',
        'shared',
        'bookmarks',
        'thumbnail',
        'createdAt',
        'isShort'
      ],
      include: [
        {
          model: Hashtag,
          where: { id: hashtag.id },
          through: { attributes: [] },
          as: 'Hashtags',
          attributes: []
        },
        {
          model: Users,
          as: 'author',
          attributes: [
            'id', 
            'username', 
            'profilePicture', 
            'firstName', 
            'lastName', 
            'Verified'
          ]
        }
      ]
    });

    const currentTime = new Date();
    const lambda = 0.05;

    const rankedPosts = posts.map(post => {
      const plainPost = post.get({ plain: true });
      
      const ageInHours = (currentTime - new Date(plainPost.createdAt)) / (1000 * 60 * 60);
      const timeDecay = Math.exp(-lambda * ageInHours);
      
      const views = plainPost.views || 0;
      const likes = plainPost.likes || 0;
      const comments = plainPost.comments || 0;
      const shares = plainPost.shared || 0;
      const bookmarks = plainPost.bookmarks || 0;
      
      const engagement = (
        (views * 0.10) + 
        (likes * 0.15) + 
        (comments * 0.25) + 
        (shares * 0.25) + 
        (bookmarks * 0.25)
      ) / 100;
      
      const verified = plainPost.author?.Verified ? 0.40 : 0;
      const followerScore = 0.25;
      const postsCount = 1;
      const postsScore = postsCount / (postsCount + 10);
      
      const authorCredibility = 
        (verified) + 
        (followerScore * 0.50) + 
        (postsScore * 0.10);
      
      const finalScore = (
        (0.40 * timeDecay) + 
        (0.40 * engagement) + 
        (0.20 * authorCredibility)
      );
      
      let processedPost = {
        ...plainPost,
        finalScore,
        formattedDate: new Date(plainPost.createdAt).toLocaleDateString('en-US', {
          day: 'numeric',
          month: 'short',
          year: 'numeric'
        }),
        formattedViews: plainPost.views > 999 
          ? (plainPost.views/1000).toFixed(1) + 'k' 
          : plainPost.views,
        formattedLikes: plainPost.likes > 999 
          ? (plainPost.likes/1000).toFixed(1) + 'k' 
          : plainPost.likes,
        authorVerified: plainPost.author?.Verified || false
      };
      
  

      delete processedPost.content;
      
      return processedPost;
    });

    let paginatedPosts;
    if (lastScore && lastCreatedAt) {
      paginatedPosts = rankedPosts
        .filter(post => 
          post.finalScore < lastScore || 
          (post.finalScore === lastScore && new Date(post.createdAt) < new Date(lastCreatedAt))
        )
        .sort((a, b) => b.finalScore - a.finalScore || new Date(b.createdAt) - new Date(a.createdAt))
        .slice(0, limit);
    } else {
      paginatedPosts = rankedPosts
        .sort((a, b) => b.finalScore - a.finalScore || new Date(b.createdAt) - new Date(a.createdAt))
        .slice(0, limit);
    }

    const hasMore = rankedPosts.length > (rankedPosts.indexOf(paginatedPosts[paginatedPosts.length - 1]) + 1);
    const nextCursor = paginatedPosts.length > 0 ? {
      lastScore: paginatedPosts[paginatedPosts.length - 1].finalScore,
      lastCreatedAt: paginatedPosts[paginatedPosts.length - 1].createdAt
    } : null;

    const totalCount = await PostHashtags.count({
      where: { hashtagId: hashtag.id }
    });
    
    res.json({
      posts: paginatedPosts,
      pagination: {
        total: totalCount,
        hasMore,
        nextCursor
      },
      hashtag: {
        name: hashtag.name,
        count: hashtag.count || totalCount
      }
    });
    
  } catch (error) {
    next(error);
  }
});

router.get('/check-profile/:username', validateToken, async (req, res, next) => {
  try {
    const { username } = req.params;
    
    
    const isOwnProfile = username === req.user.username;
    
    if (isOwnProfile) {
      return res.status(200).json({ isOwnProfile: true });
    }
    return res.status(200).json({ isOwnProfile: false });
    
  } catch (error) {
    next(error);
  }
});

router.get('/user-check', validateToken, (req, res, next) => {
  try {
    if (!req.user) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    const userData = {
      id: req.user.id,
      username: req.user.username,
      firstName: req.user.firstName,
      lastName: req.user.lastName,
      profilePicture: req.user.profilePicture,
      email: req.user.email,
      isPosting: req.user.isPosting || false, // Include isPosting status
    };

    return res.status(200).json(userData);
  } catch (error) {
    next(error);
  }
});

module.exports = router;

