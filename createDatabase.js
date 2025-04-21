require('dotenv').config();
const mysql = require('mysql2/promise');
const { Sequelize } = require('sequelize');

async function createDatabase() {
  try {
    // Connect to MySQL server without specifying a database
    const connection = await mysql.createConnection({
      host: process.env.DB_HOST,
      user: process.env.DB_USER,
      password: process.env.DB_PASS
    });
    
    console.log('Connected to MySQL server');
    
    // Create the database if it doesn't exist
    await connection.query(`CREATE DATABASE IF NOT EXISTS \`${process.env.DB_NAME}\``);
    console.log(`Database '${process.env.DB_NAME}' created or already exists`);
    
    await connection.end();
    
    return true;
  } catch (error) {
    console.error('Error creating database:', error);
    return false;
  }
}

/**
 * Sync models in the correct order to respect foreign key relationships
 * @param {Object} db - Object containing all Sequelize models
 * @param {boolean} force - Whether to drop tables before creating them
 */
async function syncModels(db, force = false) {
  try {
    console.log('Beginning table synchronization...');
    
    // Define the order of model creation to respect foreign key relationships
    // This array defines the precise order of tables to be created
    const modelCreationOrder = [
      'Users',         // Base table with no dependencies
      'Roles',         // Usually independent or depends on Users
      'Settings',      // Usually independent
      'Categories',    // Usually independent 
      'ChatRooms',     // Independent or depends on Users
      'Hashtags',      // Independent table
      'Posts',         // Depends on Users
      'Comments',      // Depends on Users AND Posts
      'Messages',      // Depends on Users and ChatRooms
      'Notifications', // Depends on Users
      'Follows',       // Depends on Users
      'CommentLikes',  // Depends on Users and Comments
      'PostLikes',     // Depends on Users and Posts
      'Queries',       // Depends on Users
      'Mentions',      // Depends on Posts and Users
      'PostHashtags',  // Depends on Posts and Hashtags
      'stories',       // Depends on Users
      'story_metadata',// Depends on stories
      'Reactions',     // Depends on Users and Messages
      'Shorts',        // Depends on Users
    ];
    
    // Get actual models that exist in the db object
    const existingModels = modelCreationOrder.filter(modelName => 
      db[modelName] && typeof db[modelName].sync === 'function'
    );
    
    // Track created tables to verify dependencies
    const createdTables = new Set();
    
    // Sync models in the order defined with better error handling
    console.log('Syncing models in dependency order:');
    for (const modelName of existingModels) {
      try {
        console.log(`Syncing ${modelName} table...`);
        await db[modelName].sync({ force });
        createdTables.add(modelName);
      } catch (error) {
        console.error(`Error syncing ${modelName}:`, error.message);
        // Continue to next model
      }
    }
    
    // Try to sync failed models again now that dependencies might be created
    console.log('Attempting to sync previously failed models...');
    for (const modelName of existingModels) {
      if (!createdTables.has(modelName) && db[modelName]) {
        try {
          console.log(`Retrying sync for ${modelName} table...`);
          await db[modelName].sync({ force });
          createdTables.add(modelName);
        } catch (error) {
          console.error(`Failed to sync ${modelName} on retry:`, error.message);
        }
      }
    }
    
    // Sync any remaining models that weren't in our predefined order
    console.log('Syncing remaining models:');
    for (const modelName in db) {
      if (
        modelName !== 'sequelize' && 
        modelName !== 'Sequelize' && 
        !createdTables.has(modelName) &&
        typeof db[modelName]?.sync === 'function'
      ) {
        try {
          console.log(`Syncing ${modelName} table...`);
          await db[modelName].sync({ force });
          createdTables.add(modelName);
        } catch (error) {
          console.error(`Error syncing ${modelName}:`, error.message);
        }
      }
    }
    
    console.log(`Successfully synchronized ${createdTables.size} tables`);
    return true;
  } catch (error) {
    console.error('Error in database synchronization process:', error);
    throw error;
  }
}

module.exports = { createDatabase, syncModels };
