import { NetworkCore } from './NetworkCore';
import { StatsigClientEmitEventFunc } from './StatsigClientBase';
import { StatsigEventInternal } from './StatsigEvent';
import { LogEventCompressionMode, LoggingEnabledOption, NetworkConfigCommon, StatsigOptionsCommon } from './StatsigOptionsCommon';
export declare class EventLogger {
    private _sdkKey;
    private _emitter;
    private _network;
    private _options;
    private _queue;
    private _flushIntervalId;
    private _lastExposureTimeMap;
    private _nonExposedChecks;
    private _maxQueueSize;
    private _hasRunQuickFlush;
    private _creationTime;
    private _loggingEnabled;
    private _logEventUrlConfig;
    private static _safeFlushAndForget;
    private static _safeRetryFailedLogs;
    constructor(_sdkKey: string, _emitter: StatsigClientEmitEventFunc, _network: NetworkCore, _options: StatsigOptionsCommon<NetworkConfigCommon> | null);
    setLogEventCompressionMode(mode: LogEventCompressionMode): void;
    setLoggingEnabled(loggingEnabled: LoggingEnabledOption): void;
    enqueue(event: StatsigEventInternal): void;
    incrementNonExposureCount(name: string): void;
    reset(): void;
    start(): void;
    stop(): Promise<void>;
    flush(): Promise<void>;
    /**
     * We 'Quick Flush' following the very first event enqueued
     * within the quick flush window
     */
    private _quickFlushIfNeeded;
    private _shouldLogEvent;
    private _sendEvents;
    private _sendEventsViaPost;
    private _sendEventsViaBeacon;
    private _getRequestData;
    private _saveFailedLogsToStorage;
    private _getFailedLogsFromStorage;
    private _retryFailedLogs;
    private _getStorageKey;
    private _normalizeAndAppendEvent;
    private _appendAndResetNonExposedChecks;
    private _getCurrentPageUrl;
    private _startBackgroundFlushInterval;
}
