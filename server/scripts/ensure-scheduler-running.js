/**
 * This script ensures that the paper scheduler is running.
 * It can be included at the end of server initialization or run as a separate process.
 */
const paperScheduler = require('../schedulers/paperScheduler');
const moment = require('moment-timezone');

async function ensureSchedulerRunning() {
  try {
    console.log(`📅 Current IST time: ${moment().tz('Asia/Kolkata').format('YYYY-MM-DD HH:mm:ss')}`);
    
    // Check if scheduler is already running
    const status = paperScheduler.getStatus();
    console.log('📊 Current scheduler status:', status);
    
    if (status.cronJobScheduled) {
      console.log('✅ Paper scheduler is already running. No action needed.');
      return true;
    }
    
    // Start the scheduler if it's not running
    console.log('🔄 Starting paper scheduler...');
    const startResult = paperScheduler.start();
    
    if (startResult) {
      console.log('✅ Scheduler started successfully!');
      
      // Force an immediate check for any missed papers
      console.log('🔍 Running immediate check for any missed papers...');
      await paperScheduler.triggerManualGeneration();
      
      return true;
    } else {
      console.error('❌ Failed to start scheduler.');
      return false;
    }
  } catch (error) {
    console.error('❌ Error ensuring scheduler is running:', error);
    return false;
  }
}

// When run directly as a script
if (require.main === module) {
  ensureSchedulerRunning()
    .then(result => {
      if (!result) {
        console.log('⚠️ Failed to ensure scheduler is running.');
        process.exit(1);
      }
    })
    .catch(err => {
      console.error('💥 Fatal error:', err);
      process.exit(1);
    });
}

module.exports = ensureSchedulerRunning;
