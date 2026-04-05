module.exports = (sequelize, DataTypes) => {
  const UserReports = sequelize.define("UserReports", {
    userId: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    targetId: { // Changed from target_id to targetId
      type: DataTypes.STRING,
      allowNull: false,
    },
    reporting: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    reason: {
      type: DataTypes.STRING,
      allowNull: false,
    }
  });
  return UserReports;
};