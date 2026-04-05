
  // Intermediate Table for Post and Hashtag Relationship
  module.exports = (sequelize,DataTypes) => {
    const PostHashtags = sequelize.define('PostHashtags', {
      id: {
        type: DataTypes.INTEGER,
        primaryKey: true,
        autoIncrement: true,
      },
      postId: {
        type: DataTypes.UUID,
        allowNull: false,
        references: {
          model: 'Posts', // Name of the target table
          key: 'id',
        },
      },
      hashtagId: {
        type: DataTypes.INTEGER,
        allowNull: false,
        references: {
          model: 'Hashtags', // Name of the target table
          key: 'id',
        },
      },
    }, {
      timestamps: true, // optional if you want createdAt and updatedAt fields
    });
  
    return PostHashtags;
  };
  