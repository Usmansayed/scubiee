/**
 * This script forces the immediate generation of papers for the current hour.
 * Useful when you need to manually trigger paper generation due to a schedule miss.
 */
const paperScheduler = require('../schedulers/paperScheduler');
const moment = require('moment-timezone');
const { db } = require('../models');

async function forceGeneratePapers() {
  try {
    console.log(`📅 Current IST time: ${moment().tz('Asia/Kolkata').format('YYYY-MM-DD HH:mm:ss')}`);
    
    // Check database connection
    console.log('🔌 Testing database connection...');
    try {
      await db.sequelize.authenticate();
      console.log('✅ Database connection established successfully.');
    } catch (error) {
      console.error('❌ Database connection error:', error);
      return false;
    }
    
    // Check if scheduler is already running
    const status = paperScheduler.getStatus();
    console.log('🔎 Current scheduler status:', JSON.stringify(status, null, 2));
    
    if (!status.cronJobScheduled) {
      console.log('🔄 Starting paper scheduler...');
      const startResult = paperScheduler.start();
      if (startResult) {
        console.log('✅ Paper Scheduler started successfully');
      } else {
        console.error('❌ Failed to start scheduler.');
        return false;
      }
    }
    
    // Force immediate generation regardless of the normal schedule
    console.log('🚀 Manually triggering paper generation now...');
    await paperScheduler.triggerManualGeneration();
    
    return true;
  } catch (error) {
    console.error('❌ Error forcing paper generation:', error);
    return false;
  }
}

// When run directly as a script
if (require.main === module) {
  forceGeneratePapers()
    .then(result => {
      if (!result) {
        console.log('⚠️ Failed to force paper generation.');
        process.exit(1);
      }
    })
    .catch(err => {
      console.error('💥 Fatal error:', err);
      process.exit(1);
    });
}

module.exports = forceGeneratePapers;
