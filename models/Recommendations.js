module.exports = (sequelize, DataTypes) => {
    const Recommendations = sequelize.define('Recommendations', {
      id: {
        type: DataTypes.INTEGER,
        primaryKey: true,
        autoIncrement: true,
      },
      userId: {
        type: DataTypes.STRING, // Foreign key to Users table (match Users.id)
        allowNull: false,
      },
      postId: {
        type: DataTypes.UUID, // Foreign key to Posts table
        allowNull: false,
      },
    });
  
    Recommendations.associate = (models) => {
      Recommendations.belongsTo(models.Users, { foreignKey: 'userId', onDelete: 'CASCADE', onUpdate: 'CASCADE' });
      Recommendations.belongsTo(models.Post, { foreignKey: 'postId', onDelete: 'CASCADE', onUpdate: 'CASCADE' });
    };
  
    return Recommendations;
  };
  