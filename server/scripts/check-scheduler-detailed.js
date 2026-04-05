// DEPRECATED: This file has been consolidated into paper-scheduler-manager.js
// You can safely delete this file.
    console.log('  • Cleanup Job: ' + (status.cleanupJobScheduled ? '✅ Running' : '❌ Not Running'));
    console.log('  • Currently Processing: ' + (status.isRunning ? '⚙️ Yes' : '⏸️ No'));
    console.log('  • Timezone: ' + status.timezone);
    console.log('  • Paper Retention: ' + status.retainDays + ' days');
    
    // Database connection check
    console.log('\n🔌 Database Connection:');
    try {
      // Try to fetch one paper to verify connection
      await Papers.findOne();
      console.log('  ✅ Connection successful');
    } catch (error) {
      console.error('  ❌ Connection failed:', error.message);
    }
    
    // Count active papers
    const activePapers = await Papers.findAll({
      where: {
        status: 'active',
        processingStatus: 'completed',
        deleted: false
      },
      attributes: ['id', 'title', 'deliveryTime', 'authorId'],
      include: [{
        model: Users,
        as: 'author',
        attributes: ['id', 'username']
      }]
    });
    
    console.log('\n📚 Active Papers:');
    console.log(`  • Total active papers: ${activePapers.length}`);
    
    if (activePapers.length > 0) {
      console.log('\n  Paper Details:');
      for (const paper of activePapers.slice(0, 5)) { // Show first 5 papers
        console.log(`  - "${paper.title}" (${paper.deliveryTime}) by ${paper.author?.username || 'unknown'}`);
      }
      
      if (activePapers.length > 5) {
        console.log(`  ... and ${activePapers.length - 5} more papers`);
      }
    }
    
    // Check today's paper generation
    const today = currentIST.format('YYYY-MM-DD');
    const todayPapers = await PaperPosts.findAll({
      where: {
        paperDate: today
      }
    });
    
    console.log(`\n📰 Today's Papers (${today})`);
    console.log(`  • Generated papers for today: ${todayPapers.length}`);
    
    if (todayPapers.length > 0) {
      console.log(`  • Delivered: ${todayPapers.filter(p => p.status === 'delivered').length}`);
      console.log(`  • Scheduled: ${todayPapers.filter(p => p.status === 'scheduled').length}`);
    }
    
    // Check next hour's schedule
    const nextHour = currentIST.clone().add(1, 'hour').hour();
    console.log(`\n⏰ Next Hour (${nextHour}:00) Schedule:`);
    
    const papersForNextHour = activePapers.filter(paper => 
      parseDeliveryTime(paper.deliveryTime) === nextHour
    );
    
    if (papersForNextHour.length === 0) {
      console.log('  • No papers scheduled for next hour');
    } else {
      console.log(`  • ${papersForNextHour.length} papers scheduled for delivery`);
      
      for (const paper of papersForNextHour) {
        const exists = await PaperPosts.findOne({
          where: {
            paperId: paper.id,
            paperDate: today
          }
        });
        
        console.log(`    - "${paper.title}": ${exists ? '✅ Generated' : '❌ Not generated yet'}`);
      }
    }
    
    // Add scheduler health assessment
    console.log('\n🔍 Scheduler Health Check:');
    
    // Check if all jobs are scheduled
    const allJobsScheduled = status.cronJobScheduled && status.deliveryJobScheduled && status.cleanupJobScheduled;
    
    if (allJobsScheduled) {
      console.log('  ✅ All scheduler jobs running properly');
    } else {
      console.log('  ❌ Not all scheduler jobs are running');
      console.log('  ⚠️ Recommendation: Restart the scheduler with "node scripts/ensure-scheduler-running.js"');
    }
    
    // Check for active papers without today's generation
    if (activePapers.length > 0 && todayPapers.length === 0) {
      console.log('  ⚠️ Warning: Active papers exist but none generated for today');
      console.log('  ⚠️ Recommendation: Trigger manual generation with "node scripts/start-scheduler-now.js"');
    }
    
    console.log('\nDiagnostic check completed!');
    
  } catch (error) {
    console.error('💥 Fatal error in diagnostics:', error);
  }
}

// Helper function to parse delivery time
function parseDeliveryTime(deliveryTime) {
  const [time, period] = deliveryTime.split(' ');
  const [hour, minute] = time.split(':').map(Number);
  
  if (period === 'PM' && hour !== 12) {
    return hour + 12;
  } else if (period === 'AM' && hour === 12) {
    return 0;
  }
  return hour;
}

// Run the diagnostics when script is executed directly
checkSchedulerDetailed()
  .catch(err => {
    console.error('\n💥 Script execution failed:', err);
    process.exit(1);
  });
