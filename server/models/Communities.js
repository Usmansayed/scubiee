module.exports = (sequelize, DataTypes) => {
  const Communities = sequelize.define('Communities', {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    name: {
      type: DataTypes.STRING,
      allowNull: false,
      unique: true,
    },
    description: {
      type: DataTypes.TEXT,
      allowNull: true,
    },
    hot_topics: {
      type: DataTypes.JSON,
      allowNull: true,
      defaultValue: [],
    },    post_access_users: {
      type: DataTypes.JSON,
      allowNull: true,
      defaultValue: [],
      comment: 'Only stores moderator IDs when post_access_type is "moderators", empty otherwise'
    },
    post_access_type: {
      type: DataTypes.ENUM('everyone', 'creator', 'moderators'),
      defaultValue: 'everyone',
      allowNull: false,
    },
    creator_id: {
      type: DataTypes.STRING, // Matching Users model id type
      allowNull: false,
    },
    member_count: {
      type: DataTypes.INTEGER,
      defaultValue: 0,
    },
    visibility: {
      type: DataTypes.ENUM('public', 'private', 'restricted'),
      defaultValue: 'public',
    },
    banner_url: {
      type: DataTypes.STRING,
      allowNull: true,
    },
    profile_icon: {
      type: DataTypes.STRING,
      allowNull: true,
    },
    summary: {
      type: DataTypes.TEXT,
      allowNull: true
    },
  });

  Communities.associate = (models) => {
    // Creator relationship
    Communities.belongsTo(models.Users, { 
      foreignKey: 'creator_id', 
      as: 'creator',
      onDelete: 'CASCADE' 
    });
    
    // Many-to-many relationship with Users through CommunityMemberships
    Communities.belongsToMany(models.Users, { 
      through: 'CommunityMemberships',
      foreignKey: 'community_id',
      otherKey: 'user_id',
      as: 'members'
    });
    
    // Posts relationship through CommunityPosts
    Communities.belongsToMany(models.Post, { 
      through: 'CommunityPosts',
      foreignKey: 'community_id',
      otherKey: 'post_id',
      as: 'posts'
    });
    
    // Direct relationships
    Communities.hasMany(models.CommunityMemberships, { 
      foreignKey: 'community_id',
      as: 'memberships',
      onDelete: 'CASCADE'
    });
    
    Communities.hasMany(models.CommunityPosts, { 
      foreignKey: 'community_id',
      as: 'community_posts',
      onDelete: 'CASCADE'
    });
  };

  return Communities;
};
