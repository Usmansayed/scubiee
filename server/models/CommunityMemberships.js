module.exports = (sequelize, DataTypes) => {
  const CommunityMemberships = sequelize.define('CommunityMemberships', {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    community_id: {
      type: DataTypes.UUID,
      allowNull: false,
    },
    user_id: {
      type: DataTypes.STRING, // Matching Users model id type
      allowNull: false,
    },
    role: {
      type: DataTypes.ENUM('member', 'admin', 'moderator'),
      defaultValue: 'member',
    },
    status: {
      type: DataTypes.ENUM('active', 'left', 'banned'),
      defaultValue: 'active',
    },
    joined_at: {
      type: DataTypes.DATE,
      defaultValue: DataTypes.NOW,
    },
  }, {
    // Composite unique index to prevent duplicate memberships
    indexes: [
      {
        unique: true,
        fields: ['community_id', 'user_id']
      }
    ]
  });

  CommunityMemberships.associate = (models) => {
    // Belongs to Community
    CommunityMemberships.belongsTo(models.Communities, { 
      foreignKey: 'community_id',
      as: 'community',
      onDelete: 'CASCADE'
    });
    
    // Belongs to User
    CommunityMemberships.belongsTo(models.Users, { 
      foreignKey: 'user_id',
      as: 'user',
      onDelete: 'CASCADE'
    });
  };

  return CommunityMemberships;
};
