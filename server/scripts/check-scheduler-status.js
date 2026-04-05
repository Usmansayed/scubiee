/**
 * This script checks the status of the paper scheduler and provides diagnostic information.
 * Use it to verify if the scheduler is properly configured and running.
 */
const paperScheduler = require('../schedulers/paperScheduler');
const moment = require('moment-timezone');
const { Papers, PaperPosts } = require('../models');

async function checkSchedulerStatus() {
  try {
    // Get the current time in IST
    const currentIST = moment().tz('Asia/Kolkata');
    console.log(`📅 Current IST time: ${currentIST.format('YYYY-MM-DD HH:mm:ss')}`);
    
    // Get scheduler status
    const status = paperScheduler.getStatus();
    console.log('📊 Paper Scheduler Status:', JSON.stringify(status, null, 2));
    
    // Count active papers
    const activePapersCount = await Papers.count({
      where: {
        status: 'active',
        processingStatus: 'completed',
        deleted: false
      }
    });
    console.log(`📚 Active papers in the system: ${activePapersCount}`);
    
    // Count today's papers
    const today = currentIST.format('YYYY-MM-DD');
    const todayPapersCount = await PaperPosts.count({
      where: {
        paperDate: today
      }
    });
    console.log(`📰 Papers generated for today (${today}): ${todayPapersCount}`);
    
    // Check papers for the next hour delivery
    const nextHour = currentIST.clone().add(1, 'hour').hour();
    const nextHourPapers = await Papers.findAll({
      where: {
        status: 'active',
        processingStatus: 'completed',
        deleted: false
      },
      attributes: ['id', 'title', 'deliveryTime']
    });
    
    const pendingDeliveries = nextHourPapers.filter(paper => {
      const deliveryHour = parseDeliveryTime(paper.deliveryTime);
      return deliveryHour === nextHour;
    });
    
    console.log(`⏰ Papers scheduled for next hour (${nextHour}:00): ${pendingDeliveries.length}`);
    
    if (pendingDeliveries.length > 0) {
      console.log('Details of papers for next hour delivery:');
      for (const paper of pendingDeliveries) {
        const exists = await PaperPosts.findOne({
          where: {
            paperId: paper.id,
            paperDate: today
          }
        });
        console.log(`- ${paper.title} (${paper.deliveryTime}) - ${exists ? '✅ Generated' : '⚠️ Not generated yet'}`);
      }
    }
    
    return {
      schedulerStatus: status,
      activePapers: activePapersCount,
      todaysPapers: todayPapersCount,
      nextHourDeliveries: pendingDeliveries.length
    };
  } catch (error) {
    console.error('❌ Error checking scheduler status:', error);
    throw error;
  }
}

// Helper function to parse delivery time (copied from scheduler)
function parseDeliveryTime(deliveryTime) {
  // Handle formats like "10:00 AM", "2:00 PM", etc.
  const [time, period] = deliveryTime.split(' ');
  const [hour, minute] = time.split(':').map(Number);
  
  if (period === 'PM' && hour !== 12) {
    return hour + 12;
  } else if (period === 'AM' && hour === 12) {
    return 0;
  }
  return hour;
}

// When run directly as a script
if (require.main === module) {
  checkSchedulerStatus()
    .then(() => {
      console.log('✅ Status check completed.');
    })
    .catch(err => {
      console.error('💥 Fatal error:', err);
      process.exit(1);
    });
}

module.exports = checkSchedulerStatus;
