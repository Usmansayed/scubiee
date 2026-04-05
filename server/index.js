const express = require('express');
const http = require('http');
const fs = require('fs');
const app = express();
const cors = require('cors');
require('dotenv').config();
const passport = require('passport');
const session = require('express-session');
const cookieParser = require('cookie-parser');
const helmet = require('helmet'); // Add helmet import
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
const socketMiddleware = require('./middlewares/SocketMiddleware');
// Add this import for Backblaze B2 functionality
const { uploadToB2, deleteFromB2, generateUniqueFilename } = require('./utils/backblaze');

// Add global error handlers for PM2
process.on('uncaughtException', (error) => {
  console.error('UNCAUGHT EXCEPTION! 💥 Shutting down...', error);
  console.error(error.name, error.message);
  // Give the server 1 second to finish current requests before shutting down
  setTimeout(() => {
    process.exit(1);
  }, 1000);
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('UNHANDLED REJECTION! 💥 Shutting down...', reason);
  // Give the server 1 second to finish current requests before shutting down
  setTimeout(() => {
    process.exit(1);
  }, 1000);
});

const privateKey = fs.readFileSync('./SSL/key.pem', 'utf8');
const certificate = fs.readFileSync('./SSL/cert.pem', 'utf8');
const credentials = { key: privateKey, cert: certificate };
const userSocketMap = new Map();

const api = process.env.VITE_API_URL ;
const Domain = process.env.VITE_DOMAIN;
const port = process.env.PORT ;

// HTTPS redirection middleware - only apply in production
if (process.env.NODE_ENV === 'production') {
  app.use((req, res, next) => {
    const forwarded = req.headers['x-forwarded-proto'];
    if (forwarded && forwarded !== 'https') {
      return res.redirect(301, `https://${req.hostname}${req.url}`);
    }
    next();
  });
}

// Configure security headers with Helmet
// Add this before any other middleware
app.use(
  helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'", "'unsafe-inline'"],
        styleSrc: ["'self'", "'unsafe-inline'"],
        imgSrc: ["'self'", "data:", "blob:"],
        connectSrc: ["'self'"],
        fontSrc: ["'self'"],
        objectSrc: ["'none'"],
        mediaSrc: ["'self'"],
        frameSrc: ["'none'"]
      }
    },
    xssFilter: true,
    noSniff: true,
    referrerPolicy: { policy: "no-referrer-when-downgrade" },
    frameguard: { action: "deny" },
    permissionsPolicy: {
      features: {
        camera: ["'none'"],
        microphone: ["'none'"],
        geolocation: ["'none'"],
        'interest-cohort': ["'none'"],
        payment: ["'none'"],
        usb: ["'none'"],
        gyroscope: ["'none'"],
        accelerometer: ["'none'"]
      }
    },
    hsts: {
      maxAge: 31536000, // 1 year in seconds
      includeSubDomains: true,
      preload: true
    }
  })
);

// Middleware
app.use(express.json());
app.use(cors({
  origin: [Domain], // Allow both localhost and 192.168.1.8
  credentials: true
}));
app.use(cookieParser());

const server = http.createServer(credentials, app);
const io = new Server(server, {
  cors: {
    origin: [Domain],
    methods: ["GET", "POST"],
    credentials: true
  }
});

// Global delay middleware (for development simulation)
// You can control this with environment variables
const ENABLE_DELAY = process.env.ENABLE_SERVER_DELAY === 'true' || process.env.NODE_ENV !== 'production';
const MIN_DELAY = parseInt(process.env.MIN_SERVER_DELAY) || 100;
const MAX_DELAY = parseInt(process.env.MAX_SERVER_DELAY) || 1000;

if (ENABLE_DELAY) {
  app.use((req, res, next) => {
    const delay = Math.floor(Math.random() * (MAX_DELAY - MIN_DELAY + 1)) + MIN_DELAY;
    console.log(`Applying ${delay}ms delay to ${req.method} ${req.path}`);
    setTimeout(() => {
      next();
    }, delay);
  });
}

// Apply socket middleware with enhanced functionality
app.use(socketMiddleware);

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

const papersRouter = require("./routes/Papers");
app.use("/papers", papersRouter);

// Community routes
const communitiesRouter = require("./routes/Communities");
app.use("/communities", communitiesRouter);


// Import the new Support routes
const supportRouter = require("./routes/Support");

app.use('/cloud', (req, res, next) => {
  // Override the CSP and Cross-Origin-Resource-Policy for cloud resources
  res.setHeader('Cross-Origin-Resource-Policy', 'cross-origin');
  next();
}, express.static(path.join(__dirname, 'cloud')));

// Add the support routes
app.use("/support", supportRouter);

// Add a simple ping endpoint for network connectivity checks
app.get('/ping', (req, res) => {
  res.status(200).json({ status: 'ok', timestamp: Date.now() });
});

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
const INACTIVE_TIMEOUT = 20 * 60 * 1000; // 20 minutes in milliseconds

// Apply the authentication middleware to socket.io
io.use(authenticateToken);

const activelyViewing = new Map();
const onlineUsers = new Set();
const roomOnlineUsers = new Map(); // Map to track online users in each room

io.on('connection', async (socket) => {
  const userId = socket.user.id;
  userSocketMap.set(userId, socket);

  // Add user to their own room for private notifications
  socket.join(userId.toString());

  try {
    // Update user's online status in database
    await db.Users.update(
      { isOnline: true },
      { where: { id: userId } }
    );

    // Get all online users from database with complete information
    const onlineUsersData = await db.Users.findAll({
      where: { isOnline: true },
      attributes: ['id']
    });

    // Add the current user to online users set
    onlineUsers.add(userId);

    // Emit to everyone that this user is online
    io.emit('userOnline', { userId });

    // Emit current online users to the newly connected user
    socket.emit('initialOnlineUsers', {
      users: onlineUsersData.map(user => user.id) // Send just the IDs for simplicity
    });

  } catch (error) {
    console.error('Error updating online status:', error);
  }

  // Add handler for requesting online users list
  socket.on('requestOnlineUsers', async () => {
    try {
      const onlineUsersData = await db.Users.findAll({
        where: { isOnline: true },
        attributes: ['id']
      });
      
      socket.emit('initialOnlineUsers', { 
        users: onlineUsersData.map(user => user.id)
      });
    } catch (error) {
      console.error('Error fetching online users on request:', error);
    }
  });

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
        userLastActivity.delete(key);
      }
    });
  }, 60000); // Check every minute

  socket.on('reactionUpdated', async ({ senderId, reaction, messageId }) => {
    try {
      // Get message first
      const message = await db.Message.findByPk(messageId);
      if (!message) return;
      
      const roomId = message.chatRoomId;
      // Derive receiverId from roomId
      const ids = roomId.split('_');
      const receiverId = ids[0] === senderId.toString() ? ids[1] : ids[0];
    
      // Ensure room joined before sending events
      await ensureRoomJoined(roomId, senderId, receiverId, socket);
    
      // Update or delete the reaction in the Reaction table
      const ReactionModel = db.Reaction;
      let reactionInstance = await ReactionModel.findOne({
        where: { messageId, senderId }
      });
      if (reaction === null) {
        // If reaction is null, delete existing reaction if it exists.
        if (reactionInstance) {
          await ReactionModel.destroy({ where: { messageId, senderId }, limit: 1 });
        }
        return;
      }
      
      if (reactionInstance) {
        reactionInstance.reaction = reaction;
        // Reset read status on update
        reactionInstance.read = false;
        await reactionInstance.save();
      } else {
        reactionInstance = await ReactionModel.create({ messageId, senderId, reaction, read: false });
      }
    
      // Emit reactionUpdated event with the updated reaction data
      io.to(roomId).emit('reactionUpdated', { messageId, reaction, senderId, roomId });
    } catch (error) {
      console.error('Error updating reaction:', error);
    }
  });

  socket.on('userOnline', ({ userId }) => {
    onlineUsers.add(userId);
    io.emit('userOnline', { userId });
  });

  socket.on('userOffline', ({ userId }) => {
    onlineUsers.delete(userId);
    io.emit('userOffline', { userId });
  });

  // Update disconnect handler
  socket.on('disconnect', async () => {
    clearInterval(checkInactivity);
    
    const hasOtherConnections = Array.from(io.sockets.sockets.values())
      .some(s => s.user?.id === userId && s.id !== socket.id);
    
    if (!hasOtherConnections) {
      try {
        // Update user's online status in database
        await db.Users.update(
          { isOnline: false },
          { where: { id: userId } }
        );
        
        io.emit('userOffline', { userId });
      } catch (error) {
        console.error('Error updating offline status:', error);
      }
    }
  });

  // Handle entering a room
  socket.on('enterRoom', async ({ roomId, userId }) => {
  
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

      const readMessages = await db.Message.findAll({
      });
      const messageIds = readMessages.map(m => m.id);
      if (messageIds.length) {
        // Also mark all reactions for these messages as read
        await db.Reaction.update(
          { read: true },
          { where: { messageId: messageIds, read: false } }
        );
      }
  
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
      socket.to(roomId).emit('messagesRead', { roomId, readerId: userId });

    } catch (error) {
      console.error('Error marking messages as read:', error);
    }
  });

  // Handle opening a chat
  socket.on('openChat', ({ roomId }) => {
    if (!activelyViewing.has(roomId)) {
      activelyViewing.set(roomId, new Set());
    }
    activelyViewing.get(roomId).add(userId);
    socket.to(roomId).emit('userOpenedChat', { roomId, userId });
  });

  // Handle closing a chat
  socket.on('closeChat', ({ roomId }) => {
    if (activelyViewing.has(roomId)) {
      const viewers = activelyViewing.get(roomId);
      viewers.delete(userId);
      if (viewers.size === 0) {
        activelyViewing.delete(roomId);
      }
    }
    socket.to(roomId).emit('userClosedChat', { roomId, userId });
  });

  socket.on('sendMessage', async ({
    roomId,
    UserDetails,
    content,
    replyToMessageId,
    isMedia,
    caption,
    isPost,
    replyMessage // carried from the client, used for thumbnail, etc.
  }) => {
    const [senderId, receiverId] = UserDetails;

    if (senderId === receiverId) {
      socket.emit('messageError', { 
        error: 'You cannot send a message to yourself',
        roomId
      });
      return;
    }
  
    try {
      // First ensure both users are joined to the room
      await ensureRoomJoined(roomId, senderId, receiverId, socket);
      const receiverSocket = userSocketMap.get(receiverId);
      if (receiverSocket) receiverSocket.join(roomId);
      userLastActivity.set(`${roomId}_${senderId}`, Date.now());
  
      const isReceiverActive =
        activelyViewing.has(roomId) &&
        activelyViewing.get(roomId).has(receiverId);
  
      // Build message data based on the payload
      const messageData = {
        chatRoomId: roomId,
        senderId,
        content,
        delivered: true,
        replyToMessageId: replyToMessageId || null,
        isMedia: isMedia || false,
        caption: caption || null,
        read: isReceiverActive,
        createdAt: new Date()
      };
  
      if (typeof isPost !== 'undefined' && isPost) {
        messageData.isPost = true;
        
        // Increment the shared counter for this post
        // content contains the postId when isPost is true
        await db.Post.increment('shared', { by: 1, where: { id: content } });
      }
  
      // If this message is a reply and the original is a media message,
      // use the post ID stored in replyMessage.content to fetch its thumbnail.
      if (replyToMessageId && replyMessage && replyMessage.isMedia) {
        const post = await db.Posts.findOne({ where: { id: replyMessage.content } });
        if (post) {
          messageData.replyPostThumbnail = post.thumbnail;
        }
      }
  
      // If a replyToMessageId is provided, fetch the original message details
      let originalReplyMessage = null;
      if (replyToMessageId) {
        originalReplyMessage = await db.Message.findOne({ where: { id: replyToMessageId } });
      }
  
      // Create the new message in the database
      const message = await db.Message.create(messageData);
  
      // Prepare the message object to send back, including the fetched reply message if available
      const messageWithReply = {
        ...message.dataValues,
        replyMessage: originalReplyMessage
      };
  
      // Emit the complete message object
      io.to(roomId).emit('receive_message', messageWithReply);
  
      if (isReceiverActive) {
        io.to(roomId).emit('messagesRead', {
          roomId,
          userId: receiverId,
          lastMessageId: message.id
        });
      }
  
      io.emit('chatUpdated');
  
      // Optionally send a "messageSeen" event after updating read status
      if (activelyViewing.has(roomId) && activelyViewing.get(roomId).has(receiverId)) {
        await db.Message.update(
          { read: true },
          { where: { id: message.id } }  // Fixed: added closing parenthesis
        );
        await db.Reaction.update(
          { read: true },
          { where: { messageId: message.id, read: false } }
        );
        io.to(roomId).emit('messageSeen', { messageId: message.id, userId: receiverId });
      } else {
        const lastSeenMessage = await db.Message.findOne({
          where: {
            chatRoomId: roomId,
            senderId: { [Op.ne]: receiverId },
            read: true,
          },
          order: [['createdAt', 'DESC']],
        });
  
        if (lastSeenMessage) {
          io.to(roomId).emit('messageSeen', { 
            messageId: lastSeenMessage.id,
            userId: receiverId 
          });
        }
      }
    } catch (error) {
      console.error('Error creating message:', error);
      socket.emit('errorOccurred', { 
        type: 'message_error', 
        message: 'Failed to send message', 
        roomId 
      });
    }
  });

const chatImageStorage = multer.memoryStorage();

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
    // Generate a unique filename for the image
    const filename = generateUniqueFilename(req.file.originalname);
    
    // Upload the file to B2 with 'chatImages' virtual folder
    const result = await uploadToB2(req.file.buffer, filename, 'chatImages');
    
    // Check if receiver is actively viewing the chat
    const isReceiverActive = activelyViewing.has(roomId) &&
                             activelyViewing.get(roomId).has(receiverId);

    // Return the message data with the B2 URL to the client
    res.json({ 
      success: true, 
      fileName: filename,
      url: result.url // Include the full URL from B2
    });
  } catch (error) {
    console.error('Error uploading image:', error);
    res.status(500).json({ error: 'Server error', details: error.message });
  }
});

// Community image upload endpoints
const communityUpload = multer({ 
  storage: multer.memoryStorage(),
  limits: { fileSize: 5 * 1024 * 1024 }, // 5MB limit
  fileFilter: (req, file, cb) => {
    if (!['image/jpeg', 'image/png', 'image/jpg'].includes(file.mimetype)) {
      return cb(new Error('Only JPEG and PNG files are allowed'));
    }
    cb(null, true);
  }
});

app.post('/upload/community-icon', validateToken, communityUpload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file provided' });

  try {
    // Generate a unique filename for the icon
    const filename = generateUniqueFilename(req.file.originalname);
    
    // Upload the file to B2 with 'communityProfile' virtual folder
    const result = await uploadToB2(req.file.buffer, filename, 'communityProfile');
    
    res.json({ 
      success: true, 
      fileName: filename,
      url: result.url
    });
  } catch (error) {
    console.error('Error uploading community icon:', error);
    res.status(500).json({ error: 'Server error', details: error.message });
  }
});

app.post('/upload/communityBanner', validateToken, communityUpload.single('file'), async (req, res) => {
  if (!req.file) return res.status(400).json({ error: 'No file provided' });

  try {
    // Generate a unique filename for the banner
    const filename = generateUniqueFilename(req.file.originalname);
    
    // Upload the file to B2 with 'communityBanner' virtual folder
    const result = await uploadToB2(req.file.buffer, filename, 'communityBanner');
    
    res.json({ 
      success: true, 
      fileName: filename,
      url: result.url
    });
  } catch (error) {
    console.error('Error uploading community banner:', error);
    res.status(500).json({ error: 'Server error', details: error.message });
  }
});


// Update deleteMessage event handler
socket.on('deleteMessage', async ({ roomId, senderId, receiverId, messageId, deleteForEveryone }) => {
    try {
      // Ensure both participants are joined to the room
      await ensureRoomJoined(roomId, senderId, receiverId, socket);
      if (deleteForEveryone) {
        await db.Message.update(
          { deleted: true },
          { where: { id: messageId } }  // Fixed: added closing parenthesis
        );
      } else {
        await db.Message.update(
          { senderDeleted: true },
          { where: { id: messageId, senderId: userId } }  // Fixed: added closing parenthesis
        );
      }
      io.to(roomId).emit('messageDeleted', { messageId, roomId, deleteForEveryone });
    } catch (error) {
      console.error('Error deleting message:', error);
    }
  });

  // Handle disconnection
  socket.on('disconnect', () => {
    onlineUsers.delete(userId);

    // Broadcast the updated list of online users to all clients
    io.emit('onlineUsers', Array.from(onlineUsers));
  });
});

// Route for marking all notifications as read
app.post('/user-interactions/read-all-notifications', validateToken, async (req, res) => {
  try {
    const userId = req.user.id;
    
    // Update all notifications for this user to read
    await db.Notifications.update(
      { is_read: true },
      { where: { user_id: userId, is_read: false } }  // Fixed: added closing parenthesis
    );
    
    res.json({ success: true });
  } catch (error) {
    console.error('Error marking notifications as read:', error);
    res.status(500).json({ error: 'Server error' });
  }
});

// Helper function to ensure room joining
async function ensureRoomJoined(roomId, senderId, receiverId, socket) {
  try {
    const [chatRoom, created] = await db.ChatRoom.findOrCreate({ where: { id: roomId } });

    await Promise.all([
      db.UserChatRooms.findOrCreate({ where: { userId: senderId, chatRoomId: roomId } }),
      db.UserChatRooms.findOrCreate({ where: { userId: receiverId, chatRoomId: roomId } }),
    ]);

    const receiverSocket = Array.from(io.sockets.sockets.values())
      .find(s => s.user?.id === receiverId);

    socket.join(roomId); // Join sender

    if (receiverSocket) {
      receiverSocket.join(roomId);
    } else {
    }

  } catch (error) {
    console.error("Error ensuring room joined:", error);
    throw error;
  }
}

// Import the comprehensive database synchronization function
const { syncModels } = require('./createDatabase');

// Import the paper scheduler
const paperScheduler = require('./schedulers/paperScheduler');

// Add a function to initialize the database
async function initializeDatabase() {
  try {
    console.log('Initializing database with comprehensive model synchronization...');
    
    // Use the comprehensive syncModels function that handles all models in the correct order
    await syncModels(db, false); // false = don't force recreate existing tables
    
    console.log('Database initialization completed successfully.');
    
  } catch (error) {
    console.error("Failed to initialize database:", error);
  }
}

// Call the initialization function before starting the server
(async () => {
  await initializeDatabase();
  
  // Start the paper scheduler after database initialization
  paperScheduler.start();
  console.log('📰 [SERVER] Paper Scheduler initialized');
  
  // Start the server after database initialization
  server.listen(port, () => {
    console.log(`🚀 [SERVER] Server running on port ${port}`);
    console.log(`📅 [SERVER] Paper generation scheduled every hour at 55 minutes`);
    
    // Add graceful shutdown functionality
    process.on('SIGINT', gracefulShutdown);
    process.on('SIGTERM', gracefulShutdown);
  });
})();

// Implement graceful shutdown function
function gracefulShutdown() {
  console.log('🛑 [SERVER] Graceful shutdown initiated...');
  
  // Stop the paper scheduler
  paperScheduler.stop();
  console.log('📰 [SERVER] Paper Scheduler stopped');
  
  server.close(() => {
    db.sequelize.close().then(() => {
      console.log('✅ [SERVER] Graceful shutdown completed');
      process.exit(0);
    }).catch(err => {
      console.error('❌ [SERVER] Error closing database connections:', err);
      process.exit(1);
    });
  });
  
  // Force shutdown after 30 seconds if closing connections takes too long
  setTimeout(() => {
    console.error('Could not close connections in time, forcefully shutting down');
    process.exit(1);
  }, 30000);
}

