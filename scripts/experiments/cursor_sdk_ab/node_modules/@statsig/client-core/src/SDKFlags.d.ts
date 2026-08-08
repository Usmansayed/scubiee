export declare const SDKFlags: {
    setFlags: (sdkKey: string, flags: Record<string, boolean>) => void;
    get: (sdkKey: string, flagKey: string) => boolean;
};
