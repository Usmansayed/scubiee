import { ErrorBoundary } from './ErrorBoundary';
import { AnyStatsigOptions } from './StatsigOptionsCommon';
import { UrlConfiguration } from './UrlConfiguration';
export type FallbackResolverArgs = {
    fallbackUrl: string | null;
};
export declare class NetworkFallbackResolver {
    private _fallbackInfo;
    private _errorBoundary;
    private _networkOverrideFunc?;
    private _dnsQueryCooldowns;
    constructor(options: AnyStatsigOptions);
    setErrorBoundary(errorBoundary: ErrorBoundary): void;
    tryBumpExpiryTime(sdkKey: string, urlConfig: UrlConfiguration): void;
    getActiveFallbackUrl(sdkKey: string, urlConfig: UrlConfiguration): string | null;
    tryFetchUpdatedFallbackInfo(sdkKey: string, urlConfig: UrlConfiguration, errorMessage: string | null, timedOut: boolean): Promise<boolean>;
    private _updateFallbackInfoWithNewUrl;
    private _tryFetchFallbackUrlsFromNetwork;
    private _pickNewFallbackUrl;
}
export declare function _isDomainFailure(errorMsg: string | null, timedOut: boolean): boolean;
