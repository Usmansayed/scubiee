const axios = require('axios');

// Test content examples
const testContents = [
  {
    content: "Just watched the latest Marvel movie! The special effects were incredible and the storyline was amazing. Can't wait for the next one!",
    expectedCategories: ["Entertainment"]
  },
  {
    content: "Breaking: New AI breakthrough in machine learning could revolutionize healthcare. Scientists at MIT have developed a new algorithm that can predict diseases with 95% accuracy.",
    expectedCategories: ["Technology", "Science", "Health"]
  },
  {
    content: "Tonight's Lakers vs Warriors game was incredible! LeBron scored 45 points and the crowd went wild. Basketball at its finest!",
    expectedCategories: ["Sports"]
  },
  {
    content: "Just tried this amazing new restaurant downtown. The pasta was absolutely delicious and the service was excellent. Highly recommend!",
    expectedCategories: ["Food & Cuisines", "Lifestyle"]
  },
  {
    content: "Election results are coming in. The polls show a tight race between the two candidates. Democracy in action!",
    expectedCategories: ["Politics", "Local News"]
  }
];

async function testCategoryDetection() {
  const apiUrl = 'http://localhost:5000/post/test-category-detection';
  
  console.log('🧪 Testing AI Category Detection\n');
  console.log('=' * 50);
  
  for (let i = 0; i < testContents.length; i++) {
    const { content, expectedCategories } = testContents[i];
    
    try {
      console.log(`\n📝 Test ${i + 1}:`);
      console.log(`Content: "${content.substring(0, 100)}..."`);
      console.log(`Expected: [${expectedCategories.join(', ')}]`);
      
      const response = await axios.post(apiUrl, 
        { content }, 
        { 
          withCredentials: true,
          headers: {
            'Authorization': 'Bearer YOUR_TOKEN_HERE', // Replace with actual token
            'Content-Type': 'application/json'
          }
        }
      );
      
      if (response.data.success) {
        console.log(`✅ Detected: [${response.data.detectedCategories.join(', ')}]`);
        
        // Check if any expected categories were detected
        const hasExpectedCategory = expectedCategories.some(expected => 
          response.data.detectedCategories.includes(expected)
        );
        
        if (hasExpectedCategory) {
          console.log('✅ Test passed - detected relevant categories');
        } else {
          console.log('⚠️  Test partial - different but potentially valid categories');
        }
      } else {
        console.log('❌ Test failed - API returned error');
      }
      
    } catch (error) {
      console.log(`❌ Test ${i + 1} failed:`, error.response?.data?.error || error.message);
    }
    
    // Wait a bit between requests
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  
  console.log('\n' + '=' * 50);
  console.log('🏁 Testing completed!');
}

// Run the test
if (require.main === module) {
  testCategoryDetection().catch(console.error);
}

module.exports = { testCategoryDetection };
