module.exports = (sequelize, DataTypes) => {
  const Message = sequelize.define('Message', {
    
    id: {
      type: DataTypes.INTEGER,
      primaryKey: true,
      autoIncrement: true,
    },
    content: {
      type: DataTypes.TEXT,
      allowNull: false,
    },
    senderId: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    chatRoomId: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    delivered: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    read: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    replyToMessageId: {
      type: DataTypes.INTEGER, // Change this to match the type of 'id'
      allowNull: true,
    },
    deleted: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    senderDeleted: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    receiverDeleted: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
   
    isMedia: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    caption: {
      type: DataTypes.STRING,
      allowNull: true,
    },
    isPost: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
 
  });

  Message.associate = (models) => {
    Message.hasMany(models.Reaction, { as: 'reactions', foreignKey: 'messageId' });
    Message.belongsTo(models.Users, { foreignKey: 'senderId', onDelete: 'NO ACTION', onUpdate: 'CASCADE' });
    Message.belongsTo(models.ChatRoom, { foreignKey: 'chatRoomId', onDelete: 'CASCADE', onUpdate: 'CASCADE' });
    Message.belongsTo(models.Message, { foreignKey: 'replyToMessageId', as: 'ReplyToMessage', onDelete: 'SET NULL', onUpdate: 'CASCADE' });
  };

  return Message; 
};