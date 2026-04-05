//// filepath: /c:/Users/usman/Videos/Real Projects/server/models/StoryMetaData.js
module.exports = (sequelize, DataTypes) => {
  const StoryMetaData = sequelize.define(
    "StoryMetaData",
    {
      metadata_id: {
        type: DataTypes.UUID,
        defaultValue: DataTypes.UUIDV4,
        primaryKey: true,
      },
      story_id: {
        type: DataTypes.UUID,
        allowNull: false,
        references: {
          model: "stories", // Must match Story’s tableName
          key: "storyId",
        },
        onDelete: "CASCADE",
      },
      element_type: {
        type: DataTypes.ENUM("text", "mention", "link", "hashtag", "image", "video","post"),
        allowNull: false,
      },
      background_color: {
        type: DataTypes.STRING,
        allowNull: true,
      },
      text_color: {
        type: DataTypes.STRING,
        allowNull: true,
      },
      content: {
        type: DataTypes.TEXT,
        allowNull: false,
      },
      position_x: DataTypes.FLOAT,
      position_y: DataTypes.FLOAT,
      width: DataTypes.FLOAT,
      height: DataTypes.FLOAT,
      rotation: {
        type: DataTypes.FLOAT,
        defaultValue: 0,
      },
      scale: {
        type: DataTypes.FLOAT,
        defaultValue: 1,
      },
      isPost: {
        type: DataTypes.BOOLEAN,
        defaultValue: false,
      },
      offset_x: {
        type: DataTypes.FLOAT,
        defaultValue: 0,
      },
      offset_y: {
        type: DataTypes.FLOAT,
        defaultValue: 0,
      },
      z_index: {
        type: DataTypes.INTEGER,
        allowNull: false,
      },
      scaled:{
        type: DataTypes.BOOLEAN,
        defaultValue: false,
      }
    },
    {
      tableName: "story_metadata",
      timestamps: true,
    }
  );

  StoryMetaData.associate = (models) => {
    StoryMetaData.belongsTo(models.Story, {
      foreignKey: "story_id",
    });
  };

  return StoryMetaData;
};