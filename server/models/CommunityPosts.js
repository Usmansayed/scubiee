module.exports = (sequelize, DataTypes) => {
  const CommunityPosts = sequelize.define('CommunityPosts', {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    community_id: {
      type: DataTypes.UUID,
      allowNull: false,
    },
    post_id: {
      type: DataTypes.UUID,
      allowNull: false,
    },
    date_posted: {
      type: DataTypes.DATE,
      defaultValue: DataTypes.NOW,
    },
    reposted_by: {
      type: DataTypes.STRING, // Matching Users model id type
      allowNull: true,
    },
    is_author_original: {
      type: DataTypes.BOOLEAN,
      defaultValue: true,
    },
    pinned: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    removed: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    meta: {
      type: DataTypes.JSON,
      allowNull: true,
      defaultValue: {},
    },
  }, {
    // Composite unique index to prevent duplicate posts in same community
    indexes: [
      {
        unique: true,
        fields: ['community_id', 'post_id']
      }
    ]
  });

  CommunityPosts.associate = (models) => {
    // Belongs to Community
    CommunityPosts.belongsTo(models.Communities, { 
      foreignKey: 'community_id',
      as: 'community',
      onDelete: 'CASCADE'
    });
    
    // Belongs to Post
    CommunityPosts.belongsTo(models.Post, { 
      foreignKey: 'post_id',
      as: 'post',
      onDelete: 'CASCADE'
    });
    
    // Belongs to User (for reposts)
    CommunityPosts.belongsTo(models.Users, { 
      foreignKey: 'reposted_by',
      as: 'reposter',
      onDelete: 'SET NULL'
    });
  };

  return CommunityPosts;
};
