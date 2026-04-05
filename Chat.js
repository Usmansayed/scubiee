module.exports = (io) => {

const express = require("express");
const router = express.Router();
const { Users, Message, ChatRoom, UserChatRooms } = require("../models");
const Fuse = require("fuse.js");
const { validateToken } = require('../middlewares/AuthMiddleware');
const Sequelize = require('sequelize');
const { Op } = Sequelize;
const crypto = require('crypto');

const multer = require('multer'); // For handling file uploads
const path = require('path');




// Search route
router.post('/search', async (req, res) => {
  const { username } = req.body;
  if (!username) {
    return res.status(400).json({ error: "Username is required" });
  }

  try {
    const users = await Users.findAll({
      attributes: ['id', 'username', 'firstName', 'lastName', 'profilePicture']
    });

    const fuse = new Fuse(users, {
      keys: ["username"],
      threshold: 0.3,
    });

    const results = fuse.search(username);
    res.json(results.map(result => result.item));
  } catch (error) {
    console.error('Error fetching users:', error);
    res.status(500).json({ error: "Internal server error" });
  }
});

// Route to handle sending messages
router.post('/send-message', validateToken, async (req, res) => {
  const { senderId, receiverId, content, replyToMessageId } = req.body;
  const roomId = [senderId, receiverId].sort().join('_');

  try {
    let chatRoom = await ChatRoom.findOne({ where: { id: roomId } });
    if (!chatRoom) {
      chatRoom = await ChatRoom.create({ id: roomId });
    }

    const message = await Message.create({
      chatRoomId: roomId,
      senderId,
      content,
      replyToMessageId: replyToMessageId || null,
      delivered: false, // Will be updated when received
      read: false
    });

    // Emit message to sender immediately
    req.io.to(senderId).emit('receive_message', message);

    // If receiver is online, emit to them as well
    const receiverSocket = Array.from(req.io.sockets.sockets.values())
      .find(s => s.user?.id === receiverId);
    
    if (receiverSocket) {
      req.io.to(receiverId).emit('receive_message', message);
      await message.update({ delivered: true });
    }

    res.json({ success: true, message });
  } catch (error) {
    console.error('Error sending message:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Route to fetch recent chats for a user
router.get('/recent-chats', validateToken, async (req, res) => {
  const userId = req.user.id;

  try {
    const userChatRooms = await UserChatRooms.findAll({
      where: { userId } ,
      include: [
        {
          model: ChatRoom,
          as: 'chatRoom',
          include: [
            {
              model: Users,
              as: 'members',
              where: {
                id: {
                  [Op.ne]: userId,
                },
              },
              attributes: ['id', 'username', 'profilePicture'],
            },
            {
              model: Message,
              as: 'messages',
              limit: 1,
              order: [['createdAt', 'DESC']],
            },
          ],
        },
      ],
    });

    const recentChats = await Promise.all(userChatRooms.map(async (userChatRoom) => {
      const chatRoom = userChatRoom.chatRoom;

      if (!chatRoom) {
        return null;
      }

      const lastMessage = chatRoom.messages && chatRoom.messages.length > 0 ? chatRoom.messages[0] : null;

      if (!lastMessage) {
        return null;
      }

      const otherUser = chatRoom.members[0];

      return {
        chatRoomId: chatRoom.id,
        lastMessage: lastMessage.content,
        lastMessageSenderId: lastMessage.senderId,
        lastMessageRead: lastMessage.read, // Include read status
        isMedia: lastMessage.isMedia,
        otherUser: {
          id: otherUser.id,
          username: otherUser.username,
          profilePicture: otherUser.profilePicture,
        },
      };
    }));

    res.json(recentChats.filter(chat => chat !== null));
  } catch (error) {
    console.error('Error fetching recent chats:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});



// routes/Chat.js
router.get('/messages/:roomId', validateToken, async (req, res) => {
  const { roomId } = req.params;
  const userId = req.user.id;

  try {
    const messages = await Message.findAll({
      where: {
        chatRoomId: roomId,
        deleted: false,
        [Op.or]: [
          { senderId: userId, senderDeleted: false },
          { senderId: { [Op.ne]: userId }, receiverDeleted: false }
        ]
      },
      attributes: ['id', 'content', 'senderId', 'chatRoomId', 'delivered', 'read', 'createdAt', 'replyToMessageId', 'sendersReaction', 'reciversReaction','isMedia','caption'],
      order: [['createdAt', 'ASC']],
    });

    res.json(messages);
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

  console.log(messageId)

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

// Route to add or update a reaction
router.post('/add-reaction', validateToken, async (req, res) => {
  const { messageId, reaction, isSender } = req.body;
  const userId = req.user.id;

  if (!messageId || !reaction) {
    return res.status(400).json({ error: "Message ID and reaction are required" });
  }

  try {
    const message = await Message.findOne({ where: { id: messageId } });

    if (!message) {
      return res.status(404).json({ error: "Message not found" });
    }

    if (isSender) {
      await message.update({ sendersReaction: reaction });
    } else {
      await message.update({ reciversReaction: reaction });
    }

    req.io.to(message.chatRoomId).emit('reactionUpdated', { messageId, reaction, isSender });

    res.json({ success: true, message });
  } catch (error) {
    console.error('Error adding reaction:', error);
    res.status(500).json({ error: "Internal server error" });
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


return router;
};