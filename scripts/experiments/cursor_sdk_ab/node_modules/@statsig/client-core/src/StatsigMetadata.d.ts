export declare const SDK_VERSION = "3.31.0";
export type StatsigMetadata = {
    readonly [key: string]: string | undefined | null;
    readonly appVersion?: string;
    readonly deviceModel?: string;
    readonly deviceModelName?: string;
    readonly locale?: string;
    readonly sdkVersion: string;
    readonly stableID?: string | null;
    readonly systemName?: string;
    readonly systemVersion?: string;
};
export declare const StatsigMetadataProvider: {
    get: () => StatsigMetadata;
    add: (additions: {
        [key: string]: string | undefined;
    }) => void;
};
