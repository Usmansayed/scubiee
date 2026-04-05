module.exports = (sequelize, DataTypes) => {
    const PostSaved = sequelize.define('PostSaved', {
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
  
    PostSaved.associate = (models) => {
      PostSaved.belongsTo(models.Users, { foreignKey: 'userId', onDelete: 'CASCADE' });
      PostSaved.belongsTo(models.Post, { foreignKey: 'postId', onDelete: 'CASCADE' });
    };
  
    return PostSaved;
  };