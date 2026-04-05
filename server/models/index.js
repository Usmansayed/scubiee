'use strict';

const fs = require('fs');
const path = require('path');
const Sequelize = require('sequelize');
const process = require('process');
const basename = path.basename(__filename);
const env = process.env.NODE_ENV || 'development';
const config = require(__dirname + '/../config/config.js')[env];
const db = {};

let sequelize;
if (config.use_env_variable) {
  sequelize = new Sequelize(process.env[config.use_env_variable], config);
} else {
  sequelize = new Sequelize(config.database, config.username, config.password, config);
}

// Enhance connection error handling with reconnection logic
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

function connectWithRetry() {
  return sequelize
    .authenticate()
    .then(() => {
      console.log('Database connection established successfully.');
      reconnectAttempts = 0;
    })
    .catch(err => {
      console.error('Unable to connect to the database:', err);
      
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        const delay = Math.min(1000 * (reconnectAttempts ** 2), 30000);
        console.log(`Retrying connection in ${delay/1000} seconds... (Attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`);
        
        setTimeout(connectWithRetry, delay);
      } else {
        console.error('Max reconnection attempts reached. Please check database configuration.');
        // In production, you might want to implement graceful shutdown here
      }
    });
}

connectWithRetry();

fs
  .readdirSync(__dirname)
  .filter(file => {
    return (
      file.indexOf('.') !== 0 &&
      file !== basename &&
      file.slice(-3) === '.js' &&
      file.indexOf('.test.js') === -1
    );
  })
  .forEach(file => {
    const model = require(path.join(__dirname, file))(sequelize, Sequelize.DataTypes);
    db[model.name] = model;
  });

Object.keys(db).forEach(modelName => {
  if (db[modelName].associate) {
    db[modelName].associate(db);
  }
});

db.sequelize = sequelize;
db.Sequelize = Sequelize;

module.exports = db;
