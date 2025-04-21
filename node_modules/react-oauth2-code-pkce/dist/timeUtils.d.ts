import type { TTokenResponse } from './types';
export declare const FALLBACK_EXPIRE_TIME = 600;
export declare const epochAtSecondsFromNow: (secondsFromNow: number | string) => number;
/**
 * Check if the Access Token has expired.
 * Will return True if the token has expired, OR there is less than 30 seconds until it expires.
 */
export declare function epochTimeIsPast(timestamp: number): boolean;
export declare function getRefreshExpiresIn(tokenExpiresIn: number, response: TTokenResponse): number;
