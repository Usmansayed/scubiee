type ClientType = 'javascript-client' | 'js-on-device-eval-client';
type BindingType = 'expo' | 'rn' | 'react' | 'angular';
export declare const SDKType: {
    _get: (sdkKey: string) => string;
    _setClientType(sdkKey: string, client: ClientType): void;
    _setBindingType(binding: BindingType): void;
};
export {};
