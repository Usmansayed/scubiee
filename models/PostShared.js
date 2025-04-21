module.exports = (sequelize, DataTypes) => {
    const PostShared = sequelize.define('PostShared', {
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
    });
  
    PostShared.associate = (models) => {
        PostShared.belongsTo(models.Users, { foreignKey: 'userId', onDelete: 'CASCADE' });
        PostShared.belongsTo(models.Post, { foreignKey: 'postId', onDelete: 'CASCADE' });
    };
  
    return PostShared;
  };