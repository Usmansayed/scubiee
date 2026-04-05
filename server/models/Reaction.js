module.exports = (sequelize, DataTypes) => {
  const Reaction = sequelize.define('Reaction', {
    id: {
      type: DataTypes.INTEGER,
      primaryKey: true,
      autoIncrement: true
    },
    reaction: {
      type: DataTypes.STRING,
      allowNull: false
    },
    senderId: {
      type: DataTypes.STRING,
      allowNull: false
    },
    messageId: {
      type: DataTypes.INTEGER,
      allowNull: false
    },
    // New timestamp column indicating when the reaction was read
    read: {
      type: DataTypes.BOOLEAN,
      defaultValue: false,
    }
  });

  Reaction.associate = (models) => {
    // Link reactions to messages
    Reaction.belongsTo(models.Message, {
      foreignKey: 'messageId',
      onDelete: 'CASCADE',
      onUpdate: 'CASCADE'
    });

    // Reference the user for the sender
    Reaction.belongsTo(models.Users, {
      foreignKey: 'senderId',
      onDelete: 'CASCADE',
      onUpdate: 'CASCADE'
    });
  };

  return Reaction;
};