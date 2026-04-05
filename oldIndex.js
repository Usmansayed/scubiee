const express = require('express');
const http = require('http');
const fs = require('fs');
const app = express();
const cors = require('cors');
require('dotenv').config();
const passport = require('passport');
const session = require('express-session');
const cookieParser = require('cookie-parser');
require('./authenticate');
const { Server } = require('socket.io');
const db = require("./models");
const jwt = require('jsonwebtoken');
const { Op } = require('sequelize');
const path = require('path');
const storyRoutes = require('./routes/Story');
const { Message } = require('./models');
const multer = require('multer');
const crypto = require('crypto');

const privateKey = fs.readFileSync('./SSL/key.pem', 'utf8');
const certificate = fs.readFileSync('./SSL/cert.pem', 'utf8');
const credentials = { key: privateKey, cert: certificate };

// Middleware
app.use(express.json());
app.use(cors({
  origin: ['http://localhost:5173', 'http://192.168.1.8:5173'], // Allow both localhost and 192.168.1.8
  credentials: true
}));
app.use(cookieParser());

const server = http.createServer(credentials, app);
const io = new Server(server);

const isProduction = process.env.NODE_ENV === 'production';

app.use(session({
  secret: "SPXvx6-tgomulFrFrx",
  resave: false,
  saveUninitialized: false,
  cookie: { 
    secure: isProduction, // Secure only in production mode
    httpOnly: true,       // Prevent client-side JS from accessing cookies
    sameSite: 'lax',      // Protect against CSRF
    maxAge: 24 * 60 * 60 * 1000 // 1 day
  }
}));

app.use(passport.initialize());
app.use(passport.session());
const { validateToken } = require("./middlewares/AuthMiddleware");

// Routers
const usersRouter = require("./routes/Users");
app.use("/user", usersRouter);

const chatRouter = require('./routes/Chat')(io);
app.use('/chat', chatRouter);

const postRouter = require("./routes/Post");
app.use("/post", postRouter);

const searchRouter = require("./routes/Search");
app.use("/search", searchRouter);

const interactionsRouter = require("./routes/PostsInteractions");
app.use("/user-interactions", interactionsRouter);

const story = require("./routes/Story");
app.use("/story", story);

// Serve static files from the uploads directory
app.use('/cloud', express.static(path.join(__dirname, 'cloud')));

// Middleware to authenticate and extract user from token
const authenticateToken = (socket, next) => {
  const tokenCookie = socket.handshake.headers.cookie?.split('; ').find(row => row.startsWith('access_token='));
  if (!tokenCookie) {
    return next(new Error('Authentication error'));
  }
  const token = tokenCookie.split('=')[1];

  jwt.verify(token, process.env.JWT_SECRET, (err, user) => {
    if (err) return next(new Error('Authentication error'));
    socket.user = user;
    next();
  });
};

// Add new state tracking variables at the top of the file
const userLastActivity = new Map(); // Track last activity time for each user in each room
const INACTIVE_TIMEOUT = 5 * 60 * 1000; // 5 minutes in milliseconds

// Database synchronization and server start
db.sequelize.sync().then(() => {
  const server = http.createServer(app);
  const io = new Server(server, {
    cors: {
      origin: ["http://localhost:5173", "http://192.168.1.8:5173"], // Allow both localhost and 192.168.1.8
      methods: ["GET", "POST"],
      credentials: true
    }
  });

  io.use(authenticateToken); // Attach authentication middleware

  const activelyViewing = new Map();
  const onlineUsers = new Set();
  const roomOnlineUsers = new Map(); // Map to track online users in each room

  io.on('connection', async (socket) => {
    console.log('New client connected');
    const userId = socket.user.id;

    // Add new event handler for chat activity
    socket.on('chatActivity', ({ roomId, userId, type }) => {
      userLastActivity.set(`${roomId}_${userId}`, Date.now());
    });

    // Add inactivity checker
    const checkInactivity = setInterval(() => {
      const now = Date.now();
      userLastActivity.forEach((lastActivity, key) => {
        const [roomId, userId] = key.split('_');
        if (now - lastActivity > INACTIVE_TIMEOUT) {
          socket.leave(roomId);
          io.to(roomId).emit('userInactive', { userId, roomId });
          console.log("user inactive----------------------------------------------------------------------------------");
          userLastActivity.delete(key);
        }
      });
    }, 60000); // Check every minute

 
    socket.on('reactionUpdated', async ({ senderId, reaction, messageId }) => {
      try {
        const message = await db.Message.findByPk(messageId);

        if (!message) {
          return;
        }

        if (message.senderId === senderId) {
          message.sendersReaction = reaction;
        } else {
          message.reciversReaction = reaction;
        }

        await message.save();

        // Emit the reaction update to all users in the room
        io.to(message.chatRoomId).emit('reactionUpdated', { messageId, reaction, senderId });
      } catch (error) {
        console.error('Error updating reaction:', error);
      }
    });

    socket.on('userOnline', ({ userId }) => {
      onlineUsers.add(userId);
      io.emit('userOnline', { userId });
      console.log(`User ${userId} is online`);
    });
  
    socket.on('userOffline', ({ userId }) => {
      onlineUsers.delete(userId);
      io.emit('userOffline', { userId });
      console.log(`User ${userId} went offline`);
    });
  
    // Update disconnect handler
    socket.on('disconnect', () => {
      clearInterval(checkInactivity);
      const hasOtherConnections = Array.from(io.sockets.sockets.values())
        .some(s => s.user?.id === userId && s.id !== socket.id);
      
      if (!hasOtherConnections) {
        onlineUsers.delete(userId);
        io.emit('userOffline', { userId });
        console.log(`User ${userId} disconnected`);
      }
    });
  
    // Add user to online users set immediately
    onlineUsers.add(userId);
    io.emit('userOnline', { userId });

    // Notify all rooms the user is associated with about their online status
    const userChatRooms = await db.UserChatRooms.findAll({
      where: { userId },
      include: [
        {
          model: db.ChatRoom,
          as: 'chatRoom',
          attributes: ['id'],
        },
      ],
    });



    userChatRooms.forEach(userChatRoom => {
      const roomId = userChatRoom.chatRoom.id;
      socket.join(roomId);
      console.log(`User ${userId} joined room ${roomId}`);

      // Add user to the room's online users set
      if (!roomOnlineUsers.has(roomId)) {
        roomOnlineUsers.set(roomId, new Set());
      }
      roomOnlineUsers.get(roomId).add(userId);

      // Emit the current online users in the room to the newly joined user
      socket.emit('currentOnlineUsers', { roomId, onlineUsers: Array.from(roomOnlineUsers.get(roomId)) });

      // Notify all users in the room about the new online user
      io.to(roomId).emit('userOnline', { userId, roomId });
    });

    // Notify all connected clients about the new online user
    io.emit('userOnline', { userId });

    // Handle entering a room
    socket.on('enterRoom', async ({ roomId, userId }) => {
      console.log(`User ${userId} entered room ${roomId}`);
      socket.join(roomId);
    
      try {
        // Mark all messages as read
        await db.Message.update(
          { read: true },
          {
            where: {
              chatRoomId: roomId,
              senderId: { [Op.ne]: userId },
              read: false,
            },
          }
        );
    
        // Get the chat room's last message
        const lastMessage = await db.Message.findOne({
          where: { chatRoomId: roomId },
          order: [['createdAt', 'DESC']],
        });
    
        if (lastMessage) {
          // Emit messagesRead event with updated status
          io.to(roomId).emit('messagesRead', { 
            roomId, 
            userId,
            lastMessageId: lastMessage.id
          });
        }
    
        console.log(`Messages in room ${roomId} marked as read by user ${userId}`);
      } catch (error) {
        console.error('Error marking messages as read:', error);
      }
    });

    // Handle leaving a room
    socket.on('leftRoom', ({ roomId }) => {
      console.log(`User ${userId} left room ${roomId}`);
      socket.leave(roomId);
      if (activelyViewing.has(roomId)) {
        const viewers = activelyViewing.get(roomId);
        viewers.delete(userId);
        if (viewers.size === 0) {
          activelyViewing.delete(roomId);
        }
      }
    });

    // Handle opening a chat
    socket.on('openChat', ({ roomId }) => {
      console.log(`User ${userId} opened chat in room ${roomId}`);
      if (!activelyViewing.has(roomId)) {
        activelyViewing.set(roomId, new Set());
      }
      activelyViewing.get(roomId).add(userId);
      socket.to(roomId).emit('userOpenedChat', { roomId, userId });
    });

    // Handle closing a chat
    socket.on('closeChat', ({ roomId }) => {
      console.log(`User ${userId} closed chat in room ${roomId}`);
      if (activelyViewing.has(roomId)) {
        const viewers = activelyViewing.get(roomId);
        viewers.delete(userId);
        if (viewers.size === 0) {
          activelyViewing.delete(roomId);
        }
      }
      socket.to(roomId).emit('userClosedChat', { roomId, userId });
    });

 socket.on('sendMessage', async ({ roomId, UserDetails, content, replyToMessageId, isMedia, caption }) => {
  const [senderId, receiverId] = UserDetails;

  try {
    // First ensure both users are joined to the room
    await ensureRoomJoined(roomId, senderId, receiverId, socket);

    // Update last activity time
    userLastActivity.set(`${roomId}_${senderId}`, Date.now());

    let chatRoom = await db.ChatRoom.findOne({ where: { id: roomId } });
    if (!chatRoom) chatRoom = await db.ChatRoom.create({ id: roomId });

    await db.UserChatRooms.findOrCreate({ where: { userId: senderId, chatRoomId: roomId } });
    await db.UserChatRooms.findOrCreate({ where: { userId: receiverId, chatRoomId: roomId } });

    const isReceiverActive = activelyViewing.has(roomId) && 
                           activelyViewing.get(roomId).has(receiverId);

    // Create message with read status based on receiver's activity
    const message = await db.Message.create({
      chatRoomId: roomId,
      senderId,
      content,
      delivered: true,
      replyToMessageId: replyToMessageId || null,
      isMedia: isMedia || false,
      caption: caption || null,
      read: isReceiverActive, // Set read based on receiver's active status
      createdAt: new Date()
    });

    io.to(roomId).emit('receive_message', message);

    // If receiver is active, mark message as read immediately
    if (isReceiverActive) {
      io.to(roomId).emit('messagesRead', { 
        roomId, 
        userId: receiverId,
        lastMessageId: message.id
      });
    }

    // Notify all connected users about chat updates
    io.emit('chatUpdated');

        // Check if the recipient is actively viewing the chat room and mark as seen only for other users
        if (activelyViewing.has(roomId) && activelyViewing.get(roomId).has(receiverId)) {
          await db.Message.update(
            { read: true },
            {
              where: {
                id: message.id,
              },
            }
          );
          io.to(roomId).emit('messageSeen', { messageId: message.id, userId: receiverId });
        } else {
          // Find the last seen message
          const lastSeenMessage = await db.Message.findOne({
            where: {
              chatRoomId: roomId,
              senderId: { [Op.ne]: receiverId },
              read: true,
            },
            order: [['createdAt', 'DESC']],
          });

          if (lastSeenMessage) {
            io.to(roomId).emit('messageSeen', { messageId: lastSeenMessage.id, userId: receiverId });
          }
        }

      } catch (error) {
        console.error('Error creating message:', error);
      }
    });

    const chatImageStorage = multer.diskStorage({
      destination: './cloud/chatImages',
      filename: (req, file, cb) => {
        const randomName = crypto.randomBytes(64).toString('hex');
        const ext = path.extname(file.originalname);
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

    app.post('/chat/upload-image', validateToken, upload.single('image'), async (req, res) => {
      if (!req.file) return res.status(400).json({ error: 'No image provided' });
    
      const { senderId, receiverId, caption } = req.body;
      const roomId = [senderId, receiverId].sort().join('_');
    
      try {
        // Check if receiver is actively viewing the chat
        const isReceiverActive = activelyViewing.has(roomId) && 
                               activelyViewing.get(roomId).has(receiverId);
    
        const message = await Message.create({
          chatRoomId: roomId,
          senderId,
          content: req.file.filename,
          delivered: true,
          isMedia: true,
          caption: caption || null,
          read: isReceiverActive // Set read status based on receiver's activity
        });
    
        io.to(roomId).emit('receive_message', message);
    
        // If receiver is active, emit messagesRead event
        if (isReceiverActive) {
          io.to(roomId).emit('messagesRead', { 
            roomId, 
            userId: receiverId,
            lastMessageId: message.id
          });
        }
    
        res.json({ success: true, message });
      } catch (error) {
        console.error('Error uploading image:', error);
        res.status(500).json({ error: 'Server error' });
      }
    });

    // Handle deleting a message
    socket.on('deleteMessage', async ({ messageId, roomId }) => {
      try {
        await db.Message.update(
          { deleted: true },
          {
            where: {
              id: messageId,
              senderId: userId, // Check if userId is equal to senderId
            },
          }
        );

        // Emit message deletion to all users in the room
        io.to(roomId).emit('messageDeleted', { messageId, roomId });
      } catch (error) {
        console.error('Error deleting message:', error);
      }
    });

    // Handle disconnection
    socket.on('disconnect', () => {
      console.log('Client disconnected');
      onlineUsers.delete(userId);

      userChatRooms.forEach(userChatRoom => {
        const roomId = userChatRoom.chatRoom.id;
        io.to(roomId).emit('userOffline', { userId, roomId });

        // Remove user from the room's online users set
        if (roomOnlineUsers.has(roomId)) {
          roomOnlineUsers.get(roomId).delete(userId);
          if (roomOnlineUsers.get(roomId).size === 0) {
            roomOnlineUsers.delete(roomId);
          }
        }
      });

      // Broadcast the updated list of online users to all clients
      io.emit('onlineUsers', Array.from(onlineUsers));
    });
  });

  server.listen(5001, '0.0.0.0', () => { // Listen on all network interfaces
    console.log("Server is running on port 5001 with HTTPS");
  });
});

// Helper function to ensure room joining
async function ensureRoomJoined(roomId, senderId, receiverId, socket) {
  return new Promise(async (resolve, reject) => {
    try {
      // Create or get chat room
      let chatRoom = await db.ChatRoom.findOne({ where: { id: roomId } });
      if (!chatRoom) {
        chatRoom = await db.ChatRoom.create({ id: roomId });
      }

      // Join both users to the room
      await db.UserChatRooms.findOrCreate({ where: { userId: senderId, chatRoomId: roomId } });
      await db.UserChatRooms.findOrCreate({ where: { userId: receiverId, chatRoomId: roomId } });

      // Join socket to room
      socket.join(roomId);
      
      // Emit room joined event
      io.to(roomId).emit('roomJoined', { roomId, users: [senderId, receiverId] });

      resolve();
    } catch (error) {
      reject(error);
    }
  });
}