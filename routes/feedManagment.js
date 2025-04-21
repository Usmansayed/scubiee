const { UserInteractions, Post, PostRelation } = require('../models');
const Sequelize = require('sequelize');
const Op = Sequelize.Op;
const compromise = require('compromise');
const stopwords = require('stopwords').english;

const MAX_INTERACTIONS = 200;

// Fetch the last 200 interactions and categorize them
async function fetchUserInteractions(userId) {
  const interactions = await UserInteractions.findAll({
    where: { userId },
    order: [['updatedAt', 'DESC']],
    limit: MAX_INTERACTIONS,
  });

  const categorizedPosts = {};

  interactions.forEach(interaction => {
    const type = interaction.interactionType; // e.g., 'recommended', 'comment', 'like', etc.
    if (!categorizedPosts[type]) {
      categorizedPosts[type] = [];
    }
    categorizedPosts[type].push(interaction.postId);
  });

  return categorizedPosts;
}

// Fetch descendant posts with depth 1 more than the interacted posts
async function fetchDescendantPosts(postIds) {
  const descendants = await PostRelation.findAll({
    where: {
      ancestorId: postIds,
      depth: 1,
    },
    attributes: ['descendantId'],
  });

  return descendants.map(rel => rel.descendantId);
}

// Extract keywords from posts
async function extractKeywordsFromPosts(postIds) {
  const posts = await Post.findAll({
    where: { id: postIds },
    attributes: ['title', 'description'],
  });

  let keywords = [];
  let mentions = [];
  let hashtags = [];

  posts.forEach(post => {
    const text = `${post.title} ${post.description}`.toLowerCase();

    // Extract hashtags and mentions
    const postHashtags = text.match(/#\w+/g) || [];
    const postMentions = text.match(/@\w+/g) || [];

    hashtags = hashtags.concat(postHashtags);
    mentions = mentions.concat(postMentions);

    // Extract nouns and verbs using Compromise.js
    const doc = compromise(text);
    const nouns = doc.nouns().out('array');
    const verbs = doc.verbs().out('array');

    // Remove stopwords
    const words = nouns.concat(verbs).filter(word => !stopwords.includes(word));

    keywords = keywords.concat(words);
  });

  // Count keyword frequency
  const keywordFrequency = {};
  keywords.forEach(word => {
    keywordFrequency[word] = (keywordFrequency[word] || 0) + 1;
  });

  return {
    keywords: keywordFrequency,
    hashtags: Array.from(new Set(hashtags)),
    mentions: Array.from(new Set(mentions)),
  };
}

// Build the keyword matrix based on scores
function buildKeywordMatrix(keywordData, scores) {
  const matrix = {};

  Object.entries(keywordData.keywords).forEach(([keyword, freq]) => {
    const score = scores[keyword] || 0;
    if (!matrix[score]) {
      matrix[score] = [];
    }
    matrix[score].push(keyword);
  });

  if (keywordData.hashtags.length > 0) {
    if (!matrix['hashtags']) {
      matrix['hashtags'] = [];
    }
    matrix['hashtags'] = keywordData.hashtags;
  }

  if (keywordData.mentions.length > 0) {
    if (!matrix['mentions']) {
      matrix['mentions'] = [];
    }
    matrix['mentions'] = keywordData.mentions;
  }

  return matrix;
}

// ...existing code...

async function getKeywordMatrixForUser(userId) {
  try {
    console.log(`Fetching keyword matrix for user: ${userId}`);
    
    const categorizedPosts = await fetchUserInteractions(userId);
    console.log('Categorized posts:', categorizedPosts);

    const interactionTypes = ['recommended', 'comment', 'like', 'save', 'read'];
    const ancestorInteractionTypes = ['recommended', 'save', 'read'];

    let postIds = [];
    let ancestorPostIds = [];

    interactionTypes.forEach(type => {
      if (categorizedPosts[type]) {
        postIds = postIds.concat(categorizedPosts[type]);
      }
    });
    console.log('Collected postIds:', postIds);

    ancestorInteractionTypes.forEach(type => {
      if (categorizedPosts[type]) {
        ancestorPostIds = ancestorPostIds.concat(categorizedPosts[type]);
      }
    });
    console.log('Collected ancestorPostIds:', ancestorPostIds);

    const descendantPostIds = await fetchDescendantPosts(ancestorPostIds);
    console.log('Descendant postIds:', descendantPostIds);

    const allPostIds = Array.from(new Set([...postIds, ...descendantPostIds]));
    console.log('Total unique postIds:', allPostIds.length);

    const keywordData = await extractKeywordsFromPosts(allPostIds);
    console.log('Extracted keyword data:', keywordData);

    // Implement a basic scoring system
    const scores = {};
    Object.entries(keywordData.keywords).forEach(([keyword, frequency]) => {
      // Simple scoring: frequency * 10
      scores[keyword] = frequency * 10;
    });
    
    // Add higher scores for hashtags and mentions
    keywordData.hashtags.forEach(hashtag => {
      scores[hashtag] = 100; // Higher priority for hashtags
    });
    
    keywordData.mentions.forEach(mention => {
      scores[mention] = 80; // High priority for mentions
    });

    console.log('Calculated scores:', scores);

    const matrix = buildKeywordMatrix(keywordData, scores);
    console.log('Final keyword matrix:', matrix);

    return matrix;
  } catch (error) {
    console.error('Error in getKeywordMatrixForUser:', error);
    throw error;
  }
}
const express = require('express');
const router = express.Router();

// ... keep all your existing functions ...

// Add the route handler
router.get('/test-matrix/:userId', async (req, res) => {
  try {
    const matrix = await getKeywordMatrixForUser(req.params.userId);
    res.json({ success: true, matrix });
  } catch (error) {
    console.error('Error in test-matrix endpoint:', error);
    res.status(500).json({ success: false, error: error.message });
  }
});

// Export the router instead of the object
module.exports = router;
module.exports = {
  getKeywordMatrixForUser,
  fetchUserInteractions,
  fetchDescendantPosts,
  extractKeywordsFromPosts,
  buildKeywordMatrix
};