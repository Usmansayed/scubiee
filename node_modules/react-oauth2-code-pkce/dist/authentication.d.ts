import type { TInternalConfig, TPrimitiveRecord, TTokenResponse } from './types';
export declare function redirectToLogin(config: TInternalConfig, customState?: string, additionalParameters?: TPrimitiveRecord, method?: 'popup' | 'redirect'): Promise<void>;
export declare const fetchTokens: (config: TInternalConfig) => Promise<TTokenResponse>;
export declare const fetchWithRefreshToken: (props: {
    config: TInternalConfig;
    refreshToken: string;
}) => Promise<TTokenResponse>;
export declare function redirectToLogout(config: TInternalConfig, token: string, refresh_token?: string, idToken?: string, state?: string, logoutHint?: string, additionalParameters?: TPrimitiveRecord): void;
export declare function validateState(urlParams: URLSearchParams, storageType: TInternalConfig['storage']): void;
