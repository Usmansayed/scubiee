"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.EventLogger = void 0;
const CacheKey_1 = require("./CacheKey");
const Hashing_1 = require("./Hashing");
const Log_1 = require("./Log");
const NetworkConfig_1 = require("./NetworkConfig");
const SafeJs_1 = require("./SafeJs");
const StatsigEvent_1 = require("./StatsigEvent");
const StatsigOptionsCommon_1 = require("./StatsigOptionsCommon");
const StorageProvider_1 = require("./StorageProvider");
const UrlConfiguration_1 = require("./UrlConfiguration");
const VisibilityObserving_1 = require("./VisibilityObserving");
const DEFAULT_QUEUE_SIZE = 100;
const DEFAULT_FLUSH_INTERVAL_MS = 10000;
const MAX_DEDUPER_KEYS = 1000;
const DEDUPER_WINDOW_DURATION_MS = 600000;
const MAX_FAILED_LOGS = 500;
const QUICK_FLUSH_WINDOW_MS = 200;
const EVENT_LOGGER_MAP = {};
class EventLogger {
    static _safeFlushAndForget(sdkKey) {
        var _a;
        (_a = EVENT_LOGGER_MAP[sdkKey]) === null || _a === void 0 ? void 0 : _a.flush().catch(() => {
            // noop
        });
    }
    static _safeRetryFailedLogs(sdkKey) {
        var _a;
        (_a = EVENT_LOGGER_MAP[sdkKey]) === null || _a === void 0 ? void 0 : _a._retryFailedLogs();
    }
    constructor(_sdkKey, _emitter, _network, _options) {
        var _a, _b;
        this._sdkKey = _sdkKey;
        this._emitter = _emitter;
        this._network = _network;
        this._options = _options;
        this._queue = [];
        this._lastExposureTimeMap = {};
        this._nonExposedChecks = {};
        this._hasRunQuickFlush = false;
        this._creationTime = Date.now();
        this._loggingEnabled =
            (_a = _options === null || _options === void 0 ? void 0 : _options.loggingEnabled) !== null && _a !== void 0 ? _a : ((_options === null || _options === void 0 ? void 0 : _options.disableLogging) === true
                ? StatsigOptionsCommon_1.LoggingEnabledOption.disabled
                : StatsigOptionsCommon_1.LoggingEnabledOption.browserOnly);
        if ((_options === null || _options === void 0 ? void 0 : _options.loggingEnabled) && _options.disableLogging !== undefined) {
            Log_1.Log.warn('Detected both loggingEnabled and disableLogging options. loggingEnabled takes precedence - please remove disableLogging.');
        }
        this._maxQueueSize = (_b = _options === null || _options === void 0 ? void 0 : _options.loggingBufferMaxSize) !== null && _b !== void 0 ? _b : DEFAULT_QUEUE_SIZE;
        const config = _options === null || _options === void 0 ? void 0 : _options.networkConfig;
        this._logEventUrlConfig = new UrlConfiguration_1.UrlConfiguration(NetworkConfig_1.Endpoint._rgstr, config === null || config === void 0 ? void 0 : config.logEventUrl, config === null || config === void 0 ? void 0 : config.api, config === null || config === void 0 ? void 0 : config.logEventFallbackUrls);
    }
    setLogEventCompressionMode(mode) {
        this._network.setLogEventCompressionMode(mode);
    }
    setLoggingEnabled(loggingEnabled) {
        if (this._loggingEnabled === 'disabled' && loggingEnabled !== 'disabled') {
            // load any pre consented events into memory
            const storageKey = this._getStorageKey();
            const events = (0, StorageProvider_1._getObjectFromStorage)(storageKey);
            if (events) {
                this._queue.push(...events);
            }
            StorageProvider_1.Storage.removeItem(storageKey);
        }
        this._loggingEnabled = loggingEnabled;
    }
    enqueue(event) {
        if (!this._shouldLogEvent(event)) {
            return;
        }
        this._normalizeAndAppendEvent(event);
        this._quickFlushIfNeeded();
        if (this._queue.length > this._maxQueueSize) {
            EventLogger._safeFlushAndForget(this._sdkKey);
        }
    }
    incrementNonExposureCount(name) {
        var _a;
        const current = (_a = this._nonExposedChecks[name]) !== null && _a !== void 0 ? _a : 0;
        this._nonExposedChecks[name] = current + 1;
    }
    reset() {
        // attempt to flush any remaining events
        this.flush().catch(() => {
            // noop
        });
        this._lastExposureTimeMap = {};
    }
    start() {
        var _a;
        const isServerEnv = (0, SafeJs_1._isServerEnv)();
        if (isServerEnv && ((_a = this._options) === null || _a === void 0 ? void 0 : _a.loggingEnabled) !== 'always') {
            return;
        }
        EVENT_LOGGER_MAP[this._sdkKey] = this;
        if (!isServerEnv) {
            (0, VisibilityObserving_1._subscribeToVisiblityChanged)((visibility) => {
                if (visibility === 'background') {
                    EventLogger._safeFlushAndForget(this._sdkKey);
                }
                else if (visibility === 'foreground') {
                    EventLogger._safeRetryFailedLogs(this._sdkKey);
                }
            });
        }
        this._retryFailedLogs();
        this._startBackgroundFlushInterval();
    }
    stop() {
        return __awaiter(this, void 0, void 0, function* () {
            if (this._flushIntervalId) {
                clearInterval(this._flushIntervalId);
                this._flushIntervalId = null;
            }
            delete EVENT_LOGGER_MAP[this._sdkKey];
            yield this.flush();
        });
    }
    flush() {
        return __awaiter(this, void 0, void 0, function* () {
            this._appendAndResetNonExposedChecks();
            if (this._queue.length === 0) {
                return;
            }
            const events = this._queue;
            this._queue = [];
            yield this._sendEvents(events);
        });
    }
    /**
     * We 'Quick Flush' following the very first event enqueued
     * within the quick flush window
     */
    _quickFlushIfNeeded() {
        if (this._hasRunQuickFlush) {
            return;
        }
        this._hasRunQuickFlush = true;
        if (Date.now() - this._creationTime > QUICK_FLUSH_WINDOW_MS) {
            return;
        }
        setTimeout(() => EventLogger._safeFlushAndForget(this._sdkKey), QUICK_FLUSH_WINDOW_MS);
    }
    _shouldLogEvent(event) {
        var _a;
        if (((_a = this._options) === null || _a === void 0 ? void 0 : _a.loggingEnabled) !== 'always' && (0, SafeJs_1._isServerEnv)()) {
            return false;
        }
        if (!(0, StatsigEvent_1._isExposureEvent)(event)) {
            return true;
        }
        const user = event.user ? event.user : { statsigEnvironment: undefined };
        const userKey = (0, CacheKey_1._getUserStorageKey)(this._sdkKey, user);
        const metadata = event.metadata ? event.metadata : {};
        const key = [
            event.eventName,
            userKey,
            metadata['gate'],
            metadata['config'],
            metadata['ruleID'],
            metadata['allocatedExperiment'],
            metadata['parameterName'],
            String(metadata['isExplicitParameter']),
            metadata['reason'],
        ].join('|');
        const previous = this._lastExposureTimeMap[key];
        const now = Date.now();
        if (previous && now - previous < DEDUPER_WINDOW_DURATION_MS) {
            return false;
        }
        if (Object.keys(this._lastExposureTimeMap).length > MAX_DEDUPER_KEYS) {
            this._lastExposureTimeMap = {};
        }
        this._lastExposureTimeMap[key] = now;
        return true;
    }
    _sendEvents(events) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a, _b;
            if (this._loggingEnabled === 'disabled') {
                this._saveFailedLogsToStorage(events);
                return false;
            }
            try {
                const isClosing = (0, VisibilityObserving_1._isUnloading)();
                const shouldUseBeacon = isClosing &&
                    this._network.isBeaconSupported() &&
                    ((_b = (_a = this._options) === null || _a === void 0 ? void 0 : _a.networkConfig) === null || _b === void 0 ? void 0 : _b.networkOverrideFunc) == null;
                this._emitter({
                    name: 'pre_logs_flushed',
                    events,
                });
                const response = shouldUseBeacon
                    ? this._sendEventsViaBeacon(events)
                    : yield this._sendEventsViaPost(events);
                if (response.success) {
                    this._emitter({
                        name: 'logs_flushed',
                        events,
                    });
                    return true;
                }
                else {
                    Log_1.Log.warn('Failed to flush events.');
                    this._saveFailedLogsToStorage(events);
                    return false;
                }
            }
            catch (_c) {
                Log_1.Log.warn('Failed to flush events.');
                return false;
            }
        });
    }
    _sendEventsViaPost(events) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a;
            const result = yield this._network.post(this._getRequestData(events));
            const code = (_a = result === null || result === void 0 ? void 0 : result.code) !== null && _a !== void 0 ? _a : -1;
            return { success: code >= 200 && code < 300 };
        });
    }
    _sendEventsViaBeacon(events) {
        return {
            success: this._network.beacon(this._getRequestData(events)),
        };
    }
    _getRequestData(events) {
        return {
            sdkKey: this._sdkKey,
            data: {
                events,
            },
            urlConfig: this._logEventUrlConfig,
            retries: 3,
            isCompressable: true,
            params: {
                [NetworkConfig_1.NetworkParam.EventCount]: String(events.length),
            },
            credentials: 'same-origin',
        };
    }
    _saveFailedLogsToStorage(events) {
        while (events.length > MAX_FAILED_LOGS) {
            events.shift();
        }
        const storageKey = this._getStorageKey();
        try {
            const savedEvents = this._getFailedLogsFromStorage(storageKey);
            (0, StorageProvider_1._setObjectInStorage)(storageKey, [...savedEvents, ...events]);
        }
        catch (_a) {
            Log_1.Log.warn('Unable to save failed logs to storage');
        }
    }
    _getFailedLogsFromStorage(storageKey) {
        let savedEvents = [];
        try {
            const retrieved = (0, StorageProvider_1._getObjectFromStorage)(storageKey);
            if (Array.isArray(retrieved)) {
                savedEvents = retrieved;
            }
            return savedEvents;
        }
        catch (_a) {
            return [];
        }
    }
    _retryFailedLogs() {
        const storageKey = this._getStorageKey();
        (() => __awaiter(this, void 0, void 0, function* () {
            if (!StorageProvider_1.Storage.isReady()) {
                yield StorageProvider_1.Storage.isReadyResolver();
            }
            const events = (0, StorageProvider_1._getObjectFromStorage)(storageKey);
            if (!events) {
                return;
            }
            StorageProvider_1.Storage.removeItem(storageKey);
            yield this._sendEvents(events);
        }))().catch(() => {
            Log_1.Log.warn('Failed to flush stored logs');
        });
    }
    _getStorageKey() {
        return `statsig.failed_logs.${(0, Hashing_1._DJB2)(this._sdkKey)}`;
    }
    _normalizeAndAppendEvent(event) {
        if (event.user) {
            event.user = Object.assign({}, event.user);
            delete event.user.privateAttributes;
        }
        const extras = {};
        const currentPage = this._getCurrentPageUrl();
        if (currentPage) {
            extras.statsigMetadata = { currentPage };
        }
        const final = Object.assign(Object.assign({}, event), extras);
        Log_1.Log.debug('Enqueued Event:', final);
        this._queue.push(final);
    }
    _appendAndResetNonExposedChecks() {
        if (Object.keys(this._nonExposedChecks).length === 0) {
            return;
        }
        this._normalizeAndAppendEvent({
            eventName: 'statsig::non_exposed_checks',
            user: null,
            time: Date.now(),
            metadata: {
                checks: Object.assign({}, this._nonExposedChecks),
            },
        });
        this._nonExposedChecks = {};
    }
    _getCurrentPageUrl() {
        var _a;
        if (((_a = this._options) === null || _a === void 0 ? void 0 : _a.includeCurrentPageUrlWithEvents) === false) {
            return;
        }
        return (0, SafeJs_1._getCurrentPageUrlSafe)();
    }
    _startBackgroundFlushInterval() {
        var _a, _b;
        const flushInterval = (_b = (_a = this._options) === null || _a === void 0 ? void 0 : _a.loggingIntervalMs) !== null && _b !== void 0 ? _b : DEFAULT_FLUSH_INTERVAL_MS;
        const intervalId = setInterval(() => {
            const logger = EVENT_LOGGER_MAP[this._sdkKey];
            if (!logger || logger._flushIntervalId !== intervalId) {
                clearInterval(intervalId);
            }
            else {
                EventLogger._safeFlushAndForget(this._sdkKey);
            }
        }, flushInterval);
        this._flushIntervalId = intervalId;
    }
}
exports.EventLogger = EventLogger;
