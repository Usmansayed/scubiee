import { DynamicConfigEvaluation, GateEvaluation, InitializeResponseV2, LayerEvaluation, ParamStoreConfig, SecondaryExposure } from '@statsig/client-core';
import { InitializeContainer } from './InitializeContainer';
export declare class V2InitializeContainer implements InitializeContainer {
    private _values;
    constructor(_values: InitializeResponseV2);
    getGate(name: string): GateEvaluation | null;
    getConfig(name: string): DynamicConfigEvaluation | null;
    getLayer(name: string): LayerEvaluation | null;
    getParamStore(name: string): ParamStoreConfig | null;
    getConfigList(): string[];
    getExposureMapping(): Record<string, SecondaryExposure> | undefined;
    private _getResultFromLookup;
}
