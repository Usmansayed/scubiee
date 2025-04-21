// Mention Model
module.exports = (sequelize) => {
    const Mention = sequelize.define('Mention', {}, { timestamps: false });
  
    Mention.associate = (models) => {
      models.Post.belongsToMany(models.Users, { through: Mention, as: 'mentionedUsers', foreignKey: 'postId' });
      models.Users.belongsToMany(models.Post, { through: Mention, as: 'mentionedInPosts', foreignKey: 'userId' });
    };
  
    return Mention;
  };
  