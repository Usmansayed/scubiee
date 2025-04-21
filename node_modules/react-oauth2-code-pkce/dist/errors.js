"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.FetchError = void 0;
class FetchError extends Error {
    constructor(status, statusText, message) {
        super(message);
        this.name = 'FetchError';
        this.status = status;
        this.statusText = statusText;
    }
}
exports.FetchError = FetchError;
