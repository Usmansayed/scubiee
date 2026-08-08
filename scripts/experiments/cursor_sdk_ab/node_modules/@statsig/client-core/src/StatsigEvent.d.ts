import { SecondaryExposure } from './EvaluationTypes';
import { DynamicConfig, FeatureGate, Layer } from './StatsigTypes';
import { StatsigUserInternal } from './StatsigUser';
export type StatsigEvent = {
    eventName: string;
    value?: string | number | null;
    metadata?: {
        [key: string]: string | undefined;
    } | null;
};
export type BootstrapMetadata = {
    generatorSDKInfo?: Record<string, string>;
    lcut?: number;
    user?: Record<string, unknown>;
};
export type StatsigEventInternal = Omit<StatsigEvent, 'metadata'> & {
    user: StatsigUserInternal | null;
    time: number;
    metadata?: {
        [key: string]: unknown;
    } | null;
    secondaryExposures?: SecondaryExposure[];
};
export declare const _isExposureEvent: ({ eventName, }: StatsigEventInternal) => boolean;
export declare const _createGateExposure: (user: StatsigUserInternal, gate: FeatureGate, exposureMapping?: Record<string, SecondaryExposure>) => StatsigEventInternal;
export declare function _mapExposures(exposures: SecondaryExposure[] | string[], exposureMapping?: Record<string, SecondaryExposure>): SecondaryExposure[];
export declare const _createConfigExposure: (user: StatsigUserInternal, config: DynamicConfig, exposureMapping?: Record<string, SecondaryExposure>) => StatsigEventInternal;
export declare const _createLayerParameterExposure: (user: StatsigUserInternal, layer: Layer, parameterName: string, exposureMapping?: Record<string, SecondaryExposure>) => StatsigEventInternal;
