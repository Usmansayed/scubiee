import { DynamicConfigEvaluationOptions, ExperimentEvaluationOptions, FeatureGateEvaluationOptions, LayerEvaluationOptions, ParameterStoreEvaluationOptions } from '../EvaluationOptions';
import { EvaluationDetails } from '../EvaluationTypes';
import { OverrideAdapter } from '../OverrideAdapter';
import { ParamStoreConfig } from '../ParamStoreTypes';
import { DynamicConfig, Experiment, FeatureGate, Layer, ParameterStore } from '../StatsigTypes';
import { StatsigUser } from '../StatsigUser';
export declare class MockOverrideAdapter implements OverrideAdapter {
    getGateOverride(_current: FeatureGate, _user: StatsigUser, _options?: FeatureGateEvaluationOptions): FeatureGate | null;
    getDynamicConfigOverride(_current: DynamicConfig, _user: StatsigUser, _options?: DynamicConfigEvaluationOptions): DynamicConfig | null;
    getExperimentOverride(_current: Experiment, _user: StatsigUser, _options?: ExperimentEvaluationOptions): Experiment | null;
    getLayerOverride(_current: Layer, _user: StatsigUser, _options?: LayerEvaluationOptions): Layer | null;
    getParamStoreOverride(_current: ParameterStore, _options?: ParameterStoreEvaluationOptions): {
        config: ParamStoreConfig;
        details: EvaluationDetails;
    } | null;
}
