module.exports = (sequelize, DataTypes) => {
  const UserInteractions = sequelize.define('UserInteractions', {
    id: {
      type: DataTypes.INTEGER,
      autoIncrement: true,
      primaryKey: true,
    },
    userId: {
      type: DataTypes.STRING,
      allowNull: false,
      references: {
        model: 'Users',
        key: 'id',
      },
      onDelete: 'CASCADE',
      onUpdate: 'CASCADE',
    },
    postId: {
      type: DataTypes.UUID,
      allowNull: false,
      references: {
        model: 'Posts',
        key: 'id',
      },
      onDelete: 'CASCADE',
      onUpdate: 'CASCADE',
    },
    interactionType: {
      type: DataTypes.ENUM('liked', 'commented', 'shared', 'saved', 'recommended', 'disliked', 'read', 'reported'),
      allowNull: false,
    },
    createdAt: {
      type: DataTypes.DATE,
      allowNull: false,
      defaultValue: DataTypes.NOW,
    },
    updatedAt: {
      type: DataTypes.DATE,
      allowNull: false,
      defaultValue: DataTypes.NOW,
    },
  }, {
    tableName: 'UserInteractions',
    timestamps: true, // Ensure timestamps are enabled
    indexes: [
      {
        unique: true,
        fields: ['userId', 'postId', 'interactionType'],
        name: 'unique_user_post_interaction'
      }
    ]
  });

  UserInteractions.associate = (models) => {
    UserInteractions.belongsTo(models.Users, { foreignKey: 'userId', onDelete: 'CASCADE' });
    UserInteractions.belongsTo(models.Post, { foreignKey: 'postId', onDelete: 'CASCADE' });
  };

  return UserInteractions;
};