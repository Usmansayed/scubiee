module.exports = (sequelize, DataTypes) => {
  const Queries = sequelize.define("Queries", {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    userId: {
      type: DataTypes.STRING,
      allowNull: true, // Will be filled from token for authenticated users
    },
    name: {
      type: DataTypes.STRING,
      allowNull: true, // Now optional since we can get it from the user data
    },
    email: {
      type: DataTypes.STRING,
      allowNull: true, // Now optional since we can get it from the user data
      validate: {
        isEmail: true,
      },
    },
    subject: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    category: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    message: {
      type: DataTypes.TEXT,
      allowNull: false,
    },
    status: {
      type: DataTypes.ENUM('pending', 'in_progress', 'resolved', 'closed'),
      defaultValue: 'pending',
    },
    adminNotes: {
      type: DataTypes.TEXT,
      allowNull: true,
    },
    priority: {
      type: DataTypes.ENUM('low', 'medium', 'high', 'urgent'),
      defaultValue: 'medium',
    },
  });

  // Associate Queries with Users (optional but useful for tracking)
  Queries.associate = (models) => {
    Queries.belongsTo(models.Users, {
      foreignKey: 'userId',
      as: 'user',
      onDelete: 'SET NULL'
    });
  };

  return Queries;
};
