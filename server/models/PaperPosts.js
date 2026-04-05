const moment = require('moment-timezone');
const { convertTo24Hour, getCronExpression: getDeliveryCronExpression } = require('../utils/timeConverter');

module.exports = (sequelize, DataTypes) => {
  const PaperPosts = sequelize.define("PaperPosts", {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    paperId: {
      type: DataTypes.STRING,
      allowNull: false,
      references: {
        model: 'Papers',
        key: 'id'
      }
    },
    paperDate: {
      type: DataTypes.DATEONLY, // Format: YYYY-MM-DD
      allowNull: false,
      comment: 'The date for which this paper edition was created'
    },
     deleted : {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    deliveryTime: {
      type: DataTypes.STRING,
      allowNull: false,
      comment: 'Time when this paper was delivered (e.g., "10:00")'
    },
    posts: {
      type: DataTypes.JSON,
      allowNull: false,
      comment: 'Array of post IDs in rank order [postId1, postId2, postId3, ...]'
    },
    timezone: {
      type: DataTypes.STRING,
      allowNull: false,
      defaultValue: 'Asia/Kolkata',
      comment: 'Timezone for the paper delivery (IST by default)'
    },    status: {
      type: DataTypes.ENUM('scheduled', 'delivered', 'failed'),
      defaultValue: 'scheduled',
      comment: 'Status of the paper post delivery'
    },
    read: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
      allowNull: false,
      comment: 'Whether the user has read this paper'
    },
  }, {
    tableName: 'PaperPosts',
    timestamps: true, // createdAt and updatedAt
    indexes: [
      // Unique index to prevent duplicates for same paper and date (one record per paper per day)
      {
        unique: true,
        fields: ['paperId', 'paperDate'],
        name: 'unique_paper_date'
      },
      // Index for querying by date only
      {
        fields: ['paperDate'],
        name: 'paper_date_only_index'
      },
      // Index for querying by delivery time
      {
        fields: ['deliveryTime'],
        name: 'delivery_time_index'
      },
      // Index for status queries
      {
        fields: ['status'],
        name: 'status_index'
      }
    ],
    validate: {
      // Validate posts array
      validPostsArray() {
        if (!Array.isArray(this.posts)) {
          throw new Error('Posts must be an array');
        }
        if (this.posts.length === 0) {
          throw new Error('Posts array cannot be empty');
        }
      }
    }
  });
  // Define associations
  PaperPosts.associate = function(models) {
    // Belongs to Paper
    PaperPosts.belongsTo(models.Papers, {
      foreignKey: 'paperId',
      as: 'paper',
      onDelete: 'CASCADE'
    });
    
    // Note: No direct relationship to Post model since posts are stored as JSON array
    // Posts will be fetched separately using the IDs in the posts array
  };
  // Instance methods
  PaperPosts.prototype.toJSON = function() {
    const values = { ...this.get() };
    
    // Format dates for IST display
    if (values.paperDate) {
      values.paperDateIST = new Date(values.paperDate).toLocaleDateString('en-IN', {
        timeZone: 'Asia/Kolkata',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
    }
    
    return values;
  };

  // Static methods for common operations
  PaperPosts.findByPaperAndDate = async function(paperId, date) {
    return await this.findOne({
      where: {
        paperId: paperId,
        paperDate: date
      },
      include: [
        {
          model: this.sequelize.models.Papers,
          as: 'paper'
        }
      ]
    });
  };

  // Method to create or update paper posts for a given date
  PaperPosts.createOrUpdatePaperPosts = async function(paperId, date, postIds, deliveryTime, transaction = null) {
    const paperPosts = await this.findOne({
      where: {
        paperId: paperId,
        paperDate: date
      },
      transaction
    });

    if (paperPosts) {
      // Update existing record
      return await paperPosts.update({
        posts: postIds,
        deliveryTime: deliveryTime,
        status: 'scheduled'
      }, { transaction });
    } else {
      // Create new record
      return await this.create({
        paperId: paperId,
        paperDate: date,
        posts: postIds,
        deliveryTime: deliveryTime,
        status: 'scheduled'
      }, { transaction });
    }
  };

  // Method to get posts with full Post data
  PaperPosts.getPaperWithPosts = async function(paperId, date) {
    const paperPosts = await this.findByPaperAndDate(paperId, date);
    
    if (!paperPosts || !paperPosts.posts || paperPosts.posts.length === 0) {
      return null;
    }

    // Fetch the actual Post records using the IDs
    const { Post, Users } = this.sequelize.models;
    const posts = await Post.findAll({
      where: {
        id: { [this.sequelize.Sequelize.Op.in]: paperPosts.posts }
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'verified']
      }],
      // Maintain the order from the posts array
      order: [
        [this.sequelize.Sequelize.fn('FIELD', this.sequelize.Sequelize.col('Post.id'), ...paperPosts.posts)]
      ]
    });

    return {
      ...paperPosts.get({ plain: true }),
      postsData: posts
    };
  };
  // Method to get paper history with date grouping
  PaperPosts.getPaperHistory = async function(paperId, startDate = null, endDate = null) {
    const whereClause = { paperId: paperId };
    
    if (startDate && endDate) {
      whereClause.paperDate = {
        [this.sequelize.Sequelize.Op.between]: [startDate, endDate]
      };
    } else if (startDate) {
      whereClause.paperDate = {
        [this.sequelize.Sequelize.Op.gte]: startDate
      };
    } else if (endDate) {
      whereClause.paperDate = {
        [this.sequelize.Sequelize.Op.lte]: endDate
      };
    }

    return await this.findAll({
      where: whereClause,
      order: [['paperDate', 'DESC']],
      include: [
        {
          model: this.sequelize.models.Papers,
          as: 'paper'
        }
      ]
    });
  };

  // Method to bulk create paper posts (updated for new structure)
  PaperPosts.bulkCreatePaperPosts = async function(paperPostsData, transaction = null) {
    try {
      const result = await this.bulkCreate(paperPostsData, {
        transaction,
        updateOnDuplicate: ['posts', 'deliveryTime', 'status'], // Update if duplicate paperId+paperDate
        returning: true
      });
      return result;
    } catch (error) {
      console.error('Error in bulk creating paper posts:', error);
      throw error;
    }
  };

  // Method to get today's paper posts for IST timezone
  PaperPosts.getTodaysPaper = async function(paperId, timezone = 'Asia/Kolkata') {
    const todayIST = moment().tz(timezone).format('YYYY-MM-DD');
    
    return await this.findByPaperAndDate(paperId, todayIST);
  };

  // Method to check if paper already exists for today
  PaperPosts.hasTodaysPaper = async function(paperId, timezone = 'Asia/Kolkata') {
    const todayIST = moment().tz(timezone).format('YYYY-MM-DD');
    
    const count = await this.count({
      where: {
        paperId: paperId,
        paperDate: todayIST
      }
    });
    
    return count > 0;
  };  // Method to get next delivery time for a paper (useful for node-cron scheduling)
  PaperPosts.getNextDeliveryTime = function(deliveryTime, timezone = 'Asia/Kolkata') {
    const now = moment().tz(timezone);
    const { hour, minute } = convertTo24Hour(deliveryTime);
    
    let nextDelivery = moment().tz(timezone).hour(hour).minute(minute).second(0);
    
    // If the time has already passed today, schedule for tomorrow
    if (nextDelivery.isSameOrBefore(now)) {
      nextDelivery.add(1, 'day');
    }
    
    return nextDelivery.toDate();
  };  // Method to get cron expression for paper delivery (2 minutes before delivery time)
  PaperPosts.getCronExpression = function(deliveryTime, timezone = 'Asia/Kolkata') {
    return getDeliveryCronExpression(deliveryTime);
  };

  // Method to mark paper posts as delivered
  PaperPosts.markAsDelivered = async function(paperId, paperDate, transaction = null) {
    return await this.update(
      { status: 'delivered' },
      {
        where: {
          paperId: paperId,
          paperDate: paperDate
        },
        transaction
      }
    );
  };
  // Method to get posts ready for delivery
  PaperPosts.getPostsForDelivery = async function(paperId, deliveryTime, timezone = 'Asia/Kolkata') {
    const todayIST = moment().tz(timezone).format('YYYY-MM-DD');
    
    const paperPosts = await this.findOne({
      where: {
        paperId: paperId,
        paperDate: todayIST,
        deliveryTime: deliveryTime,
        status: 'scheduled'
      },
      include: [
        {
          model: this.sequelize.models.Papers,
          as: 'paper'
        }
      ]
    });

    if (!paperPosts || !paperPosts.posts || paperPosts.posts.length === 0) {
      return null;
    }

    // Fetch the actual Post records using the IDs from the posts array
    const { Post, Users } = this.sequelize.models;
    const posts = await Post.findAll({
      where: {
        id: { [this.sequelize.Sequelize.Op.in]: paperPosts.posts }
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'verified']
      }],
      // Maintain the order from the posts array
      order: [
        [this.sequelize.Sequelize.fn('FIELD', this.sequelize.Sequelize.col('Post.id'), ...paperPosts.posts)]
      ]
    });

    return {
      ...paperPosts.get({ plain: true }),
      postsData: posts
    };
  };
  // Method to clean up old paper posts (useful for maintenance)
  PaperPosts.cleanupOldPosts = async function(daysToKeep = 30, transaction = null) {
    const cutoffDate = moment().subtract(daysToKeep, 'days').format('YYYY-MM-DD');
    
    return await this.destroy({
      where: {
        paperDate: {
          [this.sequelize.Sequelize.Op.lt]: cutoffDate
        }
      },
      transaction
    });
  };

  // Method to get all papers that need cron jobs scheduled
  PaperPosts.getPapersForCronScheduling = async function() {
    const { Papers } = this.sequelize.models;
    return await Papers.findAll({
      where: {
        status: 'active'
      },
      attributes: ['id', 'deliveryTime', 'postCount', 'title']
    });
  };

  // Method to schedule paper generation for a specific date
  PaperPosts.schedulePaperGeneration = async function(paperId, targetDate, postIds, deliveryTime, transaction = null) {
    return await this.createOrUpdatePaperPosts(paperId, targetDate, postIds, deliveryTime, transaction);
  };
  // Method to get delivery schedule for all active papers
  PaperPosts.getDeliverySchedule = async function(timezone = 'Asia/Kolkata') {
    const { Papers } = this.sequelize.models;
    const activePapers = await Papers.findAll({
      where: { status: 'active' },
      attributes: ['id', 'title', 'deliveryTime', 'postCount']
    });    return activePapers.map(paper => ({
      paperId: paper.id,
      title: paper.title,
      deliveryTime: paper.deliveryTime,
      postCount: paper.postCount,
      cronExpression: this.getCronExpression(paper.deliveryTime, timezone),
      nextDelivery: this.getNextDeliveryTime(paper.deliveryTime, timezone)
    }));
  };

  // Method to mark paper as read for a specific user
  PaperPosts.markAsRead = async function(paperPostId, userId, transaction = null) {
    console.log(`🔍 [MODEL DEBUG] PaperPosts.markAsRead called:`, {
      paperPostId,
      userId,
      hasTransaction: !!transaction,
      timestamp: new Date().toISOString()
    });

    try {
      // First, check if the record exists and get current status
      const existingRecord = await this.findByPk(paperPostId, { transaction });
      console.log(`📄 [MODEL DEBUG] Existing record found:`, {
        exists: !!existingRecord,
        currentReadStatus: existingRecord?.read,
        paperDate: existingRecord?.paperDate,
        paperId: existingRecord?.paperId
      });

      if (!existingRecord) {
        console.log(`❌ [MODEL ERROR] PaperPost not found with ID: ${paperPostId}`);
        return false;
      }      // Perform the update
      const [updatedRowsCount] = await this.update(
        { read: true },
        {
          where: { id: paperPostId },
          transaction,
          validate: false
        }
      );

      console.log(`✅ [MODEL SUCCESS] Update completed:`, {
        paperPostId,
        updatedRowsCount,
        wasSuccessful: updatedRowsCount > 0
      });

      // Verify the update by re-fetching
      const verifyRecord = await this.findByPk(paperPostId, { transaction });
      console.log(`🔍 [MODEL VERIFY] Post-update verification:`, {
        paperPostId,
        beforeRead: existingRecord.read,
        afterRead: verifyRecord.read,
        updateConfirmed: verifyRecord.read === true,
        updatedAt: verifyRecord.updatedAt
      });

      return updatedRowsCount > 0;
    } catch (error) {
      console.error('❌ [MODEL ERROR] Error in markAsRead:', {
        paperPostId,
        userId,
        error: error.message,
        stack: error.stack,
        sqlMessage: error.original?.sqlMessage,
        sqlState: error.original?.sqlState
      });
      return false;
    }
  };
  // Method to mark paper as unread for a specific user
  PaperPosts.markAsUnread = async function(paperPostId, userId, transaction = null) {
    console.log(`🔍 [MODEL DEBUG] PaperPosts.markAsUnread called:`, {
      paperPostId,
      userId,
      hasTransaction: !!transaction,
      timestamp: new Date().toISOString()
    });

    try {
      // First, check if the record exists and get current status
      const existingRecord = await this.findByPk(paperPostId, { transaction });
      console.log(`📄 [MODEL DEBUG] Existing record found:`, {
        exists: !!existingRecord,
        currentReadStatus: existingRecord?.read,
        paperDate: existingRecord?.paperDate,
        paperId: existingRecord?.paperId
      });

      if (!existingRecord) {
        console.log(`❌ [MODEL ERROR] PaperPost not found with ID: ${paperPostId}`);
        return false;
      }      // Perform the update
      const [updatedRowsCount] = await this.update(
        { read: false },
        {
          where: { id: paperPostId },
          transaction,
          validate: false
        }
      );

      console.log(`✅ [MODEL SUCCESS] Unread update completed:`, {
        paperPostId,
        updatedRowsCount,
        wasSuccessful: updatedRowsCount > 0
      });

      // Verify the update by re-fetching
      const verifyRecord = await this.findByPk(paperPostId, { transaction });
      console.log(`🔍 [MODEL VERIFY] Post-unread-update verification:`, {
        paperPostId,
        beforeRead: existingRecord.read,
        afterRead: verifyRecord.read,
        updateConfirmed: verifyRecord.read === false,
        updatedAt: verifyRecord.updatedAt
      });

      return updatedRowsCount > 0;
    } catch (error) {
      console.error('❌ [MODEL ERROR] Error in markAsUnread:', {
        paperPostId,
        userId,
        error: error.message,
        stack: error.stack,
        sqlMessage: error.original?.sqlMessage,
        sqlState: error.original?.sqlState
      });
      return false;
    }
  };// Method to check if paper is read by a specific user
  PaperPosts.isReadByUser = function(paperPosts, userId) {
    return paperPosts.read || false;
  };

  // Method to get papers for MyPaper page with read/unread status and filtering
  PaperPosts.getPapersForUser = async function(userId, paperId, filterDate = null, timezone = 'Asia/Kolkata') {
    const whereClause = { paperId: paperId };
    
    if (filterDate) {
      if (filterDate === 'today') {
        whereClause.paperDate = moment().tz(timezone).format('YYYY-MM-DD');
      } else if (filterDate === 'yesterday') {
        whereClause.paperDate = moment().tz(timezone).subtract(1, 'day').format('YYYY-MM-DD');
      } else {
        // Specific date provided
        whereClause.paperDate = filterDate;
      }
    }

    const papers = await this.findAll({
      where: whereClause,
      include: [
        {
          model: this.sequelize.models.Papers,
          as: 'paper',
          attributes: ['id', 'title', 'description']
        }
      ],      order: [['paperDate', 'DESC'], ['deliveryTime', 'DESC']]
    });    // Add read status and sort by read/unread priority
    const papersWithReadStatus = papers.map(paper => {
      const plainPaper = paper.get({ plain: true });
      plainPaper.isRead = plainPaper.read || false; // Use actual read field
      plainPaper.readAt = plainPaper.read ? plainPaper.updatedAt : null; // Use updatedAt as readAt if read
      return plainPaper;
    });

    // Sort: Unread first, then read, with time as secondary sort
    papersWithReadStatus.sort((a, b) => {
      // Primary sort: unread papers first
      if (a.isRead !== b.isRead) {
        return a.isRead ? 1 : -1; // unread (false) comes before read (true)
      }
      
      // Secondary sort: by date and time (most recent first)
      const dateA = new Date(a.paperDate + ' ' + a.deliveryTime);
      const dateB = new Date(b.paperDate + ' ' + b.deliveryTime);
      return dateB - dateA;
    });

    return papersWithReadStatus;
  };
  // Method to get papers with date range for "More" filter
  PaperPosts.getPapersByDateRange = async function(userId, paperId, startDate, endDate, timezone = 'Asia/Kolkata') {
    const papers = await this.findAll({
      where: {
        paperId: paperId,
        paperDate: {
          [this.sequelize.Sequelize.Op.between]: [startDate, endDate]
        }
      },
      include: [
        {
          model: this.sequelize.models.Papers,
          as: 'paper',
          attributes: ['id', 'title', 'description']
        }
      ],
      order: [['paperDate', 'DESC'], ['deliveryTime', 'DESC']]
    });    // Add read status and sort by read/unread priority
    const papersWithReadStatus = papers.map(paper => {
      const plainPaper = paper.get({ plain: true });
      plainPaper.isRead = plainPaper.read || false; // Use actual read field
      plainPaper.readAt = plainPaper.read ? plainPaper.updatedAt : null; // Use updatedAt as readAt if read
      return plainPaper;
    });

    // Sort: Unread first, then read, with time as secondary sort
    papersWithReadStatus.sort((a, b) => {
      if (a.isRead !== b.isRead) {
        return a.isRead ? 1 : -1;
      }
      const dateA = new Date(a.paperDate + ' ' + a.deliveryTime);
      const dateB = new Date(b.paperDate + ' ' + b.deliveryTime);
      return dateB - dateA;
    });    return papersWithReadStatus;
  };  // Method to get user read status for a specific paper
  PaperPosts.getUserReadStatus = async function(paperPostId, userId) {
    try {
      const paperPost = await this.findByPk(paperPostId);
      return paperPost ? paperPost.read || false : false;
    } catch (error) {
      console.error('Error getting user read status:', error);
      return false;
    }  };
  // Method to get posts with full Post data (simplified - using paperPost ID)
  PaperPosts.getPaperWithPosts = async function(paperPostId) {
    const paperPost = await this.findByPk(paperPostId);
    
    if (!paperPost || !paperPost.posts || paperPost.posts.length === 0) {
      return [];
    }

    // Fetch the actual Post records using the IDs
    const { Post, Users } = this.sequelize.models;
    const posts = await Post.findAll({
      where: {
        id: { [this.sequelize.Sequelize.Op.in]: paperPost.posts }
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'verified']
      }],
      // Maintain the order from the posts array
      order: [
        [this.sequelize.Sequelize.fn('FIELD', this.sequelize.Sequelize.col('Post.id'), ...paperPost.posts)]
      ]
    });

    return posts;
  };

  // Method to get today's paper (without paperId parameter)
  PaperPosts.getTodaysPaper = async function(timezone = 'Asia/Kolkata') {
    const todayIST = moment().tz(timezone).format('YYYY-MM-DD');
    
    return await this.findOne({
      where: {
        paperDate: todayIST
      },
      include: [
        {
          model: this.sequelize.models.Papers,
          as: 'paper'
        }
      ],
      order: [['createdAt', 'DESC']]
    });
  };

  // Method to get posts with full details by paperPost ID (for the new endpoint)
  PaperPosts.getPaperPostsWithDetails = async function(paperPostId) {
    const paperPost = await this.findByPk(paperPostId);
    
    if (!paperPost || !paperPost.posts || paperPost.posts.length === 0) {
      return [];
    }

    // Fetch the actual Post records using the IDs
    const { Post, Users } = this.sequelize.models;
    const posts = await Post.findAll({
      where: {
        id: { [this.sequelize.Sequelize.Op.in]: paperPost.posts }
      },
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username', 'profilePicture', 'firstName', 'lastName', 'verified', 'state']
      }],
      // Maintain the order from the posts array
      order: [
        [this.sequelize.Sequelize.fn('FIELD', this.sequelize.Sequelize.col('Post.id'), ...paperPost.posts)]
      ]
    });

    // Format response with full post data
    return posts.map(post => {
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
        shares: plainPost.shared,
        bookmarks: plainPost.bookmarks,
        createdAt: plainPost.createdAt,
        updatedAt: plainPost.updatedAt,
        category: plainPost.category || plainPost.categories,
        isShort: plainPost.isShort,
        author: {
          id: plainPost.author.id,
          username: plainPost.author.username,
          profilePicture: plainPost.author.profilePicture,
          fullName: (plainPost.author.firstName || '') + ' ' + (plainPost.author.lastName || ''),
          verified: plainPost.author.verified,
          state: plainPost.author.state
        }
      };
    });
  };
  // Method to mark scheduled papers as delivered when their time comes
  PaperPosts.markScheduledAsDelivered = async function(timezone = 'Asia/Kolkata') {
    const currentIST = moment().tz(timezone);
    const currentHour = currentIST.hour();
    const currentMinute = currentIST.minute();
    const todayDate = currentIST.format('YYYY-MM-DD');
    
    // Only mark as delivered if we're past the delivery minute (allow 1 minute buffer)
    if (currentMinute < 1) {
      return 0; // Too early, wait for next check
    }
    
    try {
      // Find all scheduled papers that should now be marked as delivered
      const papersToDeliver = await this.findAll({
        where: {
          status: 'scheduled',
          paperDate: todayDate // Only check today's papers
        },
        include: [{
          model: this.sequelize.models.Papers,
          as: 'paper',
          attributes: ['deliveryTime']
        }]
      });
      
      let deliveredCount = 0;
      
      for (const paperPost of papersToDeliver) {
        // Parse delivery time (e.g., "12:00 AM", "10:00 PM")
        const [time, period] = paperPost.paper.deliveryTime.split(' ');
        const [hour, minute] = time.split(':').map(Number);
        
        let deliveryHour = hour;
        if (period === 'PM' && hour !== 12) {
          deliveryHour = hour + 12;
        } else if (period === 'AM' && hour === 12) {
          deliveryHour = 0;
        }
        
        console.log(`🕐 [DELIVERY DEBUG] Paper ${paperPost.id}: Delivery time ${paperPost.paper.deliveryTime} -> ${deliveryHour}:${minute.toString().padStart(2, '0')}, Current: ${currentHour}:${currentMinute.toString().padStart(2, '0')}`);
          // Check if current time is past delivery time
        // For midnight (00:00), make sure we don't deliver during the day
        if (deliveryHour === 0 && currentHour > 1) {
          // Don't deliver 12:00 AM papers during daytime hours (after 1 AM)
          console.log(`📬 [DELIVERY] Skipping midnight paper delivery during day: ${paperPost.id} at ${currentIST.format('HH:mm')}`);
          continue;
        }
        
        if (currentHour > deliveryHour || (currentHour === deliveryHour && currentMinute >= minute)) {
          await paperPost.update({
            status: 'delivered'
          });
          deliveredCount++;
          
          console.log(`📬 [DELIVERY] Marked paper as delivered: ${paperPost.id} at ${currentIST.format('HH:mm')}`);
        }
      }
      
      return deliveredCount;
      
    } catch (error) {
      console.error('❌ [DELIVERY] Error marking papers as delivered:', error);
      throw error;
    }
  };

  return PaperPosts;
};