module.exports = (sequelize, DataTypes) => {
    const CommentLike = sequelize.define("CommentLike", {
      userId: {
        type: DataTypes.STRING,
        allowNull: false,
        references: {
          model: 'Users',
          key: 'id'
        },
        onDelete: 'CASCADE'
      },
      commentId: {
        type: DataTypes.UUID,
        allowNull: false,
        references: {
          model: 'Comments',
          key: 'id'
        },
        onDelete: 'CASCADE'
      }
    }, {
      indexes: [
        {
          unique: true,
          fields: ['userId', 'commentId']
        }
      ]
    });
  
    CommentLike.associate = (models) => {
      CommentLike.belongsTo(models.Users, {
        foreignKey: 'userId'
      });
      CommentLike.belongsTo(models.Comment, {
        foreignKey: 'commentId'
      });
    };
  
    return CommentLike;
  };