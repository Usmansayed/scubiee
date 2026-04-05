# Paper Scheduler

## Overview
The `paperScheduler.js` file is the sole module responsible for scheduling and delivering papers at specific times.

## Features
- **Automatic Paper Generation**: Papers are generated 5 minutes before the scheduled delivery hour
- **Paper Delivery**: Papers are marked as delivered at the scheduled time
- **Cleanup**: Old papers are automatically cleaned up after a specified period

## Usage
The scheduler is automatically started when the server initializes. No additional action is required.

### Programmatic API

```javascript
const paperScheduler = require('./schedulers/paperScheduler');

// Start the scheduler
paperScheduler.start();

// Stop the scheduler
paperScheduler.stop();

// Check scheduler status
const status = paperScheduler.getStatus();

// Manually trigger paper generation
await paperScheduler.triggerManualGeneration();
```

## Schedule
- **Paper Generation**: Every hour at 55 minutes past the hour (e.g., 12:55, 1:55)
- **Paper Delivery**: Every hour at 01 minutes past the hour (e.g., 1:01, 2:01)
- **Cleanup**: Daily at 2:00 AM

## Troubleshooting
If papers are not being delivered at their scheduled times, ensure:

1. The server is running
2. Check the scheduler status via `paperScheduler.getStatus()`
3. If the scheduler is not running, restart it with `paperScheduler.start()`
4. Manually trigger generation with `paperScheduler.triggerManualGeneration()`
