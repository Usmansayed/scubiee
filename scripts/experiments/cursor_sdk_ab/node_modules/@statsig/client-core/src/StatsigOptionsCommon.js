"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.LoggingEnabledOption = exports.LogEventCompressionMode = void 0;
exports.LogEventCompressionMode = {
    /** Do not compress request bodies */
    Disabled: 'd',
    /** Compress request bodies unless a network proxy is configured */
    Enabled: 'e',
    /** Always compress request bodies, even when a proxy is configured */
    Forced: 'f',
};
exports.LoggingEnabledOption = {
    disabled: 'disabled',
    browserOnly: 'browser-only',
    always: 'always',
};
