module.exports = (sequelize, DataTypes) => {
  const PostLike = sequelize.define('PostLike', {
    userId: {
      type: DataTypes.STRING,
      allowNull: false,
      references: {
        model: 'Users',
        key: 'id',
      },
      onDelete: 'CASCADE',
    },
    postId: {
      type: DataTypes.UUID,
      allowNull: false,
      references: {
        model: 'Posts',
        key: 'id',
      },
      onDelete: 'CASCADE',
    }
  }, {
    tableName: 'PostLikes', // Explicitly set table name
    timestamps: true
  });

  PostLike.associate = (models) => {
    PostLike.belongsTo(models.Users, { foreignKey: 'userId' });
    PostLike.belongsTo(models.Post, { foreignKey: 'postId' });
  };

  return PostLike;
};