module.exports = (sequelize, DataTypes) => {
  const Story = sequelize.define(
    "Story",
    {
      storyId: {
        type: DataTypes.UUID,
        defaultValue: DataTypes.UUIDV4,
        primaryKey: true,
      },
      userId: {
        type: DataTypes.STRING,
        allowNull: false,
      },
       width: DataTypes.FLOAT,
      height: DataTypes.FLOAT,
      bgcolor: {
        type: DataTypes.STRING,
        allowNull: true,
      },
    },
    {
      tableName: "stories",
      timestamps: true,
    }
  );

  Story.associate = (models) => {
    Story.hasMany(models.StoryMetaData, { 
      foreignKey: "story_id",
      as: "metadata", // Add this alias
      onDelete: "CASCADE"
    });
    Story.belongsTo(models.Users, {
      foreignKey: 'userId',
      as: 'user'
    });
  };

  return Story;
};