/**
 * Simple test file for timeConverter module
 */

try {
  const { convertTo24Hour, timeToMinutes, isCurrentTimeAfter, getCronExpression } = require('./server/utils/timeConverter');

  console.log('🧪 Testing Time Converter Module\n');

  // Test basic conversion
  console.log('📋 Testing convertTo24Hour function:');
  
  const testTimes = ['11:00 AM', '1:00 PM', '12:00 AM', '12:00 PM'];
  
  testTimes.forEach(time => {
    try {
      const result = convertTo24Hour(time);
      console.log(`${time} → Hour: ${result.hour}, Minute: ${result.minute}`);
    } catch (error) {
      console.log(`${time} → ERROR: ${error.message}`);
    }
  });

  console.log('\n⏰ Testing timeToMinutes function:');
  testTimes.forEach(time => {
    try {
      const minutes = timeToMinutes(time);
      console.log(`${time} → ${minutes} minutes since midnight`);
    } catch (error) {
      console.log(`${time} → ERROR: ${error.message}`);
    }
  });

  console.log('\n🕐 Testing isCurrentTimeAfter function:');
  const currentTime24 = '14:30'; // 2:30 PM
  testTimes.forEach(deliveryTime => {
    try {
      const isAfter = isCurrentTimeAfter(currentTime24, deliveryTime);
      console.log(`Current: ${currentTime24}, Delivery: ${deliveryTime} → ${isAfter ? 'AFTER' : 'BEFORE'}`);
    } catch (error) {
      console.log(`${deliveryTime} → ERROR: ${error.message}`);
    }
  });

  console.log('\n⚙️ Testing getCronExpression function:');
  testTimes.forEach(time => {
    try {
      const cron = getCronExpression(time);
      console.log(`${time} → Cron: ${cron}`);
    } catch (error) {
      console.log(`${time} → ERROR: ${error.message}`);
    }
  });

  console.log('\n✅ Time Converter Module Test Complete!');

} catch (error) {
  console.error('❌ Error loading time converter module:', error.message);
  console.error('Stack trace:', error.stack);
}
