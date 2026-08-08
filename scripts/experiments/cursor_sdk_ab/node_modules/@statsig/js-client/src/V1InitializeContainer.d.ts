import { DynamicConfigEvaluation, GateEvaluation, InitializeResponseV1WithUpdates, LayerEvaluation, ParamStoreConfig, SecondaryExposure } from '@statsig/client-core';
import { InitializeContainer } from './InitializeContainer';
export declare class V1InitializeContainer implements InitializeContainer {
    private _values;
    constructor(_values: InitializeResponseV1WithUpdates);
    getGate(name: string): GateEvaluation | null;
    getConfig(name: string): DynamicConfigEvaluation | null;
    getLayer(name: string): LayerEvaluation | null;
    getParamStore(name: string): ParamStoreConfig | null;
    getConfigList(): string[];
    getExposureMapping(): Record<string, SecondaryExposure> | undefined;
    private _getResultFromLookup;
}
