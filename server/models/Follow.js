module.exports = (sequelize, DataTypes) => {
    const Follow = sequelize.define("Follow", {
      followerId: {
        type: DataTypes.STRING,  // Assuming you're using STRING as the userId type
        allowNull: false,
        references: {
          model: "Users",  // References the Users table
          key: "id",
        },
      },
      followingId: {
        type: DataTypes.STRING,
        allowNull: false,
        references: {
          model: "Users",  // References the Users table
          key: "id",
        },
      },
    });
  
    Follow.associate = (models) => {
      Follow.belongsTo(models.Users, { as: "follower", foreignKey: "followerId" });
      Follow.belongsTo(models.Users, { as: "following", foreignKey: "followingId" });
    };
  
    return Follow;
  };
  