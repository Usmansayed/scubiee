const express = require("express");
const router = express.Router();
const { validateToken } = require("../middlewares/AuthMiddleware");
const { Post, PostLike, PostSaved, UserReports, Recommendations, Notifications, UserInteractions, sequelize, Comment, Follow, Users, CommentLike, PostView } = require("../models");
const { Op } = require("sequelize");

router.post("/like/:postId", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { postId } = req.params;
    const userId = req.user.id;
    const { action } = req.body;

    const likeAction = action === "unlike" ? "unlike" : "like";

    const existingLike = await PostLike.findOne({
      where: { userId, postId },
      transaction: t
    });

    if (likeAction === "like") {
      if (existingLike) {
        await existingLike.update({
          updatedAt: new Date()
        }, { transaction: t });
      } else {
        await PostLike.create({
          userId,
          postId
        }, { transaction: t });

        await Post.increment('likes', {
          by: 1,
          where: { id: postId },
          transaction: t
        });

        const post = await Post.findByPk(postId, {
          attributes: ['authorId', 'isShort'],
          transaction: t
        });

        if (post && post.authorId !== userId) {
          const sender = await Users.findByPk(userId, {
            attributes: ['id', 'username', 'profilePicture', 'Verified'],
            transaction: t
          });

          await Notifications.create({
            user_id: post.authorId,
            sender_id: userId,
            type: 'like',
            reference_id: postId,
            reference_type: 'post',
            post_id: postId,
            message: 'liked your post',
            is_read: false
          }, { transaction: t });

          const isShort = post.isShort || false;

          if (req.io) {
            req.io.to(post.authorId.toString()).emit('notification', {
              type: 'like',
              senderId: userId,
              postId: postId,
              referenceId: postId,
              referenceType: 'post',
              isShort: isShort,
              message: 'liked your post',
              sender: sender ? sender.toJSON() : null,
              timestamp: new Date().toISOString()
            });
          }
        }
      }
    } else {
      if (existingLike) {
        await existingLike.destroy({ transaction: t });
        
        await Post.decrement('likes', {
          by: 1,
          where: { id: postId },
          transaction: t
        });

        const post = await Post.findByPk(postId, {
          attributes: ['authorId'],
          transaction: t
        });

        if (post) {
          await Notifications.destroy({
            where: {
              sender_id: userId,
              user_id: post.authorId,
              type: 'like',
              reference_id: postId,
              reference_type: 'post'
            },
            transaction: t
          });

          if (req.io) {
            req.io.to(post.authorId.toString()).emit('notification_remove', {
              type: 'like',
              senderId: userId,
              postId: postId
            });
          }
        }
      }
    }

    await UserInteractions.upsert({
      userId,
      postId,
      interactionType: 'liked',
      updatedAt: new Date()
    }, { transaction: t });

    const updatedPost = await Post.findByPk(postId, { transaction: t });

    await t.commit();
    res.json({
      success: true,
      action: likeAction,
      likesCount: updatedPost.likes
    });

  } catch (error) {
    await t.rollback();
    next(error);
  }
});
router.post("/view/:postId", validateToken, async (req, res, next) => {
  const userId = req.user.id;
  const { postId } = req.params;

  try {
    const [postView, created] = await PostView.findOrCreate({
      where: { userId, postId },
      defaults: { userId, postId }
    });

    if (created) {
      await Post.increment('views', {
        by: 1,
        where: { id: postId }
      });

      await UserInteractions.create({
        userId,
        postId,
        interactionType: 'read'
      });
    }

    res.status(200).send({
      success: true,
      newView: created
    });
  } catch (error) {
    next(error);
  }
});

router.post("/save/:postId", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { postId } = req.params;
    const userId = req.user.id;
    const { action } = req.body;

    const saveAction = action === "unsave" ? "unsave" : "save";

    const existingSave = await PostSaved.findOne({
      where: { userId, postId },
      transaction: t
    });

    if (saveAction === "save") {
      if (existingSave) {
        await existingSave.update({
          updatedAt: new Date()
        }, { transaction: t });
      } else {
        await PostSaved.create({
          userId,
          postId
        }, { transaction: t });

        await Post.increment('bookmarks', {
          by: 1,
          where: { id: postId },
          transaction: t
        });
      }
    } else {
      if (existingSave) {
        await existingSave.destroy({ transaction: t });

        await Post.decrement('bookmarks', {
          by: 1,
          where: {
            id: postId,
            bookmarks: { [Op.gt]: 0 }
          },
          transaction: t
        });
      }
    }

    await UserInteractions.upsert({
      userId,
      postId,
      interactionType: 'saved',
      updatedAt: new Date()
    }, { transaction: t });

    await t.commit();
    res.json({
      success: true,
      action: saveAction
    });
  } catch (error) {
    await t.rollback();
    next(error);
  }
});

router.post("/share/:postId", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { postId } = req.params;
    const userId = req.user.id;

    await Post.increment('shared', { by: 1, where: { id: postId }, transaction: t });
    await UserInteractions.create({
      userId,
      postId,
      interactionType: 'shared'
    }, { transaction: t });

    await t.commit();
    res.json({ success: true });
  } catch (error) {
    await t.rollback();
    next(error);
  }
});

router.post("/report/:postId", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { postId } = req.params;
    const { reason } = req.body;
    const userId = req.user.id;

    await UserReports.create({ userId, postId, reason }, { transaction: t });
    await UserInteractions.create({
      userId,
      postId,
      interactionType: 'reported'
    }, { transaction: t });

    await t.commit();
    res.json({ success: true });
  } catch (error) {
    await t.rollback();
    next(error);
  }
});

router.post("/recommend/:postId", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { postId } = req.params;
    const userId = req.user.id;

    await Recommendations.create({ userId, postId }, { transaction: t });
    await Post.increment('recommendedby', { by: 1, where: { id: postId }, transaction: t });
    await UserInteractions.create({
      userId,
      postId,
      interactionType: 'recommended'
    }, { transaction: t });

    await t.commit();
    res.json({ success: true });
  } catch (error) {
    await t.rollback();
    next(error);
  }
});

router.post("/comment", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { postId, content, parentId, replyingto } = req.body;
    const authorId = req.user.id;

    if (parentId) {
      const parentComment = await Comment.findOne({ where: { id: parentId }, transaction: t });
      if (!parentComment) {
        await t.rollback();
        return res.status(404).json({ error: "Parent comment not found" });
      }
    }

    const newComment = await Comment.create(
      { postId, authorId, content, parentId, replyingto },
      { transaction: t }
    );

    await Post.increment('comments', {
      by: 1,
      where: { id: postId },
      transaction: t
    });

    let notificationType, notificationRecipient, notificationMessage, referenceType, referenceId;

    if (parentId) {
      const parentComment = await Comment.findByPk(parentId, {
        attributes: ['authorId', 'id', 'postId'],
        transaction: t
      });

      if (parentComment && parentComment.authorId !== authorId) {
        notificationType = 'reply';
        notificationRecipient = parentComment.authorId;
        notificationMessage = 'replied to your comment';
        referenceType = 'comment';
        referenceId = newComment.id;

        const post = await Post.findByPk(postId, {
          attributes: ['isShort'],
          transaction: t
        });

        const isShort = post ? !!post.isShort : false;

        await Notifications.create({
          user_id: notificationRecipient,
          sender_id: authorId,
          type: notificationType,
          reference_id: referenceId,
          reference_type: referenceType,
          post_id: postId,
          message: notificationMessage,
          is_read: false
        }, { transaction: t });

        const sender = await Users.findByPk(authorId, {
          attributes: ['id', 'username', 'profilePicture', 'Verified'],
          transaction: t
        });

        if (req.io) {
          req.io.to(notificationRecipient.toString()).emit('notification', {
            type: notificationType,
            senderId: authorId,
            sender_id: authorId,
            user_id: notificationRecipient,
            referenceId: referenceId,
            reference_id: referenceId,
            referenceType: referenceType,
            reference_type: referenceType,
            postId: postId,
            post_id: postId,
            isShort: isShort,
            message: notificationMessage,
            sender: sender ? sender.toJSON() : null,
            timestamp: new Date().toISOString()
          });
        }
      }
    } else {
      const post = await Post.findByPk(postId, {
        attributes: ['authorId', 'isShort'],
        transaction: t
      });

      if (post && post.authorId !== authorId) {
        notificationType = 'comment';
        notificationRecipient = post.authorId;
        notificationMessage = 'commented on your post';
        referenceType = 'comment';
        referenceId = newComment.id;

        const isShort = !!post.isShort;

        await Notifications.create({
          user_id: notificationRecipient,
          sender_id: authorId,
          type: notificationType,
          reference_id: referenceId,
          reference_type: referenceType,
          post_id: postId,
          message: notificationMessage,
          is_read: false
        }, { transaction: t });

        const sender = await Users.findByPk(authorId, {
          attributes: ['id', 'username', 'profilePicture', 'Verified'],
          transaction: t
        });

        if (req.io) {
          req.io.to(notificationRecipient.toString()).emit('notification', {
            type: notificationType,
            senderId: authorId,
            sender_id: authorId,
            user_id: notificationRecipient,
            referenceId: referenceId,
            reference_id: referenceId,
            referenceType: referenceType,
            reference_type: referenceType,
            postId: postId,
            post_id: postId,
            isShort: isShort,
            message: notificationMessage,
            sender: sender ? sender.toJSON() : null,
            timestamp: new Date().toISOString()
          });
        }
      }
    }

    const completeComment = await Comment.findOne({
      where: { id: newComment.id },
      include: [{
        model: Users,
        as: 'User', // Changed from 'user' to 'User' to match the model association
        attributes: ['id', 'username', 'profilePicture']
      }],
      transaction: t
    });

    await t.commit();

    res.json({
      success: true,
      commentId: newComment.id,
      comment: completeComment
    });
  } catch (error) {
    if (t && !t.finished) {
      await t.rollback();
    }
    next(error);
  }
});

router.delete("/comment/:commentId", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { commentId } = req.params;
    const userId = req.user.id;

    const comment = await Comment.findByPk(commentId, {
      transaction: t
    });

    if (!comment) {
      await t.rollback();
      return res.status(404).json({ error: "Comment not found" });
    }

    if (comment.authorId !== userId) {
      await t.rollback();
      return res.status(403).json({ error: "You can only delete your own comments" });
    }

    const postId = comment.postId;
    const parentId = comment.parentId;

    let replyCount = 0;
    if (!parentId) {
      replyCount = await Comment.count({
        where: { parentId: commentId },
        transaction: t
      });
    }

    await comment.destroy({ transaction: t });

    await Notifications.destroy({
      where: {
        reference_id: commentId,
        reference_type: 'comment'
      },
      transaction: t
    });

    if (!parentId) {
      await Post.decrement('comments', {
        by: 1 + replyCount,
        where: { id: postId },
        transaction: t
      });

      await Comment.destroy({
        where: { parentId: commentId },
        transaction: t
      });
    } else {
      await Post.decrement('comments', {
        by: 1,
        where: { id: postId },
        transaction: t
      });
    }

    await t.commit();
    res.json({
      success: true,
      message: "Comment deleted successfully",
      commentId,
      parentId,
      wasParent: !parentId,
      replyCount
    });
  } catch (error) {
    await t.rollback();
    next(error);
  }
});

router.get("/c/:postId", validateToken, async (req, res, next) => {
  try {
    const { postId } = req.params;
    const userId = req.user.id;
    const parentId = req.query.commentId || null;
    const { limit, skipIds, beforeTimestamp, afterTimestamp, targetCommentId, fromNotification, fetchDirection } = req.query;

    const skipArray = skipIds ? skipIds.split(',').filter(id => id) : [];

    const limitValue = parentId ? parseInt(limit) || 8 : parseInt(limit) || 12;

    const isNotificationView = fromNotification === 'true';

    if (targetCommentId) {
      return await handleTargetCommentView(
        postId, targetCommentId, userId, isNotificationView, parseInt(limit) || 12, res
      );
    }

    if (parentId) {
      return await handleRepliesFetch(
        postId, parentId, userId, skipArray, beforeTimestamp, afterTimestamp,
        fetchDirection, limitValue, res
      );
    }

    const whereClause = { postId, parentId: null };

    if (beforeTimestamp) {
      const lastDate = new Date(beforeTimestamp);
      if (!isNaN(lastDate.getTime())) {
        whereClause.createdAt = { [Op.lt]: lastDate };
      }
    }

    if (skipArray.length > 0) {
      whereClause.id = { [Op.notIn]: skipArray };
    }

    const comments = await Comment.findAll({
      where: whereClause,
      order: [["createdAt", "DESC"]],
      limit: limitValue
    });

    let hasMore = false;
    if (comments.length > 0) {
      const oldestCommentInBatch = comments[comments.length - 1];

      const remainingOlderComments = await Comment.count({
        where: {
          postId,
          parentId: null,
          createdAt: { [Op.lt]: oldestCommentInBatch.createdAt }
        }
      });

      hasMore = remainingOlderComments > 0;
    }

    const oldestCommentTimestamp = comments.length > 0
      ? new Date(comments[comments.length - 1].createdAt).toISOString()
      : null;

    const commentIds = comments.map(c => c.id);
    let likedCommentIds = new Set();

    if (commentIds.length > 0) {
      const userLikes = await CommentLike.findAll({
        where: { userId, commentId: commentIds }
      });

      likedCommentIds = new Set(userLikes.map(like => like.commentId));
    }

    const commentsWithUserDetails = await Promise.all(
      comments.map(async (comment) => {
        const user = await Users.findByPk(comment.authorId, {
          attributes: ["id", "username", "profilePicture"]
        });

        const repliesCount = await Comment.count({
          where: { parentId: comment.id }
        });

        return {
          ...comment.toJSON(),
          user,
          replies: repliesCount,
          userLiked: likedCommentIds.has(comment.id)
        };
      })
    );

    const total = await Comment.count({ where: { postId, parentId: null } });

    const paginationInfo = {
      total,
      hasMore,
      oldestCommentTimestamp,
      loadedIds: comments.map(comment => comment.id.toString())
    };

    return res.json({
      comments: commentsWithUserDetails,
      pagination: paginationInfo
    });
  } catch (error) {
    next(error);
  }
});

router.get("/notifications", validateToken, async (req, res, next) => {
  try {
    const userId = req.user.id;
    const page = parseInt(req.query.page) || 1;
    const limit = page === 1 ? 30 : 16;
    const offset = page === 1 ? 0 : 30 + ((page - 2) * 16);

    const total = await Notifications.count({
      where: { user_id: userId }
    });

    const notifications = await Notifications.findAll({
      where: { user_id: userId },
      order: [['createdAt', 'DESC']],
      limit,
      offset,
      include: [{
        model: Users,
        as: 'sender',
        attributes: ['id', 'username', 'profilePicture']
      }]
    });

    const processedNotifications = [];

    for (const notification of notifications) {
      const notificationData = notification.toJSON();
      let isValid = true;

      if (['comment', 'comment_like', 'reply', 'reply_like'].includes(notificationData.type) &&
        !notificationData.post_id &&
        notificationData.reference_id) {

        try {
          const comment = await Comment.findByPk(notificationData.reference_id, {
            attributes: ['postId']
          });

          if (comment && comment.postId) {
            notificationData.post_id = comment.postId;

            await Notifications.update(
              { post_id: comment.postId },
              { where: { id: notification.id } }
            );
          } else {
            isValid = false;
          }
        } catch (err) {
          isValid = false;
        }
      }

      if (notificationData.type === 'like' && !notificationData.post_id) {
        notificationData.post_id = notificationData.reference_id;
      }

      if (isValid && notificationData.post_id) {
        try {
          const post = await Post.findByPk(notificationData.post_id);
          if (!post) {
            isValid = false;
          }
        } catch (err) {
          isValid = false;
        }
      }

      if (isValid) {
        try {
          if (notificationData.reference_type === 'post') {
            const post = await Post.findByPk(notificationData.reference_id, {
              attributes: ['isShort']
            });

            if (!post) {
              isValid = false;
            } else {
              notificationData.isShort = !!post.isShort;
            }
          } else if (notificationData.reference_type === 'comment') {
            let postId = notificationData.post_id;

            if (!postId) {
              const comment = await Comment.findByPk(notificationData.reference_id, {
                attributes: ['postId']
              });
              postId = comment ? comment.postId : null;
            }

            if (postId) {
              const post = await Post.findByPk(postId, {
                attributes: ['isShort']
              });

              if (!post) {
                isValid = false;
              } else {
                notificationData.isShort = !!post.isShort;
              }
            } else {
              isValid = false;
            }
          } else {
            notificationData.isShort = false;
          }
        } catch (err) {
          isValid = false;
        }
      }

      if (isValid) {
        processedNotifications.push(notificationData);
      } else {
        try {
          await Notifications.destroy({ where: { id: notification.id } });
        } catch (deleteErr) {
        }
      }
    }

    res.json({
      notifications: processedNotifications || [],
      pagination: {
        total,
        page,
        limit,
        hasMore: offset + processedNotifications.length < total
      }
    });
  } catch (error) {
    next(error);
  }
});

router.post("/comment/:commentId/action", validateToken, async (req, res, next) => {
  const t = await sequelize.transaction();
  try {
    const { commentId } = req.params;
    const { action } = req.body;
    const userId = req.user.id;

    const comment = await Comment.findByPk(commentId, {
      include: [{ model: Post, attributes: ['id'] }],
      transaction: t
    });

    if (!comment) {
      await t.rollback();
      return res.status(404).json({ error: "Comment not found" });
    }

    if (action === "report" && comment.authorId === userId) {
      await t.rollback();
      return res.status(403).json({ error: "You cannot report your own comment" });
    }

    if (action === "like") {
      const existingLike = await CommentLike.findOne({
        where: { userId, commentId },
        transaction: t
      });

      if (!existingLike) {
        await CommentLike.create({ userId, commentId }, { transaction: t });
        comment.likes += 1;
        await comment.save({ transaction: t });

        if (comment.authorId !== userId) {
          const isReply = comment.parentId !== null;
          const notificationType = isReply ? 'reply_like' : 'comment_like';
          const notificationMessage = isReply ? 'liked your reply' : 'liked your comment';

          const post = await Post.findOne({
            where: { id: comment.postId || comment.Post?.id },
            attributes: ['isShort'],
            transaction: t
          });

          const isShort = post ? !!post.isShort : false;

          await Notifications.create({
            user_id: comment.authorId,
            sender_id: userId,
            type: notificationType,
            reference_id: commentId,
            reference_type: 'comment',
            post_id: comment.postId || comment.Post?.id,
            message: notificationMessage,
            is_read: false
          }, { transaction: t });

          if (req.io && req.io.emitWithSender) {
            req.io.emitWithSender('notification', comment.authorId, {
              type: notificationType,
              senderId: userId,
              commentId: commentId,
              postId: comment.postId || comment.Post?.id,
              isShort: isShort,
              message: notificationMessage,
              timestamp: new Date().toISOString()
            }, Users);
          }
        }

        await UserInteractions.upsert({
          userId,
          postId: comment.postId,
          interactionType: 'liked',
          updatedAt: new Date()
        }, { transaction: t });
      }

      await t.commit();
      return res.json({
        success: true,
        liked: true,
        likesCount: comment.likes,
        message: "Comment liked successfully"
      });

    } else if (action === "remove-like") {
      const existingLike = await CommentLike.findOne({
        where: { userId, commentId },
        transaction: t
      });

      if (existingLike) {
        await existingLike.destroy({ transaction: t });
        comment.likes -= 1;
        await comment.save({ transaction: t });

        const isReply = comment.parentId !== null;
        const notificationType = isReply ? 'reply_like' : 'comment_like';

        await Notifications.destroy({
          where: {
            sender_id: userId,
            user_id: comment.authorId,
            type: notificationType,
            reference_id: commentId,
            reference_type: 'comment'
          },
          transaction: t
        });

        if (req.io) {
          req.io.to(comment.authorId.toString()).emit('notification_remove', {
            type: notificationType,
            senderId: userId,
            commentId: commentId
          });
        }
      }

      await t.commit();
      return res.json({
        success: true,
        liked: false,
        likesCount: comment.likes,
        message: "Like removed successfully"
      });

    } else if (action === "report") {
      const ReportModel = sequelize.models.Report || UserReports;

      await ReportModel.create({
        userId,
        commentId,
        reportedBy: userId,
        targetId: commentId,
        reporting: 'comment',
        reason: req.body.reason || 'Reported content'
      }, { transaction: t });

      await t.commit();
      return res.json({ success: true, message: "Comment reported successfully" });
    } else {
      await t.rollback();
      return res.status(400).json({ error: "Invalid action" });
    }
  } catch (error) {
    await t.rollback();
    next(error);
  }
});

router.post("/report", validateToken, async (req, res, next) => {
  try {
    const { reporting, target_id, reason } = req.body;
    const userId = req.user.id;

    if (!reporting || !target_id || !reason) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    if (!['post', 'comment', 'user'].includes(reporting)) {
      return res.status(400).json({ error: "Invalid report type" });
    }

    if (reporting === 'post') {
      const post = await Post.findByPk(target_id, { attributes: ['authorId'] });
      if (post && post.authorId === userId) {
        return res.status(403).json({
          error: "You cannot report your own post"
        });
      }
    } else if (reporting === 'comment') {
      const comment = await Comment.findByPk(target_id, { attributes: ['authorId'] });
      if (comment && comment.authorId === userId) {
        return res.status(403).json({
          error: "You cannot report your own comment"
        });
      }
    } else if (reporting === 'user' && target_id === userId) {
      return res.status(403).json({
        error: "You cannot report yourself"
      });
    }

    const existingReport = await UserReports.findOne({
      where: {
        userId,
        targetId: target_id,
        reporting
      }
    });

    if (existingReport) {
      return res.json({
        success: true,
        message: `${reporting} reported successfully`
      });
    }

    await UserReports.create({
      userId,
      targetId: target_id,
      reporting,
      reason
    });

    res.json({
      success: true,
      message: `${reporting} reported successfully`
    });

  } catch (error) {
    next(error);
  }
});

module.exports = router;


