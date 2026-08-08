import { StatsigClientInterface } from './ClientInterfaces';
export type StatsigGlobal = {
    [key: string]: unknown;
    instances?: Record<string, StatsigClientInterface>;
    firstInstance?: StatsigClientInterface;
    acInstances?: Record<string, unknown>;
    srInstances?: Record<string, unknown>;
    firstSRInstance?: unknown;
    instance: (sdkKey?: string) => StatsigClientInterface | undefined;
};
declare global {
    let __STATSIG__: StatsigGlobal | undefined;
    interface Window {
        __STATSIG__: StatsigGlobal | undefined;
    }
}
export declare const _getStatsigGlobal: () => StatsigGlobal;
export declare const _getStatsigGlobalFlag: (flag: string) => unknown;
export declare const _getInstance: (sdkKey: string) => StatsigClientInterface | undefined;
