// This middleware enhances the socket.io functionality for notification events

const socketMiddleware = (req, res, next) => {
  // Skip if io is not available
  if (!req.io) {
    return next();
  }

  // Enhanced emit function that includes sender details
  req.io.emitWithSender = async (event, userId, data, senderModel) => {
    try {
      // CRITICAL: Make absolutely sure we have all required fields for notifications
      if (event === 'notification') {
        // Ensure all required fields exist
        if (!data.type) {
          console.error('Missing notification type:', data);
          return; // Don't emit invalid notifications
        }
        
        // Make sure we have both formats of IDs (camelCase and snake_case)
        data.sender_id = data.sender_id || data.senderId;
        data.senderId = data.senderId || data.sender_id;
        data.reference_id = data.reference_id || data.referenceId;
        data.referenceId = data.referenceId || data.reference_id;
        data.post_id = data.post_id || data.postId;
        data.postId = data.postId || data.post_id;
        
        // Make sure we have a timestamp
        data.timestamp = data.timestamp || data.createdAt || new Date().toISOString();
        data.createdAt = data.timestamp;
        
        // Ensure the target user_id is set
        data.user_id = userId;
      }
      
      // If there's a sender ID and a model to fetch sender data
      if (data.senderId && senderModel) {
        // Get the sender details to include in the notification
        const sender = await senderModel.findByPk(data.senderId, {
          attributes: ['id', 'username', 'profilePicture', 'Verified']
        });
        
        if (sender) {
          // Include the sender data in the notification
          data.sender = sender.dataValues;
          console.log(`Emitting ${event} to user ${userId} with sender data:`, sender.dataValues.username);
        }
      }
      
      console.log(`Emitting ${event} to ${userId} through room ${userId.toString()}:`, data);
      
      // Emit the event to the user's room and also directly to any matching socket
      req.io.to(userId.toString()).emit(event, data);
      
      // Also try direct delivery to any connected sockets for this user
      const sockets = Array.from(req.io.sockets.sockets.values())
        .filter(s => s.user?.id === userId);
      
      if (sockets.length > 0) {
        sockets.forEach(socket => {
          socket.emit(event, data);
        });
      }
    } catch (error) {
      console.error(`Error in emitWithSender for event ${event}:`, error);
      // Still try to emit without enhanced data if there was an error
      req.io.to(userId.toString()).emit(event, data);
    }
  };
  
  next();
};

module.exports = socketMiddleware;
