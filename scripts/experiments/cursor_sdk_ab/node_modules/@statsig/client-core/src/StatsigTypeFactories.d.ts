import { DynamicConfigEvaluation, EvaluationDetails, GateEvaluation, LayerEvaluation } from './EvaluationTypes';
import { AnyConfigBasedStatsigType, DynamicConfig, Experiment, FeatureGate, Layer, TypedGet } from './StatsigTypes';
export declare function _makeFeatureGate(name: string, details: EvaluationDetails, evaluation: GateEvaluation | null): FeatureGate;
export declare function _makeDynamicConfig(name: string, details: EvaluationDetails, evaluation: DynamicConfigEvaluation | null): DynamicConfig;
export declare function _makeExperiment(name: string, details: EvaluationDetails, evaluation: DynamicConfigEvaluation | null): Experiment;
export declare function _makeLayer(name: string, details: EvaluationDetails, evaluation: LayerEvaluation | null, exposeFunc?: (param: string) => void): Layer;
export declare function _mergeOverride<T extends AnyConfigBasedStatsigType>(original: T, overridden: T | null | undefined, value: Record<string, unknown>, exposeFunc?: (param: string) => void): T;
export declare function _makeTypedGet(name: string, value: Record<string, unknown> | undefined, exposeFunc?: (param: string) => void): TypedGet;
