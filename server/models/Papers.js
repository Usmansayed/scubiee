module.exports = (sequelize, DataTypes) => {
  const Papers = sequelize.define("Papers", {
    id: {
      type: DataTypes.STRING,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    title: {
      type: DataTypes.STRING(35),
      allowNull: false,
    },    description: {
      type: DataTypes.TEXT,
      allowNull: false,
    },
    authorId: {
      type: DataTypes.STRING,
      allowNull: false,
      references: {
        model: 'Users',
        key: 'id'
      }
    },
    deliveryTime: {
      type: DataTypes.STRING,
      allowNull: false,
    },
    postCount: {
      type: DataTypes.INTEGER,
      allowNull: false,
      defaultValue: 30,
    },
    deleted : {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    status: {
      type: DataTypes.ENUM('active', 'paused', 'archived'),
      defaultValue: 'active',
    },
    // AI-generated metadata from Google GenAI
    metadata: {
      type: DataTypes.JSON,
      allowNull: true,
      // This will store the structured JSON response from Google GenAI
      // Including: summary, primary_topics, secondary_topics, regions, etc.
    },    // Processing status
    processingStatus: {
      type: DataTypes.ENUM('pending', 'processing', 'completed', 'failed'),
      defaultValue: 'pending',
    },    // Error message if processing fails
    processingError: {
      type: DataTypes.TEXT,
      allowNull: true,
    },
  });

  Papers.associate = (models) => {
    Papers.belongsTo(models.Users, {
      foreignKey: 'authorId',
      as: 'author'
    });
  };

  return Papers;
};