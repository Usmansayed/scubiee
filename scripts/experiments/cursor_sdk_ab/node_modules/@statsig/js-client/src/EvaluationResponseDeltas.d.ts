import { InitializeResponseV1WithUpdates } from '@statsig/client-core';
export type DeltasFailureInfo = {
    hadBadDeltaChecksum: boolean;
    badChecksum?: string;
    badMergedConfigs?: Record<string, unknown>;
    badFullResponse?: Record<string, unknown>;
};
type DeltasResult = string | DeltasFailureInfo | null;
export declare function _resolveDeltasResponse(cache: InitializeResponseV1WithUpdates, deltasString: string): DeltasResult;
export {};
