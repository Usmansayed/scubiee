import { NetworkCore } from './NetworkCore';
import { DataAdapterAsyncOptions, DataAdapterResult, DataSource } from './StatsigDataAdapter';
import { AnyStatsigOptions } from './StatsigOptionsCommon';
import { StatsigUser, StatsigUserInternal } from './StatsigUser';
export declare abstract class DataAdapterCore {
    private _adapterName;
    protected _cacheSuffix: string;
    protected _options: AnyStatsigOptions | null;
    private _sdkKey;
    private _inMemoryCache;
    private _lastModifiedStoreKey;
    private _cacheLimit;
    protected constructor(_adapterName: string, _cacheSuffix: string);
    attach(sdkKey: string, options: AnyStatsigOptions | null, _network: NetworkCore | null): void;
    getDataSync(user?: StatsigUser | undefined): DataAdapterResult | null;
    setData(data: string, user?: StatsigUser): void;
    protected _getIsCacheValueValid(current: DataAdapterResult): boolean;
    protected _getDataAsyncImpl(current: DataAdapterResult | null, user?: StatsigUserInternal, options?: DataAdapterAsyncOptions): Promise<DataAdapterResult | null>;
    protected _prefetchDataImpl(user?: StatsigUser, options?: DataAdapterAsyncOptions): Promise<void>;
    protected abstract _fetchFromNetwork(current: string | null, user?: StatsigUser, options?: DataAdapterAsyncOptions, isCacheValidFor204?: boolean): Promise<string | null>;
    protected abstract _getCacheKey(user?: StatsigUserInternal): string;
    protected abstract _isCachedResultValidFor204(result: DataAdapterResult, user: StatsigUser | undefined): boolean;
    private _fetchAndPrepFromNetwork;
    protected _getSdkKey(): string;
    private _loadFromCache;
    private _writeToCache;
    private _runLocalStorageCacheEviction;
}
export declare function _makeDataAdapterResult(source: DataSource, data: string, stableID: string | null, user?: StatsigUser): DataAdapterResult;
