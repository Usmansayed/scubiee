module.exports = (sequelize, DataTypes) => {
  const Post = sequelize.define('Post', {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    content: {
      type: DataTypes.TEXT,
      allowNull: false,
    },
    authorId: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    media: {
      type: DataTypes.JSON,
      allowNull: true,
    },
    description: {
      type: DataTypes.STRING,
      allowNull: true,
    },
  
    shared: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    bookmarks: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    views: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    likes: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
 
    recommendedby: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    comments: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    isShort: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    categories: {
      type: DataTypes.JSON,
      allowNull: false,
     
    },
    location: {
      type: DataTypes.JSON,
      allowNull: true,
     
    },
 
  });

  Post.associate = (models) => {
    Post.belongsTo(models.Post, { foreignKey: 'parentId', as: 'ParentPost', onDelete: 'SET NULL' });
    Post.hasMany(models.Post, { foreignKey: 'parentId', as: 'ChildPosts', onDelete: 'SET NULL' });
    Post.belongsTo(models.Users, { foreignKey: 'authorId', as: 'author', onDelete: 'CASCADE' }); // Added alias 'author'
    Post.hasMany(models.Comment, { foreignKey: 'postId', onDelete: 'CASCADE' });
    Post.belongsToMany(models.Hashtag, { through: 'PostHashtags', foreignKey: 'postId' });
    Post.hasMany(models.PostRelation, { foreignKey: 'ancestorId', as: 'Ancestors' });
    Post.hasMany(models.PostRelation, { foreignKey: 'descendantId', as: 'Descendants' });
  };

  return Post;
};