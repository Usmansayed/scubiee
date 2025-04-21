module.exports = (sequelize, DataTypes) => {
  const Notifications = sequelize.define("Notifications", {
    id: {
      type: DataTypes.UUID,
      defaultValue: DataTypes.UUIDV4,
      primaryKey: true,
    },
    user_id: {
      type: DataTypes.STRING, // Changed to STRING to match Users model
      allowNull: false,
    },
    sender_id: {
      type: DataTypes.STRING, // Changed to STRING to match Users model
      allowNull: false,
    },
    type: {
      type: DataTypes.STRING,
      allowNull: false,
      validate: {
        isIn: [['like', 'comment', 'follow', 'mention', 'reply', 'comment_like','reply_like']] // Added 'comment_like'
      }
    },
    reference_id: {
      type: DataTypes.UUID, // Changed to UUID since Post and Comment use UUID
      allowNull: true,
    },
    reference_type: {
      type: DataTypes.STRING,
      allowNull: true,
    },
    message: {
      type: DataTypes.STRING,
      allowNull: true,
    },
    is_read: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    },
    createdAt: {
      type: DataTypes.DATE,
      defaultValue: DataTypes.NOW,
    }
  }, {
    timestamps: true,
    createdAt: 'createdAt',
    updatedAt: false
  });

  // Rest of the model definition remains the same
  Notifications.associate = (models) => {
    // Association with the recipient user
    Notifications.belongsTo(models.Users, {
      foreignKey: 'user_id',
      as: 'recipient'
    });

    // Association with the sender user
    Notifications.belongsTo(models.Users, {
      foreignKey: 'sender_id',
      as: 'sender'
    });
  };

  return Notifications;
};