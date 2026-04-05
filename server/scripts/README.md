# Paper Scheduler System

## Overview
This folder contains scripts for managing the paper scheduler system, which automatically generates and delivers papers at scheduled times.

## File Structure
- `paper-scheduler-manager.js`: Consolidated script for managing the scheduler (start/stop/status)
- `paper-generator.js`: Consolidated script for on-demand paper generation tasks

## Usage

### Scheduler Management
The `paper-scheduler-manager.js` script provides functions for:
- Starting the scheduler
- Stopping the scheduler
- Checking scheduler status
- Ensuring the scheduler is running

Example:
```bash
# Start the scheduler
node scripts/paper-scheduler-manager.js start

# Stop the scheduler
node scripts/paper-scheduler-manager.js stop

# Check scheduler status
node scripts/paper-scheduler-manager.js status

# Restart the scheduler
node scripts/paper-scheduler-manager.js restart
```

### Paper Generation
The `paper-generator.js` script provides functions for:
- Forcing immediate paper generation
- Finding and generating missing papers
- Regenerating specific papers

Example:
```bash
# Force immediate paper generation
node scripts/paper-generator.js generate

# Find papers that should have been delivered but weren't
node scripts/paper-generator.js find

# Find and generate missing papers
node scripts/paper-generator.js fix

# Regenerate a specific paper
node scripts/paper-generator.js regenerate <paperId> [date]
```

## Architecture
The core functionality is implemented in `schedulers/paperScheduler.js`. The scripts in this folder provide a user-friendly interface to interact with the paper scheduler.

## Deprecated Scripts
The following scripts have been consolidated and are no longer needed:
- `check-scheduler.js` → Use `paper-scheduler-manager.js status` instead
- `check-scheduler-status.js` → Use `paper-scheduler-manager.js status` instead
- `check-scheduler-detailed.js` → Use `paper-scheduler-manager.js status --detailed` instead
- `start-scheduler.js` → Use `paper-scheduler-manager.js start` instead
- `ensure-scheduler-running.js` → Use `paper-scheduler-manager.js ensure` instead
- `force-generate-papers.js` → Use `paper-generator.js generate` instead
- `find-missing-papers.js` → Use `paper-generator.js find` or `paper-generator.js fix` instead
