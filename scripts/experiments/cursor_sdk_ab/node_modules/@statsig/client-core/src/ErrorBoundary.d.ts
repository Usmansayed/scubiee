import { StatsigClientEmitEventFunc } from './StatsigClientBase';
import { AnyStatsigOptions } from './StatsigOptionsCommon';
export declare const EXCEPTION_ENDPOINT = "https://statsigapi.net/v1/sdk_exception";
export declare class ErrorBoundary {
    private _sdkKey;
    private _options;
    private _emitter?;
    private _lastSeenError?;
    private _seen;
    constructor(_sdkKey: string, _options: AnyStatsigOptions | null, _emitter?: StatsigClientEmitEventFunc | undefined, _lastSeenError?: Error | undefined);
    wrap(instance: unknown, namePrefix?: string): void;
    logError(tag: string, error: unknown): void;
    getLastSeenErrorAndReset(): Error | null;
    attachErrorIfNoneExists(error: unknown): void;
    private _capture;
    private _onError;
}
