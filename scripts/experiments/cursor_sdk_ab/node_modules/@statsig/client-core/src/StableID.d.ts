export declare const StableID: {
    cookiesEnabled: boolean;
    randomID: string;
    get: (sdkKey: string) => string | null;
    setOverride: (override: string, sdkKey: string) => void;
    _setCookiesEnabled: (sdkKey: string, cookiesEnabled: boolean) => void;
    _setDisabled: (sdkKey: string, disabled: boolean) => void;
};
export declare function getCookieName(sdkKey: string): string;
