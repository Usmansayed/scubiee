module.exports = (io) => {

const express = require("express");
const router = express.Router();
const { Users, Message, ChatRoom, UserChatRooms,Reaction } = require("../models");
const Fuse = require("fuse.js");
const { validateToken } = require('../middlewares/AuthMiddleware');
const Sequelize = require('sequelize');
const { Op } = Sequelize;
const crypto = require('crypto');

const multer = require('multer'); // For handling file uploads
const path = require('path');

// Add this near your other routes



async function updateLastActivity(userId, roomId, activityMsg) {
    const rowsUpdated = await UserChatRooms.update(
    { lastActivity: activityMsg },
    { where: { userId, chatRoomId: roomId } }
  );
  if (rowsUpdated === 0) {
    console.warn(`==============================================================================================================================================================================================`);
  }
};

async function getLastActivity(chatRoomId) {
  // Step 1: Retrieve the most recent message from the chatroom
  const lastMessage = await Message.findOne({
    where: { chatRoomId },
    order: [['createdAt', 'DESC']]
  });

  if (!lastMessage) {
    return null; // No messages in the chatroom
  }

  // Step 2: Check if the last message is unread
  if (lastMessage.read === false) {
    return { type: 'message', data: lastMessage };
  }
  
  // Step 3: Look for unread reactions in this chatroom.
  // To find relevant reactions, join with Message to assure reaction relates to messages in this chatroom.
  const latestUnreadReaction = await Reaction.findOne({
    where: { read: false },
    include: {
      model: Message,
      where: { chatRoomId },
      attributes: []  // We don't need message fields here (optional)
    },
    order: [['createdAt', 'DESC']]
  });

  if (latestUnreadReaction) {
    return { type: 'reaction', data: latestUnreadReaction };
  }

// Since Reaction doesn't have a chatRoomId field, join with the Message model.
const latestReaction = await Reaction.findOne({
  include: [{
    model: Message,
    where: { chatRoomId }
  }],
  order: [['updatedAt', 'DESC']]
});

if (latestReaction && new Date(latestReaction.updatedAt) > new Date(lastMessage.updatedAt)) {
  return { type: 'reaction', data: latestReaction };
}

// Fallback to the last message if it is more recent
return { type: 'message', data: lastMessage };
}

// Search route
router.post('/search', validateToken, async (req, res) => {
  const { username } = req.body;
  const currentUserId = req.user.id;  // Get current user's ID from token
  
  if (!username) {
    return res.status(400).json({ error: "Username is required" });
  }

  try {
    const users = await Users.findAll({
      where: {
        id: { [Op.ne]: currentUserId }  // Exclude current user
      },
      attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture', 'Verified']
    });

    const fuse = new Fuse(users, {
      keys: ["username"],
      threshold: 0.3,
    });

    const results = fuse.search(username).slice(0, 10);

    res.json(results.map(result => result.item));
  } catch (error) {
    console.error('Error fetching users:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});

router.get('/recent-chats', validateToken, async (req, res) => {
  const userId = req.user.id;
  const { lastChatRoomId } = req.query; // may be undefined
  // determine limit: initial call returns 24, subsequent calls return 16
  const limit = lastChatRoomId ? 12 : 20;
  try {
    // Fetch all chatrooms for the user
    const userChatRooms = await UserChatRooms.findAll({
      where: { userId },
      include: [
        {
          model: ChatRoom,
          as: 'chatRoom',
          include: [
            {
              model: Users,
              as: 'members',
              where: { id: { [Op.ne]: userId } },
              attributes: ['id', 'username', 'profilePicture', 'isOnline'] // Added isOnline
            },
            {
              model: Message,
              as: 'messages',
              limit: 1,
              order: [['createdAt', 'DESC']]
            }
          ]
        }
      ]
    });

    // Map to recentChats with lastActivity computed
    let recentChats = await Promise.all(
      userChatRooms.map(async room => {
        const chatRoom = room.chatRoom;
        const otherUser = chatRoom.members[0];
        // Use the getLastActivity helper to determine the last activity
        const lastActivity = await getLastActivity(chatRoom.id);
        // Determine isMedia flag: if the last activity is a message, then use its isMedia property
        const isMedia = lastActivity && lastActivity.type === 'message'
          ? lastActivity.data.isMedia
          : false;
        return {
          chatRoomId: chatRoom.id,
          lastActivity, // { type: 'message'|'reaction', data: { ... } }
          isMedia,
          otherUser: {
            id: otherUser.id,
            username: otherUser.username,
            profilePicture: otherUser.profilePicture,
            isOnline: otherUser.isOnline // Include isOnline status from database
          }
        };
      })
    );

    // Ensure that only chats with valid lastActivity dates are considered
    recentChats = recentChats.filter(chat => chat.lastActivity && chat.lastActivity.data && chat.lastActivity.data.createdAt);

    // Sort the chats with the latest activities on top
    recentChats.sort((a, b) => new Date(b.lastActivity.data.createdAt) - new Date(a.lastActivity.data.createdAt));

    // If lastChatRoomId is provided, find its activity date and filter newer chats
    if (lastChatRoomId) {
      const thresholdChat = recentChats.find(chat => chat.chatRoomId.toString() === lastChatRoomId.toString());
      if (thresholdChat) {
        const thresholdDate = new Date(thresholdChat.lastActivity.data.createdAt);
        recentChats = recentChats.filter(chat => new Date(chat.lastActivity.data.createdAt) < thresholdDate);
      } else {
        // If lastChatRoomId not found, return empty array or you can opt to send initial data.
        return res.json([]);
      }
    }
    
    // Return the first "limit" items
    return res.json(recentChats.slice(0, limit));
  } catch (error) {
    console.error('Error fetching recent chats:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});


router.get('/messages/:roomId', validateToken, async (req, res) => {
  const { roomId } = req.params;
  const { lastMessageId } = req.query;
  const userId = req.user.id;

  try {
    let whereClause = {
      chatRoomId: roomId,
      deleted: false,
      [Op.or]: [
        { senderId: userId, senderDeleted: false },
        { senderId: { [Op.ne]: userId }, receiverDeleted: false }
      ]
    };

    // Add condition for messages older than lastMessageId
    if (lastMessageId) {
      const lastMessage = await Message.findByPk(lastMessageId);
      if (lastMessage) {
        whereClause.createdAt = {
          [Op.lt]: lastMessage.createdAt
        };
      }
    }

    // Fetch messages
    const messages = await Message.findAll({
      where: whereClause,
      attributes: [
        'id', 
        'content', 
        'senderId', 
        'chatRoomId', 
        'delivered', 
        'read', 
        'createdAt', 
        'replyToMessageId', 
        'isMedia', 
        'caption',
        'isPost'
      ],
      include: [
        {
          model: Reaction,
          as: 'reactions',
          attributes: ['reaction', 'senderId', 'messageId']
        }
      ],
      order: [['createdAt', 'DESC']],
      limit: 20
    });

    // Reverse messages so they are in ascending order by createdAt...
    const orderedMessages = messages.reverse();

    // Collect replyToMessageIds from messages
    const replyIdsSet = new Set();
    orderedMessages.forEach(msg => {
      if (msg.replyToMessageId) {
        replyIdsSet.add(msg.replyToMessageId);
      }
    });
    const replyIds = Array.from(replyIdsSet);

    // Fetch the original messages for reply; include isMedia and isPost fields
    const replyMessages = await Message.findAll({
      where: {
        id: { [Op.in]: replyIds }
      },
      attributes: [
        'id', 
        'content', 
        'senderId', 
        'chatRoomId', 
        'createdAt',
        'isMedia',
        'isPost'
      ]
    });

    // Create a mapping of message id to the reply message object
    const replyMap = {};
    replyMessages.forEach(replyMsg => {
      replyMap[replyMsg.id] = replyMsg;
    });

    // Attach the replyMessage field and new fields to each message if available
    const finalMessages = orderedMessages.map(msg => {
      const jsonMsg = msg.toJSON();
      if (jsonMsg.replyToMessageId) {
        const replyData = replyMap[jsonMsg.replyToMessageId] || null;
        jsonMsg.replyMessage = replyData;
        jsonMsg.isOrignalPost = replyData ? !!replyData.isPost : false;
        jsonMsg.isOrignalMedia = replyData ? !!replyData.isMedia : false;
      }
      return jsonMsg;
    });

    res.json(finalMessages);
  } catch (error) {
    console.error('Error fetching messages:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});
// Route to delete a message
router.post('/delete-message', validateToken, async (req, res) => {
  const { messageId } = req.body;
  const userId = req.user.id;

  if (!messageId) {
    return res.status(400).json({ error: "Message ID is required" });
  }

  try {
    const message = await Message.findOne({ where: { id: messageId, senderId: userId } });

    if (!message) {
      return res.status(404).json({ error: "Message not found or you don't have permission to delete this message" });
    }

    await message.update({ deleted: true });

    // Emit the delete event to all users in the room
    req.io.to(message.chatRoomId).emit('messageDeleted', { messageId });

    res.json({ success: true });
  } catch (error) {
    console.error('Error deleting message:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Route to reply to a message
router.post('/reply-message', validateToken, async (req, res) => {
  const { senderId, receiverId, content, replyToMessageId } = req.body;

  if (!senderId || !receiverId || !content || !replyToMessageId) {
    return res.status(400).json({ error: "All fields are required" });
  }

  try {
    const roomId = [senderId, receiverId].sort().join('_');
    let chatRoom = await ChatRoom.findOne({ where: { id: roomId } });

    if (!chatRoom) {
      chatRoom = await ChatRoom.create({ id: roomId });
    }

    // Ensure both users are associated with the chat room
    await UserChatRooms.findOrCreate({ where: { userId: senderId, chatRoomId: roomId } });
    await UserChatRooms.findOrCreate({ where: { userId: receiverId, chatRoomId: roomId } });

    const message = await Message.create({
      chatRoomId: roomId,
      senderId,
      content,
      replyToMessageId,
      delivered: true,
    });

    req.io.to(senderId).emit('newMessage', message);
    req.io.to(receiverId).emit('newMessage', message);

    res.json({ success: true, message });
  } catch (error) {
    console.error('Error replying to message:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Route to delete a message from me
router.post('/delete-message-from-me', validateToken, async (req, res) => {
  const { messageId } = req.body;
  const userId = req.user.id;


  if (!messageId) {
    return res.status(400).json({ error: "Message ID is required" });
  }

  try {
    const message = await Message.findOne({ where: { id: messageId } });

    if (!message) {
      return res.status(404).json({ error: "Message not found" });
    }

    if (message.senderId === userId) {
      await message.update({ senderDeleted: true });
    } else {
      await message.update({ receiverDeleted: true });
    }

    res.json({ success: true });
  } catch (error) {
    console.error('Error deleting message from me:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});


// Route to mark messages as read
router.post('/mark-as-read', validateToken, async (req, res) => {
  const { roomId } = req.body;
  const userId = req.user.id;

  if (!roomId) {
    return res.status(400).json({ error: "Room ID is required" });
  }

  try {
    await Message.update(
      { read: true },
      {
        where: {
          chatRoomId: roomId,
          senderId: { [Op.ne]: userId }, // Only update messages not sent by the current user
          read: false,
        },
      }
    );

    res.json({ success: true });
  } catch (error) {
    console.error('Error marking messages as read:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// routes/Chat.js
router.post('/update-reaction', validateToken, async (req, res) => {
  const { senderId, reaction, messageId } = req.body;

  if (!senderId || !reaction || !messageId) {
    return res.status(400).json({ error: "All fields are required" });
  }

  try {
    const message = await Message.findByPk(messageId);

    if (!message) {
      return res.status(404).json({ error: "Message not found" });
    }

    if (message.senderId === senderId) {
      message.sendersReaction = reaction;
    } else {
      message.reciversReaction = reaction;
    }

    await message.save();
    res.json({ success: true, message });
  } catch (error) {
    console.error('Error updating reaction:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});

router.post('/remove-reaction', validateToken, async (req, res) => {
  const { messageId } = req.body;
  // Ensure required field is provided
  if (!messageId) {
    return res.status(400).json({ error: "messageId is required" });
  }

  try {
    const message = await Message.findByPk(messageId);

    if (!message) {
      return res.status(404).json({ error: "Message not found" });
    }

    // Get senderId from validated token (set by validateToken middleware)
    const senderId = req.user.id;

    // Update the reaction field based on who is removing it.
    if (message.senderId === senderId) {
      message.sendersReaction = null;
    } else {
      message.reciversReaction = null;
    }

    // If your application uses a separate Reaction table, you can remove the corresponding record:
    // await Reaction.destroy({ where: { messageId, senderId } });

    await message.save();
    res.json({ success: true, message });
  } catch (error) {
    console.error('Error removing reaction:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Set up multer storage for file uploads
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    cb(null, './cloud/groupImages'); // Directory where images will be stored
  },
  filename: function (req, file, cb) {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + path.extname(file.originalname)); // Save with unique file name
  }
});



{ /* router.post('/createGroup', validateToken, upload.single('groupImage'), async (req, res) => {
  const { userIds, roomId, groupName } = req.body;
  const currentUserId = req.user.id;
  const groupImage = req.file?.filename; // Safely get the uploaded file's filename or undefined

  // Concatenate the current user ID with the other user IDs into an array
  const allUserIds = userIds ? userIds.split(',').concat(currentUserId) : [currentUserId];

  try {
    // Find or create the chat room
    let chatRoom = await ChatRoom.findOne({ where: { id: roomId } });
    if (!chatRoom) {
      chatRoom = await ChatRoom.create({
        id: roomId,
        isGroup: true,
        name: groupName, // Store the group name
        image: groupImage // Store the group image or null
      });
    } else {
      // Update the chat room if it already exists
      await chatRoom.update({
        isGroup: true,
        name: groupName, // Update the group name
        image: groupImage // Update the group image
      });
    }

    // Associate all selected group members with the chat room
    await Promise.all(allUserIds.map(async (userId) => {
      try {
        await UserChatRooms.findOrCreate({ where: { userId, chatRoomId: roomId } });
      } catch (error) {
        console.error(`Error associating user ${userId} with chat room:`, error);
      }
    }));

    res.json({ success: true, chatRoom });
  } catch (error) {
    console.error('Error creating group:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
}); */ }

router.post('/delete-chatroom', validateToken, async (req, res) => {
  const { roomId } = req.body;
  const userId = req.user.id;

  if (!roomId) {
    return res.status(400).json({ error: "Room ID is required" });
  }

  try {
    // Delete the user's entry from UserChatRooms
    await UserChatRooms.destroy({
      where: { chatRoomId: roomId, userId }
    });

    // Update messages for this chatroom:
    // If the message was sent by the user, mark it as senderDeleted,
    // otherwise mark it as receiverDeleted.
    await Message.update(
      { senderDeleted: true },
      { where: { chatRoomId: roomId, senderId: userId } }
    );

    await Message.update(
      { receiverDeleted: true },
      { where: { chatRoomId: roomId, senderId: { [Op.ne]: userId } } }
    );

    res.json({ success: true });
  } catch (error) {
    console.error('Error deleting chatroom:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});


const chatImageStorage = multer.diskStorage({
  destination: './cloud/chatImages',
  filename: (req, file, cb) => {
    const randomName = crypto.randomBytes(64).toString('hex');
    // Get original extension from file
    const ext = path.extname(file.originalname);
    // If no extension found, get it from mimetype
    const fileExt = ext || (file.mimetype === 'image/jpeg' ? '.jpg' : '.png');
    cb(null, `${randomName}${fileExt}`);
  }
});

const upload = multer({ 
  storage: chatImageStorage,
  limits: { fileSize: 10 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    if (!['image/jpeg', 'image/png'].includes(file.mimetype)) {
      return cb(new Error('Only JPEG and PNG files are allowed'));
    }
    cb(null, true);
  }
});

// Add a route to get all users for chat functionality
router.get('/getAllUsers', validateToken, async (req, res) => {
  try {
    const users = await Users.findAll({
      attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture', 'verified'],
      limit: 100 // Limit to prevent large data transfers
    });
    
    res.json(users);
  } catch (error) {
    console.error('Error fetching all users:', error);
    res.status(500).json({ message: 'Server error' });
  }
});

return router;
};