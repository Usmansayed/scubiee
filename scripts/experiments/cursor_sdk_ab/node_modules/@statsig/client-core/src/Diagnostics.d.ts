import { EvaluationDetails } from './EvaluationTypes';
import { EventLogger } from './EventLogger';
import { NetworkConfigCommon, StatsigOptionsCommon } from './StatsigOptionsCommon';
import { StatsigUserInternal } from './StatsigUser';
export type KeyType = 'initialize' | 'overall';
export type StepType = 'process' | 'network_request';
export type ActionType = 'start' | 'end';
export interface Marker {
    key: KeyType;
    action: ActionType;
    timestamp: number;
    step?: StepType;
    statusCode?: number;
    success?: boolean;
    url?: string;
    idListCount?: number;
    sdkRegion?: string | null;
    markerID?: string;
    attempt?: number;
    isRetry?: boolean;
    configName?: string;
    message?: string | null;
    evaluationDetails?: EvaluationDetails;
    error?: Record<string, unknown>;
    isDelta?: boolean;
}
export declare const Diagnostics: {
    _getMarkers: (sdkKey: string) => Marker[] | undefined;
    _markInitOverallStart: (sdkKey: string) => void;
    _markInitOverallEnd: (sdkKey: string, success: boolean, evaluationDetails?: EvaluationDetails) => void;
    _markInitNetworkReqStart: (sdkKey: string, data: InitializeDataType['networkRequest']['start']) => void;
    _markInitNetworkReqEnd: (sdkKey: string, data: InitializeDataType['networkRequest']['end']) => void;
    _markInitProcessStart: (sdkKey: string) => void;
    _markInitProcessEnd: (sdkKey: string, data: InitializeDataType['process']['end']) => void;
    _clearMarkers: (sdkKey: string) => void;
    _formatError(e: unknown): Record<string, unknown> | undefined;
    _getDiagnosticsData(res: Response | null, attempt: number, body: string, e?: unknown): {
        success: boolean;
        isDelta?: boolean;
        sdkRegion?: string | null;
        statusCode?: number;
        attempt: number;
        error?: Record<string, unknown>;
    };
    _enqueueDiagnosticsEvent(user: StatsigUserInternal | null, logger: EventLogger, sdk: string, options: StatsigOptionsCommon<NetworkConfigCommon> | null): number;
};
interface InitializeDataType {
    process: {
        end: {
            success: boolean;
        };
    };
    networkRequest: {
        start: {
            attempt: number;
        };
        end: {
            success: boolean;
            attempt: number;
            isDelta?: boolean;
            sdkRegion?: string | null;
            statusCode?: number;
            error?: Record<string, unknown>;
        };
    };
}
export {};
