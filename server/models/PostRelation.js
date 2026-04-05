module.exports = (sequelize, DataTypes) => {
  const PostRelation = sequelize.define('PostRelation', {
    ancestorId: {
      type: DataTypes.UUID,
      allowNull: false,
      references: {
        model: 'Posts',
        key: 'id',
      },
      onDelete: 'CASCADE',
      onUpdate: 'CASCADE',
    },
    descendantId: {
      type: DataTypes.UUID,
      allowNull: false,
      references: {
        model: 'Posts',
        key: 'id',
      },
      onDelete: 'CASCADE',
      onUpdate: 'CASCADE',
    },
    depth: {
      type: DataTypes.INTEGER,
      allowNull: false,
    },
  });

  return PostRelation;
};