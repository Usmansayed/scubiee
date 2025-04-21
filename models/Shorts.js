module.exports = (sequelize, DataTypes) => {
    const Shorts = sequelize.define('Shorts', {
      id: {
        type: DataTypes.UUID,
        defaultValue: DataTypes.UUIDV4,
        primaryKey: true,
      },
      media: {
        type: DataTypes.STRING,
        allowNull: false,
      },
      content: {
        type: DataTypes.TEXT,
        allowNull: false,
      },
      authorId: {
        type: DataTypes.STRING,
        allowNull: false,
      },
      shared: {
        type: DataTypes.INTEGER,
        defaultValue: 0,
      },
      bookmarks: {
        type: DataTypes.INTEGER,
        defaultValue: 0,
      },
      views: {
        type: DataTypes.INTEGER,
        defaultValue: 0,
      },
      likes: {
        type: DataTypes.INTEGER,
        defaultValue: 0,
      },
    });
  
    Shorts.associate = (models) => {
      // Associate Short with Users model (modify alias and onDelete as needed)
      Shorts.belongsTo(models.Users, { foreignKey: 'authorId', as: 'author', onDelete: 'CASCADE' });
    };
  
    return Shorts;
  };