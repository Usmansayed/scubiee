module.exports = (sequelize, DataTypes) => {
  const UserChatRooms = sequelize.define("UserChatRooms", {
    userId: {
      type: DataTypes.STRING,
      references: {
        model: 'Users',
        key: 'id',
      },
    },
    chatRoomId: {
      type: DataTypes.STRING,
      references: {
        model: 'ChatRooms',
        key: 'id',
      },
    },
    lastActivity: {
      type: DataTypes.STRING,
      allowNull: true,
    },
  });

  UserChatRooms.associate = (models) => {
    UserChatRooms.belongsTo(models.Users, { foreignKey: 'userId' });
    UserChatRooms.belongsTo(models.ChatRoom, { foreignKey: 'chatRoomId', as: 'chatRoom' }); // Add alias here
  };
  

  return UserChatRooms;
};
