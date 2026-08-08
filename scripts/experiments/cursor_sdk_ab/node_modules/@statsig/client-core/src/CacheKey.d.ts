import { StatsigUser } from './StatsigUser';
export type CustomCacheKeyGenerator = (sdkKey: string, user: StatsigUser) => string;
export declare function _getUserStorageKey(sdkKey: string, user: StatsigUser, customKeyGenerator?: CustomCacheKeyGenerator): string;
export declare function _getStorageKey(sdkKey: string, user?: StatsigUser, customKeyGenerator?: CustomCacheKeyGenerator): string;
