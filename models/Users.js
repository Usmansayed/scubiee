module.exports = (sequelize, DataTypes) => {
  const Users = sequelize.define("Users", {
    id: {
      type: DataTypes.STRING, // Changed from DataTypes.UUID to DataTypes.STRING
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    username: {
      type: DataTypes.STRING,
      allowNull: false,
      unique: true,
    },
    firstName: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    lastName: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    email: {
      type: DataTypes.STRING,
      allowNull: false,
      unique: true,
    },
    profilePicture: {
      type: DataTypes.STRING,
      allowNull: true,
    },
    coverImage: {
      type: DataTypes.STRING,
      allowNull: true,
    },
   
    Verified:{
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    }, 
    posts: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    followers: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    following: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    Bio: {
      type: DataTypes.TEXT,
      allowNull: true,
    }, 
    SocialMedia:{
      type: DataTypes.JSON,
      allowNull: true,
    },
     isOnline: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    intrest: {
      type: DataTypes.JSON,
      allowNull: false,
     
    },
    badges: {
      type: DataTypes.JSON,
      allowNull: true,
     
    },


  });

  Users.associate = (models) => {
    Users.belongsToMany(models.ChatRoom, { through: 'UserChatRooms', as: 'rooms', foreignKey: 'userId' });
    Users.hasMany(models.Message, { as: 'messages', foreignKey: 'senderId' });
    Users.hasMany(models.Story, {
      foreignKey: 'userId',
      as: 'Stories'
    });
  };

  return Users;
};  