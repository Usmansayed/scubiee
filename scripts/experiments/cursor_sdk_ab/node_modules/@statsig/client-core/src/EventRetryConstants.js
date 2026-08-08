"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.EventRetryConstants = void 0;
exports.EventRetryConstants = {
    MAX_RETRY_ATTEMPTS: 5,
    DEFAULT_BATCH_SIZE: 100,
    MAX_PENDING_BATCHES: 10,
    TICK_INTERVAL_MS: 1000,
    get MAX_QUEUED_EVENTS() {
        return this.DEFAULT_BATCH_SIZE * this.MAX_PENDING_BATCHES;
    },
};
