import './$_StatsigGlobal';
import { ErrorBoundary } from './ErrorBoundary';
import { NetworkPriority } from './NetworkConfig';
import { StatsigClientEmitEventFunc } from './StatsigClientBase';
import { AnyStatsigOptions, LogEventCompressionMode } from './StatsigOptionsCommon';
import { Flatten } from './TypingUtils';
import { UrlConfiguration } from './UrlConfiguration';
type RequestArgs = {
    sdkKey: string;
    urlConfig: UrlConfiguration;
    priority?: NetworkPriority;
    retries?: number;
    attempt?: number;
    params?: Record<string, string>;
    headers?: Record<string, string>;
    credentials?: RequestCredentials;
};
type DataFlags = {
    isStatsigEncodable?: boolean;
    isCompressable?: boolean;
};
export type RequestArgsWithData = Flatten<RequestArgs & {
    data: Record<string, unknown>;
} & DataFlags>;
type BeaconRequestArgs = Pick<RequestArgsWithData, 'data' | 'sdkKey' | 'urlConfig' | 'params' | 'isCompressable' | 'attempt'>;
type NetworkResponse = {
    body: string | null;
    code: number;
};
export declare class NetworkCore {
    private _emitter?;
    protected _errorBoundary: ErrorBoundary | null;
    private readonly _timeout;
    private readonly _netConfig;
    private readonly _options;
    private readonly _fallbackResolver;
    private _leakyBucket;
    private _lastUsedInitUrl;
    constructor(options: AnyStatsigOptions | null, _emitter?: StatsigClientEmitEventFunc | undefined);
    setLogEventCompressionMode(mode: LogEventCompressionMode): void;
    setErrorBoundary(errorBoundary: ErrorBoundary): void;
    isBeaconSupported(): boolean;
    getLastUsedInitUrlAndReset(): string | null;
    beacon(args: BeaconRequestArgs): boolean;
    post(args: RequestArgsWithData): Promise<NetworkResponse | null>;
    get(args: RequestArgs): Promise<NetworkResponse | null>;
    private _sendRequest;
    private _getLogEventCompressionMode;
    private _isRateLimited;
    private _getPopulatedURL;
    private _tryEncodeBody;
    private _tryToCompressBody;
    private _getInternalRequestArgs;
}
export {};
