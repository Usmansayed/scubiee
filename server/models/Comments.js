module.exports = (sequelize, DataTypes) => {
    const Comment = sequelize.define("Comment", {
      id: {
        type: DataTypes.UUID,
        defaultValue: DataTypes.UUIDV4, // Generate UUID automatically
        primaryKey: true,
      },
      postId: {
        type: DataTypes.UUID,
        allowNull: false,
      },
      authorId: {
        type: DataTypes.STRING, // Ensure this matches the Users model's id type (STRING)
        allowNull: false,
      },
      content: {
        type: DataTypes.TEXT,
        allowNull: false,
      },
      likes: {
        type: DataTypes.INTEGER,
        defaultValue: 0,
      },
      isPinned: {
        type: DataTypes.BOOLEAN,
        defaultValue: false,
      },
      parentId: {
        type: DataTypes.UUID,
        allowNull: true,
        
        onDelete: 'CASCADE',
      },
      replyingto: {
        type: DataTypes.STRING, 
        allowNull: true,
      },
    });
    
  
    // Associations
    Comment.associate = (models) => {
      Comment.belongsTo(models.Post, {
        foreignKey: "postId",
        onDelete: "CASCADE",
      });
      Comment.belongsTo(models.Users, {
        foreignKey: "authorId", // Ensure this foreign key exists in the `Users` model
        onDelete: "CASCADE",
      });
    };
  
    return Comment;
  };
  