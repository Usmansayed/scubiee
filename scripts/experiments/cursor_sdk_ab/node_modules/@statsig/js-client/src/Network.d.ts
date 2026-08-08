import { NetworkCore, NetworkPriority, StatsigClientEmitEventFunc, StatsigUser } from '@statsig/client-core';
import { StatsigOptions } from './StatsigOptions';
export default class StatsigNetwork extends NetworkCore {
    private _initializeUrlConfig;
    private _option;
    constructor(options: StatsigOptions | null, emitter?: StatsigClientEmitEventFunc);
    fetchEvaluations(sdkKey: string, current: string | null, priority?: NetworkPriority, user?: StatsigUser, isCacheValidFor204?: boolean): Promise<string | null>;
    private _fetchEvaluations;
}
