export type EvaluationOptionsCommon = {
    /**
     * Prevents an exposure log being created for this check.
     *
     * default: `false`
     */
    disableExposureLog?: boolean;
};
export type FeatureGateEvaluationOptions = EvaluationOptionsCommon & {};
export type DynamicConfigEvaluationOptions = EvaluationOptionsCommon & {};
export type ExperimentEvaluationOptions = EvaluationOptionsCommon & {
    /**
     * Provide a map of values to be used across checks
     *
     * @requires {@link @statsig/js-user-persisted-storage}
     * @see {@link https://docs.statsig.com/client/concepts/persistent_assignment#example-usage}
     */
    userPersistedValues?: unknown;
};
export type LayerEvaluationOptions = EvaluationOptionsCommon & {
    /**
     * Provide a map of values to be used across checks
     *
     * @requires {@link @statsig/js-user-persisted-storage}
     * @see {@link https://docs.statsig.com/client/concepts/persistent_assignment#example-usage}
     */
    userPersistedValues?: unknown;
};
export type ParameterStoreEvaluationOptions = EvaluationOptionsCommon & {};
export type AnyEvaluationOptions = FeatureGateEvaluationOptions | DynamicConfigEvaluationOptions | ExperimentEvaluationOptions | LayerEvaluationOptions | ParameterStoreEvaluationOptions;
