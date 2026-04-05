/**
 * This script checks for any papers that should have been delivered today
 * but weren't generated, and allows you to force their generation.
 */
const paperScheduler = require('../schedulers/paperScheduler');
const moment = require('moment-timezone');
const { Papers, PaperPosts } = require('../models');
const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout
});

async function findMissingPapers() {
  try {
    // Get the current time in IST
    const currentIST = moment().tz('Asia/Kolkata');
    console.log(`📅 Current IST time: ${currentIST.format('YYYY-MM-DD HH:mm:ss')}`);
    
    const today = currentIST.format('YYYY-MM-DD');
    console.log(`🔍 Looking for papers that should exist for today (${today}) but don't...`);
    
    // Find all active papers
    const activePapers = await Papers.findAll({
      where: {
        status: 'active',
        processingStatus: 'completed',
        deleted: false
      },
      attributes: ['id', 'title', 'authorId', 'deliveryTime', 'postCount']
    });
    
    console.log(`📚 Found ${activePapers.length} active papers in total.`);
    
    // Check which papers don't have entries for today
    const missingPapers = [];
    for (const paper of activePapers) {
      const deliveryHour = parseDeliveryTime(paper.deliveryTime);
      const currentHour = currentIST.hour();
      
      // Only check papers whose delivery time has already passed today
      if (deliveryHour <= currentHour) {
        const exists = await PaperPosts.findOne({
          where: {
            paperId: paper.id,
            paperDate: today
          }
        });
        
        if (!exists) {
          missingPapers.push({
            ...paper.toJSON(),
            deliveryHour
          });
        }
      }
    }
    
    console.log(`\n🔎 Results: ${missingPapers.length} papers missing for today that should have been delivered.`);
    
    if (missingPapers.length > 0) {
      console.log('\nMissing papers:');
      missingPapers.forEach((paper, index) => {
        console.log(`${index + 1}. ${paper.title} (ID: ${paper.id}) - Delivery time: ${paper.deliveryTime}`);
      });
      
      if (process.argv.includes('--auto-generate')) {
        await generateMissingPapers(missingPapers);
      } else {
        await promptForGeneration(missingPapers);
      }
    }
    
    return missingPapers;
  } catch (error) {
    console.error('❌ Error finding missing papers:', error);
    throw error;
  }
}

async function generateMissingPapers(missingPapers) {
  console.log('\n🚀 Generating all missing papers...');
  
  const today = moment().tz('Asia/Kolkata').format('YYYY-MM-DD');
  let generatedCount = 0;
  
  for (const paper of missingPapers) {
    try {
      console.log(`\nGenerating paper: ${paper.title}`);
      
      // Use the same algorithm as the main paper generation
      const recommendationsData = await paperScheduler.generatePaperRecommendations(paper, paper.authorId);
      
      if (!recommendationsData || !recommendationsData.recommendations || recommendationsData.recommendations.length === 0) {
        console.log(`⚠️ No suitable content found for ${paper.title}`);
        continue;
      }

      // Create new PaperPost with generated recommendations
      const postIds = recommendationsData.recommendations.map(rec => rec.id);
      const paperPost = await PaperPosts.create({
        paperId: paper.id,
        paperDate: today,
        deliveryTime: paper.deliveryTime,
        posts: postIds,
        status: 'scheduled',
        timezone: 'Asia/Kolkata'
      });

      console.log(`✅ Successfully generated paper: ${paper.title}`);
      generatedCount++;
    } catch (error) {
      console.error(`❌ Error generating paper ${paper.title}:`, error.message);
    }
  }
  
  console.log(`\n📊 Summary: Generated ${generatedCount} out of ${missingPapers.length} missing papers.`);
}

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

async function promptForGeneration(missingPapers) {
  return new Promise((resolve) => {
    rl.question('\nDo you want to generate these missing papers now? (y/n): ', async (answer) => {
      if (answer.toLowerCase() === 'y') {
        await generateMissingPapers(missingPapers);
      } else {
        console.log('❌ Paper generation cancelled.');
      }
      rl.close();
      resolve();
    });
  });
}

// When run directly as a script
if (require.main === module) {
  findMissingPapers()
    .then(() => {
      console.log('✅ Process completed.');
    })
    .catch(err => {
      console.error('💥 Fatal error:', err);
      rl.close();
      process.exit(1);
    });
}

module.exports = findMissingPapers;
