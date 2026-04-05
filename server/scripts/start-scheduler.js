// This script manually starts the paper scheduler
// Use it when the scheduler isn't starting automatically with the server
// Can be run with: node scripts/start-scheduler.js

const paperScheduler = require('../schedulers/paperScheduler');
const { Papers, PaperPosts } = require('../models');

async function startScheduler() {
  try {
    console.log('🧪 [TEST] Checking database connection...');
    // Test database connection
    await Papers.findOne();
    console.log('✅ [TEST] Database connection successful');

    // Start the scheduler
    paperScheduler.start();
    
    console.log('✅ [TEST] Scheduler status:', paperScheduler.getStatus());
    
    // Trigger immediate paper generation
    console.log('🚀 [TEST] Triggering manual paper generation...');
    await paperScheduler.triggerManualGeneration();
    
    console.log('✅ [TEST] Script completed - The scheduler is now running in the background');
    console.log('📋 [TEST] You can keep the server running to let it process papers');
    console.log('🔍 [TEST] Or check the database to see if papers were generated successfully');
    
    // Don't exit - keep running to let the scheduler work
    console.log('⏳ [TEST] Keeping script alive to allow cron jobs to run...');
    console.log('⌨️ [TEST] Press Ctrl+C to exit when finished testing');

  } catch (error) {
    console.error('❌ [TEST] Error:', error);
    process.exit(1);
  }
}

// Run the function
startScheduler();
