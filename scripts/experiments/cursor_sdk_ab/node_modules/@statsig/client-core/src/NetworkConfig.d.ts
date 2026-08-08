export declare const Endpoint: {
    readonly _initialize: "initialize";
    readonly _rgstr: "rgstr";
    readonly _download_config_specs: "download_config_specs";
};
export type Endpoint = (typeof Endpoint)[keyof typeof Endpoint];
export declare const NetworkDefault: {
    rgstr: "https://prodregistryv2.org/v1";
    initialize: "https://featureassets.org/v1";
    download_config_specs: "https://api.statsigcdn.com/v1";
};
export type NetworkPriority = 'high' | 'low' | 'auto';
export type NetworkArgs = RequestInit & {
    priority?: NetworkPriority;
};
export declare const NetworkParam: {
    readonly EventCount: "ec";
    readonly SdkKey: "k";
    readonly SdkType: "st";
    readonly SdkVersion: "sv";
    readonly Time: "t";
    readonly SessionID: "sid";
    readonly StatsigEncoded: "se";
    readonly IsGzipped: "gz";
};
export type NetworkParam = (typeof NetworkParam)[keyof typeof NetworkParam];
