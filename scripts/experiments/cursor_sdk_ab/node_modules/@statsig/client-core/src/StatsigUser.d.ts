import type { AnyStatsigOptions, StatsigEnvironment } from './StatsigOptionsCommon';
type StatsigUserPrimitives = string | number | boolean | Array<string> | undefined;
export type StatsigUser = {
    userID?: string;
    customIDs?: {
        [key: string]: string | undefined;
        stableID?: string;
    };
    email?: string;
    ip?: string;
    userAgent?: string;
    country?: string;
    locale?: string;
    appVersion?: string;
    custom?: Record<string, StatsigUserPrimitives>;
    privateAttributes?: Record<string, StatsigUserPrimitives> | null;
    analyticsOnlyMetadata?: Record<string, string | number | boolean>;
};
export type StatsigUserInternal = StatsigUser & {
    statsigEnvironment: StatsigEnvironment | undefined;
};
export declare function _normalizeUser(original: StatsigUser, options?: AnyStatsigOptions | null, fallbackEnvironment?: string | null): StatsigUserInternal;
export declare function _getFullUserHash(user: StatsigUser | undefined): string | null;
export {};
