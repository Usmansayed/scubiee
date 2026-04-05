module.exports = (sequelize, DataTypes) => {
    const StoryView = sequelize.define(
      "StoryView",
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
        tableName: "story_views",
        timestamps: true, // This will add createdAt and updatedAt columns
      }
    );
  
    StoryView.associate = (models) => {
      StoryView.belongsTo(models.Story, {
        foreignKey: 'storyId',
        as: 'story'
      });
      StoryView.belongsTo(models.Users, {
        foreignKey: 'userId',
        as: 'viewer'
      });
    };
  
    return StoryView;
  };