module.exports = (sequelize, DataTypes) => {
  const PostView = sequelize.define('PostView', {
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
    timestamps: true, // Ensure timestamps are enabled
  });

  PostView.associate = (models) => {
    PostView.belongsTo(models.Users, { foreignKey: 'userId', onDelete: 'CASCADE' });
    PostView.belongsTo(models.Post, { foreignKey: 'postId', onDelete: 'CASCADE' });
  };

  return PostView;
};