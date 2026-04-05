// Hashtag Model
module.exports = (sequelize, DataTypes) => {
    const Hashtag = sequelize.define('Hashtag', {
      id: {
        type: DataTypes.INTEGER,
        primaryKey: true,
        autoIncrement: true,
      },
      name: {
        type: DataTypes.STRING,
        allowNull: false,
        unique: true,
      },
      Count: {
        type: DataTypes.INTEGER,
        allowNull: false,
      },
      
    });
  
    Hashtag.associate = (models) => {
      Hashtag.belongsToMany(models.Post, { through: 'PostHashtags', foreignKey: 'hashtagId' });
    };
  
    return Hashtag;
  };
  