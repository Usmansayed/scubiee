import { DataAdapterAsyncOptions, DataAdapterCore, DataAdapterResult, EvaluationsDataAdapter, NetworkCore, StatsigUser, StatsigUserInternal } from '@statsig/client-core';
import { StatsigOptions } from './StatsigOptions';
export declare class StatsigEvaluationsDataAdapter extends DataAdapterCore implements EvaluationsDataAdapter {
    private _network;
    protected _options: StatsigOptions | null;
    constructor();
    attach(sdkKey: string, options: StatsigOptions | null, network: NetworkCore | null): void;
    getDataAsync(current: DataAdapterResult | null, user: StatsigUser, options?: DataAdapterAsyncOptions): Promise<DataAdapterResult | null>;
    prefetchData(user: StatsigUser, options?: DataAdapterAsyncOptions): Promise<void>;
    setData(data: string): void;
    setDataLegacy(data: string, user: StatsigUser): void;
    protected _fetchFromNetwork(current: string | null, user?: StatsigUser, options?: DataAdapterAsyncOptions, isCacheValidFor204?: boolean): Promise<string | null>;
    protected _getCacheKey(user?: StatsigUserInternal): string;
    protected _isCachedResultValidFor204(result: DataAdapterResult, user: StatsigUser | undefined): boolean;
}
