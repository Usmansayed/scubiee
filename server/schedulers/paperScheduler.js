const cron = require('node-cron');
const moment = require('moment-timezone');
const { Papers, PaperPosts, Users, Post, PostView, PostLike, PostSaved, Follow } = require('../models');
const { Op } = require('sequelize');

class PaperScheduler {
  constructor() {
    this.isRunning = false;
    this.timezone = 'Asia/Kolkata';
    this.retainDays = 7; // Keep papers for 7 days
  }
  // Initialize the scheduler
  start() {
    console.log('🚀 [SCHEDULER] Starting Paper Scheduler...');
      // Run every hour at 55 minutes (e.g., 12:55, 1:55, 2:55, etc.)
    // This gives us 5 minutes before the next hour to generate papers
    this.cronJob = cron.schedule('55 * * * *', async () => {
      await this.processPaperGeneration();
    }, {
      scheduled: true,
      timezone: this.timezone
    });

    // Run every hour at 01 minutes to mark scheduled papers as delivered
    this.deliveryJob = cron.schedule('1 * * * *', async () => {
      await this.markScheduledPapersAsDelivered();
    }, {
      scheduled: true,
      timezone: this.timezone
    });

    // Also run a cleanup job daily at 2:00 AM to remove old papers
    this.cleanupJob = cron.schedule('0 2 * * *', async () => {
      await this.cleanupOldPapers();
    }, {
      scheduled: true,
      timezone: this.timezone
    });

    console.log('✅ [SCHEDULER] Paper Scheduler started successfully');
    console.log('📅 [SCHEDULER] Paper generation: Every hour at 55 minutes');
    console.log('📬 [SCHEDULER] Paper delivery: Every hour at 01 minutes');
    console.log('🧹 [SCHEDULER] Cleanup: Daily at 2:00 AM');
  }
  // Stop the scheduler
  stop() {
    if (this.cronJob) {
      this.cronJob.destroy();
    }
    if (this.deliveryJob) {
      this.deliveryJob.destroy();
    }
    if (this.cleanupJob) {
      this.cleanupJob.destroy();
    }
    console.log('🛑 [SCHEDULER] Paper Scheduler stopped');
  }

  // Main function to process paper generation
  async processPaperGeneration() {
    if (this.isRunning) {
      console.log('⏳ [SCHEDULER] Previous job still running, skipping...');
      return;
    }

    this.isRunning = true;
    const startTime = Date.now();
    
    try {
      const currentIST = moment().tz(this.timezone);
      const nextHour = currentIST.clone().add(1, 'hour').hour();
      const currentDate = currentIST.format('YYYY-MM-DD');
      const tomorrowDate = currentIST.clone().add(1, 'day').format('YYYY-MM-DD');
        console.log(`\n🕐 [SCHEDULER] Running at ${currentIST.format('YYYY-MM-DD HH:mm:ss')}`);
      console.log(`📋 [SCHEDULER] Preparing papers for hour: ${nextHour}:00 (5 minutes early)`);

      // Get all active papers
      const activePapers = await Papers.findAll({
        where: {
          status: 'active',
          processingStatus: 'completed',
          deleted: false
        },
        include: [{
          model: Users,
          as: 'author',
          attributes: ['id', 'username', 'intrest', 'state']
        }]
      });

      console.log(`📰 [SCHEDULER] Found ${activePapers.length} active papers`);

      let generatedCount = 0;
      let skippedCount = 0;
      let errorCount = 0;      for (const paper of activePapers) {
        try {
          const deliveryHour = this.parseDeliveryTime(paper.deliveryTime);
          
          // Generate today's paper if:
          // 1. We're within 1 hour of delivery time
          // 2. Paper doesn't exist yet
          const todayExists = await this.paperExistsForDate(paper.id, currentDate);
          if (!todayExists && (nextHour === deliveryHour || currentIST.hour() >= deliveryHour)) {
            await this.generatePaperForDate(paper, currentDate);
            generatedCount++;
            console.log(`✅ [SCHEDULER] Generated today's paper: ${paper.title} for ${currentDate}`);
          }
          
          // Generate tomorrow's paper only if:
          // 1. Today's paper exists
          // 2. We're generating advance papers (5 minutes before next day)
          // 3. Tomorrow's paper doesn't exist yet
          const tomorrowExists = await this.paperExistsForDate(paper.id, tomorrowDate);
          if (todayExists && !tomorrowExists && nextHour === deliveryHour) {
            await this.generatePaperForDate(paper, tomorrowDate);
            generatedCount++;
            console.log(`📅 [SCHEDULER] Generated tomorrow's paper: ${paper.title} for ${tomorrowDate}`);
          }
          
          if (!todayExists && nextHour !== deliveryHour && currentIST.hour() < deliveryHour) {
            skippedCount++;
          }

        } catch (error) {
          errorCount++;
          console.error(`❌ [SCHEDULER] Error processing paper ${paper.title}:`, error.message);
        }
      }

      const duration = Date.now() - startTime;
      console.log(`\n📊 [SCHEDULER] Execution completed in ${duration}ms`);
      console.log(`   ✅ Generated: ${generatedCount}`);
      console.log(`   ⏭️  Skipped: ${skippedCount}`);
      console.log(`   ❌ Errors: ${errorCount}`);

    } catch (error) {
      console.error('💥 [SCHEDULER] Critical error in paper generation:', error);
    } finally {
      this.isRunning = false;
    }
  }

  // Check if a paper should be generated for the next hour
  async shouldGeneratePaper(paper, nextHour, targetDate) {
    // Parse the delivery time (e.g., "10:00 AM" -> 10)
    const deliveryHour = this.parseDeliveryTime(paper.deliveryTime);
    
    // Only generate if the next hour matches the delivery hour
    if (nextHour !== deliveryHour) {
      return false;
    }

    // Check if paper already exists for target date
    const exists = await this.paperExistsForDate(paper.id, targetDate);
    return !exists;
  }

  // Parse delivery time string to 24-hour format
  parseDeliveryTime(deliveryTime) {
    // Handle formats like "10:00 AM", "2:00 PM", etc.
    const [time, period] = deliveryTime.split(' ');
    const [hour, minute] = time.split(':').map(Number);
    
    if (period === 'PM' && hour !== 12) {
      return hour + 12;
    } else if (period === 'AM' && hour === 12) {
      return 0;
    }
    return hour;
  }

  // Check if a paper exists for a specific date
  async paperExistsForDate(paperId, date) {
    const count = await PaperPosts.count({
      where: {
        paperId: paperId,
        paperDate: date
      }
    });
    return count > 0;
  }

  // Generate a paper for a specific date
  async generatePaperForDate(paper, targetDate) {
    try {
      // Use the same algorithm as the main paper generation
      const recommendationsData = await this.generatePaperRecommendations(paper, paper.author.id);
      
      if (!recommendationsData || !recommendationsData.recommendations || recommendationsData.recommendations.length === 0) {
        console.log(`⚠️  [SCHEDULER] No suitable content found for ${paper.title} on ${targetDate}`);
        return;
      }

      // Create new PaperPost with generated recommendations
      const postIds = recommendationsData.recommendations.map(rec => rec.id);
      const paperPost = await PaperPosts.create({
        paperId: paper.id,
        paperDate: targetDate,
        deliveryTime: paper.deliveryTime,
        posts: postIds,
        status: 'scheduled', // Mark as scheduled until delivery time
        timezone: this.timezone      });

      return paperPost;

    } catch (error) {
      console.error(`❌ [SCHEDULER] Error generating paper for ${paper.title} on ${targetDate}:`, error);
      throw error;
    }
  }

  // Enhanced paper recommendation algorithm (adapted from the main route)
  async generatePaperRecommendations(paper, userId) {
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
      
      // Time-based prioritization (last 7 days for scheduled generation)
      const last7Days = new Date(currentTime.getTime() - 7 * 24 * 60 * 60 * 1000);
      whereConditions.createdAt = { [Op.gte]: last7Days };
      
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

      if (posts.length === 0) {
        return { recommendations: [] };
      }

      // Score each post using the sophisticated algorithm
      const scoredPosts = posts.map(post => {
        const score = this.calculatePostScore(post, paper, userInterests, userState, followingIds, currentTime);
        return {
          post: post,
          score: score.total,
          breakdown: score.breakdown
        };
      });

      // Sort by score and take the top posts
      const rankedPosts = scoredPosts
        .sort((a, b) => b.score - a.score)
        .slice(0, paper.postCount);

      // Get user interaction data for the selected posts
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
          viewed: false // These are unviewed by definition
        }
      }));

      return {
        recommendations,
        totalFound: recommendations.length,
        algorithm: 'scheduler-v1.0'
      };

    } catch (error) {
      console.error('Error in generatePaperRecommendations:', error);
      throw error;
    }
  }

  // Calculate post score (simplified version of the main algorithm)
  calculatePostScore(post, paper, userInterests, userState, followingIds, currentTime) {
    const plainPost = post.get({ plain: true });
    let totalScore = 0;
    let scoreBreakdown = {};
    
    // 1. Time Decay Score (25%) - Prioritize recent content
    const ageInHours = (currentTime - new Date(plainPost.createdAt)) / (1000 * 60 * 60);
    let timeScore;
    if (ageInHours <= 24) {
      timeScore = 1.0; // Maximum score for last 24 hours
    } else if (ageInHours <= 72) {
      timeScore = 0.8; // Good score for last 3 days
    } else {
      timeScore = Math.exp(-0.02 * ageInHours); // Gradual decay for older content
    }
    scoreBreakdown.timeScore = timeScore * 0.25;
    
    // 2. Content Matching (30%) - Match with paper description
    let contextScore = 0;
    const postContent = (plainPost.content || plainPost.description || '').toLowerCase();
    const paperDescription = (paper.description || '').toLowerCase();
    
    // Simple keyword matching
    const paperKeywords = paperDescription.split(/\s+/).filter(word => word.length > 3);
    const matchingKeywords = paperKeywords.filter(keyword => 
      postContent.includes(keyword)
    ).length;
    
    if (paperKeywords.length > 0) {
      contextScore = Math.min(matchingKeywords / paperKeywords.length, 1.0);
    }
    scoreBreakdown.contextScore = contextScore * 0.30;
    
    // 3. Region Matching (15%)
    let regionScore = 0.5; // Default neutral score
    if (userState && plainPost.author && plainPost.author.state) {
      regionScore = userState === plainPost.author.state ? 1.0 : 0.3;
    }
    scoreBreakdown.regionScore = regionScore * 0.15;
    
    // 4. Engagement Score (20%)
    const engagementScore = Math.min(
      (plainPost.likes * 0.4 + plainPost.comments * 0.6 + plainPost.shared * 0.8) / 100,
      1.0
    );
    scoreBreakdown.engagementScore = engagementScore * 0.20;
    
    // 5. Social Signals (10%)
    const socialScore = followingIds.includes(plainPost.author.id) ? 1.0 : 0.0;
    scoreBreakdown.socialScore = socialScore * 0.10;
    
    // Calculate total score
    totalScore = Object.values(scoreBreakdown).reduce((sum, score) => sum + score, 0);
    
    return {
      total: totalScore,
      breakdown: scoreBreakdown
    };
  }

  // Mark scheduled papers as delivered when their time arrives
  async markScheduledPapersAsDelivered() {
    try {
      const currentIST = moment().tz(this.timezone);
      console.log(`📬 [DELIVERY] Checking for papers to mark as delivered at ${currentIST.format('YYYY-MM-DD HH:mm:ss')}`);
      
      const deliveredCount = await PaperPosts.markScheduledAsDelivered(this.timezone);
      
      if (deliveredCount > 0) {
        console.log(`✅ [DELIVERY] Marked ${deliveredCount} papers as delivered`);
      }
      
    } catch (error) {
      console.error('❌ [DELIVERY] Error in delivery marking process:', error);
    }
  }

  // Cleanup old papers (keep only recent 7 days)
  async cleanupOldPapers() {
    try {
      const cutoffDate = moment().tz(this.timezone)
        .subtract(this.retainDays, 'days')
        .format('YYYY-MM-DD');
      
      console.log(`🧹 [CLEANUP] Removing papers older than ${cutoffDate}`);
      
      const deletedCount = await PaperPosts.destroy({
        where: {
          paperDate: {
            [Op.lt]: cutoffDate
          }
        }
      });
      
      console.log(`✅ [CLEANUP] Removed ${deletedCount} old paper posts`);
      
    } catch (error) {
      console.error('❌ [CLEANUP] Error during cleanup:', error);
    }
  }

  // Manual trigger for testing
  async triggerManualGeneration() {
    console.log('🔧 [MANUAL] Triggering manual paper generation...');
    await this.processPaperGeneration();
  }
  // Get scheduler status
  getStatus() {
    return {
      isRunning: this.isRunning,
      cronJobScheduled: !!this.cronJob,
      deliveryJobScheduled: !!this.deliveryJob,
      cleanupJobScheduled: !!this.cleanupJob,
      timezone: this.timezone,
      retainDays: this.retainDays,
      schedule: {
        paperGeneration: 'Every hour at 55 minutes',
        paperDelivery: 'Every hour at 01 minutes',
        cleanup: 'Daily at 2:00 AM'
      }
    };
  }
}

// Export singleton instance
module.exports = new PaperScheduler();
