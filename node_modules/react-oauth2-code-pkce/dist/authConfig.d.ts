import type { TAuthConfig, TInternalConfig } from './types';
export declare function createInternalConfig(passedConfig: TAuthConfig): TInternalConfig;
export declare function validateConfig(config: TInternalConfig): void;
