"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.EventBatch = void 0;
class EventBatch {
    constructor(events) {
        this.attempts = 0;
        this.createdAt = Date.now();
        this.events = events;
    }
    incrementAttempts() {
        this.attempts++;
    }
}
exports.EventBatch = EventBatch;
