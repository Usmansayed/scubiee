import { AnyInitializeResponse, DataAdapterResult, DataSource, DetailedStoreResult, DynamicConfigEvaluation, EvaluationDetails, GateEvaluation, LayerEvaluation, ParamStoreConfig, SecondaryExposure, StatsigUser, StatsigWarnings } from '@statsig/client-core';
export default class EvaluationStore {
    private _sdkKey;
    private _valuesForExternalUse;
    private _values;
    private _source;
    private _lcut;
    private _receivedAt;
    private _bootstrapMetadata;
    private _warnings;
    constructor(_sdkKey: string);
    reset(): void;
    finalize(): void;
    getValues(): AnyInitializeResponse | null;
    setValues(result: DataAdapterResult | null, user: StatsigUser): boolean;
    getWarnings(): StatsigWarnings[] | undefined;
    getGate(name: string): DetailedStoreResult<GateEvaluation>;
    getConfig(name: string): DetailedStoreResult<DynamicConfigEvaluation>;
    getConfigList(): string[];
    getLayer(name: string): DetailedStoreResult<LayerEvaluation>;
    getParamStore(name: string): DetailedStoreResult<ParamStoreConfig>;
    getSource(): DataSource;
    getExposureMapping(): Record<string, SecondaryExposure> | undefined;
    private _extractBootstrapMetadata;
    private _getDetailedStoreResult;
    private _setWarningState;
    getCurrentSourceDetails(): EvaluationDetails;
    private _getDetails;
}
