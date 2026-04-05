const { Sequelize } = require('sequelize');
const config = require('./config/config.js');

// Initialize Sequelize with your database configuration
const sequelize = new Sequelize(config.database, config.username, config.password, {
  host: config.host,
  dialect: config.dialect,
  logging: console.log
});

async function runMigration() {
  try {
    console.log('Starting database migration...');
    
    // Test connection
    await sequelize.authenticate();
    console.log('Database connection established successfully.');

    const transaction = await sequelize.transaction();
    
    try {
      // Step 1: Remove the old access_type column if it exists
      console.log('Step 1: Removing access_type column if it exists...');
      try {
        await sequelize.query('ALTER TABLE Communities DROP COLUMN access_type', { transaction });
        console.log('✓ Removed access_type column');
      } catch (error) {
        console.log('ℹ access_type column does not exist or already removed');
      }

      // Step 2: Update existing data to match new enum values before changing schema
      console.log('Step 2: Updating existing post_access_type values...');
      const [results, metadata] = await sequelize.query(`
        UPDATE Communities 
        SET post_access_type = CASE 
          WHEN post_access_type = 'creator_only' THEN 'creator'
          WHEN post_access_type = 'selected_users' THEN 'moderators'
          ELSE post_access_type
        END
      `, { transaction });
      console.log(`✓ Updated ${metadata.affectedRows || 0} communities`);

      // Step 3: Update the enum constraint
      console.log('Step 3: Updating post_access_type enum constraint...');
      await sequelize.query(`
        ALTER TABLE Communities 
        MODIFY COLUMN post_access_type ENUM('everyone', 'creator', 'moderators') 
        NOT NULL DEFAULT 'everyone'
      `, { transaction });
      console.log('✓ Updated post_access_type enum');

      // Step 4: Update CommunityMemberships roles
      console.log('Step 4: Updating CommunityMemberships roles...');
      const [roleResults, roleMetadata] = await sequelize.query(`
        UPDATE CommunityMemberships 
        SET role = 'moderator' 
        WHERE role = 'contributor'
      `, { transaction });
      console.log(`✓ Updated ${roleMetadata.affectedRows || 0} membership roles`);

      await transaction.commit();
      console.log('🎉 Migration completed successfully!');
      
    } catch (error) {
      await transaction.rollback();
      console.error('❌ Migration failed:', error);
      throw error;
    }
    
  } catch (error) {
    console.error('❌ Database connection failed:', error);
  } finally {
    await sequelize.close();
    console.log('Database connection closed.');
  }
}

// Run the migration
runMigration();
