module.exports = (sequelize, DataTypes) => {
  const ChatRoom = sequelize.define("ChatRoom", {
    id: {
      type: DataTypes.STRING, // Changed from DataTypes.UUID to DataTypes.STRING
      primaryKey: true,
      defaultValue: DataTypes.UUIDV4,
    },
    lastActivity: {
      type: DataTypes.JSON,
      allowNull: true,
    },

   

  });

  ChatRoom.associate = (models) => {
    ChatRoom.belongsToMany(models.Users, { through: 'UserChatRooms', as: 'members', foreignKey: 'chatRoomId' });
    ChatRoom.hasMany(models.Message, { as: 'messages', foreignKey: 'chatRoomId' });
  };
  

  return ChatRoom;
};