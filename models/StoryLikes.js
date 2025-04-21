module.exports = (sequelize, DataTypes) => {
    const StoryLike = sequelize.define(
      "StoryLike",
      {
        storyId: {
          type: DataTypes.UUID,
          allowNull: false,
          references: {
            model: 'stories',
            key: 'storyId'
          }
        },
        userId: {
          type: DataTypes.STRING,
          allowNull: false,
          references: {
            model: 'Users',
            key: 'id'
          }
        }
      },
      {
        tableName: "story_likes",
        timestamps: true, // This will add createdAt and updatedAt columns
      }
    );
  
    StoryLike.associate = (models) => {
      StoryLike.belongsTo(models.Story, {
        foreignKey: 'storyId',
        as: 'story'
      });
      StoryLike.belongsTo(models.Users, {
        foreignKey: 'userId',
        as: 'liker'
      });
    };
  
    return StoryLike;
  };