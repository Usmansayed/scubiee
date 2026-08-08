import { DataAdapterAsyncOptions, DataAdapterSyncOptions, EvaluationsDataAdapter, ExperimentEvaluationOptions, FeatureGateEvaluationOptions, LayerEvaluationOptions, PrecomputedEvaluationsContext, PrecomputedEvaluationsInterface, StatsigClientBase, StatsigEvent, StatsigUpdateDetails, StatsigUser } from '@statsig/client-core';
import type { StatsigOptions } from './StatsigOptions';
type AsyncUpdateOptions = DataAdapterAsyncOptions;
type SyncUpdateOptions = DataAdapterSyncOptions;
export default class StatsigClient extends StatsigClientBase<EvaluationsDataAdapter> implements PrecomputedEvaluationsInterface {
    private _store;
    private _user;
    private _network;
    private _possibleFirstTouchMetadata;
    private _sdkInstanceID;
    /**
     * Retrieves an instance of the StatsigClient based on the provided SDK key.
     *  If no SDK key is provided, the method returns the most recently created instance of the StatsigClient.
     *  The method ensures that each unique SDK key corresponds to a single instance of StatsigClient, effectively implementing a singleton pattern for each key.
     *  If no instance exists for the given SDK key, a new StatsigClient instance will be created and returned.
     *
     * @param {string} [sdkKey] - Optional. The SDK key used to identify a specific instance of the StatsigClient. If omitted, the method returns the last created instance.
     * @returns {StatsigClient} Returns the StatsigClient instance associated with the given SDK key, creating a new one if needed.
     */
    static instance(sdkKey?: string): StatsigClient;
    /**
     * StatsigClient constructor
     *
     * @param {string} sdkKey A Statsig client SDK key. eg "client-xyz123..."
     * @param {StatsigUser} user StatsigUser object containing various attributes related to a user.
     * @param {StatsigOptions | null} options StatsigOptions, used to customize the behavior of the SDK.
     */
    constructor(sdkKey: string, user: StatsigUser, options?: StatsigOptions | null);
    /**
     * Initializes the StatsigClient using cached values. This method sets up the client synchronously by utilizing previously cached values.
     * After initialization, cache values are updated in the background for future use, either in subsequent sessions or when `updateUser` is called.
     * This is useful for quickly starting with the last-known-good configurations while refreshing data to keep settings up-to-date.
     *
     * @see {@link initializeAsync} for the asynchronous version of this method.
     */
    initializeSync(options?: SyncUpdateOptions): StatsigUpdateDetails;
    /**
     * Initializes the StatsigClient asynchronously by first using cached values and then updating to the latest values from the network.
     * Once the network values are fetched, they replace the existing cached values. If this method's promise is not awaited,
     * there might be a transition from cached to network values during the session, which can affect consistency.
     * This method is useful when it's acceptable to begin with potentially stale data and switch to the latest configuration as it becomes available.
     *
     * @param {AsyncUpdateOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {Promise<void>} A promise that resolves once the client is fully initialized with the latest values from the network or a timeout (if set) is hit.
     * @see {@link initializeSync} for the synchronous version of this method.
     */
    initializeAsync(options?: AsyncUpdateOptions): Promise<StatsigUpdateDetails>;
    /**
     * Synchronously updates the user in the Statsig client and switches the internal state to use cached values for the newly specified user.
     * After the initial switch to cached values, this method updates these values in the background, preparing them for future sessions or subsequent calls to updateUser.
     * This method ensures the client is quickly ready with available data.
     *
     * @param {StatsigUser} user - The new StatsigUser for which the client should update its internal state.
     * @see {@link updateUserAsync} for the asynchronous version of this method.
     */
    updateUserSync(user: StatsigUser, options?: SyncUpdateOptions): StatsigUpdateDetails;
    private _updateUserSyncImpl;
    /**
     * Asynchronously updates the user in the Statsig client by initially using cached values and then fetching the latest values from the network.
     * When the latest values are fetched, they replace the cached values. If the promise returned by this method is not awaited,
     * the client's state may shift from cached to updated network values during the session, potentially affecting consistency.
     * This method is best used in scenarios where up-to-date configuration is critical and initial delays are acceptable.
     *
     * @param {StatsigUser} user - The new StatsigUser for which the client should update its internal state.
     * @param {AsyncUpdateOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {Promise<void>} A promise that resolves once the client is fully updated with the latest values from the network or a timeout (if set) is hit.
     * @see {@link updateUserSync} for the synchronous version of this method.
     */
    updateUserAsync(user: StatsigUser, options?: AsyncUpdateOptions): Promise<StatsigUpdateDetails>;
    private _updateUserAsyncImpl;
    /**
     * Retrieves a synchronous context containing data currently being used by the SDK. Represented as a {@link PrecomputedEvaluationsContext} object.
     *
     * @returns {PrecomputedEvaluationsContext} The current synchronous context for the this StatsigClient instance.
     */
    getContext(): PrecomputedEvaluationsContext;
    /**
     * Retrieves the value of a feature gate for the current user, represented as a simple boolean.
     *
     * @param {string} name - The name of the feature gate to retrieve.
     * @param {FeatureGateEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {boolean} - The boolean value representing the gate's current evaluation results for the user.
     */
    checkGate(name: string, options?: FeatureGateEvaluationOptions): boolean;
    /**
     * Retrieves the value of a feature gate for the current user, represented as a {@link FeatureGate} object.
     *
     * @param {string} name - The name of the feature gate to retrieve.
     * @param {FeatureGateEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {FeatureGate} - The {@link FeatureGate} object representing the gate's current evaluation results for the user.
     */
    readonly getFeatureGate: (name: string, options?: import("@statsig/client-core").EvaluationOptionsCommon | undefined) => {
        readonly name: string;
        readonly ruleID: string;
        readonly details: import("@statsig/client-core").EvaluationDetails;
        readonly value: boolean;
        readonly idType: string | null;
        readonly __evaluation: import("@statsig/client-core").GateEvaluation | null;
    };
    /**
     * Retrieves the value of a dynamic config for the current user.
     *
     * @param {string} name The name of the dynamic config to get.
     * @param {DynamicConfigEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {DynamicConfig} - The {@link DynamicConfig} object representing the dynamic configs's current evaluation results for the user.
     */
    readonly getDynamicConfig: (name: string, options?: import("@statsig/client-core").EvaluationOptionsCommon | undefined) => {
        readonly name: string;
        readonly value: Record<string, unknown>;
        readonly ruleID: string;
        readonly details: import("@statsig/client-core").EvaluationDetails;
        readonly idType: string | null;
        readonly __evaluation: {
            id_type: string;
            name: string;
            rule_id: string;
            secondary_exposures: string[] | import("@statsig/client-core").SecondaryExposure[];
            value: Record<string, unknown>;
            version?: string | undefined;
            group_name?: string | undefined;
            group: string;
            is_device_based: boolean;
            is_experiment_active?: boolean | undefined;
            is_user_in_experiment?: boolean | undefined;
            passed?: boolean | undefined;
            is_in_layer?: boolean | undefined;
            explicit_parameters?: string[] | undefined;
        } | null;
        readonly get: import("@statsig/client-core").TypedGet;
    };
    /**
     * Retrieves the value of a experiment for the current user.
     *
     * @param {string} name The name of the experiment to get.
     * @param {ExperimentEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {Experiment} - The {@link Experiment} object representing the experiments's current evaluation results for the user.
     */
    readonly getExperiment: (name: string, options?: ExperimentEvaluationOptions | undefined) => {
        readonly name: string;
        readonly ruleID: string;
        readonly details: import("@statsig/client-core").EvaluationDetails;
        readonly value: Record<string, unknown>;
        readonly groupName: string | null;
        readonly idType: string | null;
        readonly __evaluation: {
            id_type: string;
            name: string;
            rule_id: string;
            secondary_exposures: string[] | import("@statsig/client-core").SecondaryExposure[];
            value: Record<string, unknown>;
            version?: string | undefined;
            group_name?: string | undefined;
            group: string;
            is_device_based: boolean;
            is_experiment_active?: boolean | undefined;
            is_user_in_experiment?: boolean | undefined;
            passed?: boolean | undefined;
            is_in_layer?: boolean | undefined;
            explicit_parameters?: string[] | undefined;
        } | null;
        readonly get: import("@statsig/client-core").TypedGet;
    };
    /**
     * Retrieves the list of all Dynamic Configs and Experiments for the current user.
     *
     * @returns {string[]} The list of all Dynamic Config and Experiment names for the current user. Note - these will be hashed unless you've disabled hashing.
     * This is intended to be used for debugging.
     */
    readonly getConfigList: (name: string, options?: import("@statsig/client-core").AnyEvaluationOptions | undefined) => string[];
    /**
     * Retrieves the value of a layer for the current user.
     *
     * @param {string} name The name of the layer to get.
     * @param {LayerEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {Layer} - The {@link Layer} object representing the layers's current evaluation results for the user.
     */
    readonly getLayer: (name: string, options?: LayerEvaluationOptions | undefined) => {
        readonly name: string;
        readonly ruleID: string;
        readonly details: import("@statsig/client-core").EvaluationDetails;
        readonly groupName: string | null;
        readonly __value: Record<string, unknown>;
        readonly __evaluation: {
            name: string;
            rule_id: string;
            secondary_exposures: string[] | import("@statsig/client-core").SecondaryExposure[];
            value: Record<string, unknown>;
            version?: string | undefined;
            group_name?: string | undefined;
            group: string;
            is_device_based: boolean;
            is_experiment_active?: boolean | undefined;
            is_user_in_experiment?: boolean | undefined;
            passed?: boolean | undefined;
            is_in_layer?: boolean | undefined;
            explicit_parameters: string[];
            allocated_experiment_name: string;
            undelegated_secondary_exposures?: string[] | import("@statsig/client-core").SecondaryExposure[] | undefined;
            parameter_rule_ids?: Record<string, string> | undefined;
        } | null;
        get: import("@statsig/client-core").TypedGet;
    };
    /**
     * Retrieves the value of a parameter store for the current user.
     *
     * @param {string} name The name of the parameter store to get.
     * @param {ParameterStoreEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {ParameterStore} - The {@link ParameterStore} object representing the parameter store's current mappings for the user.
     */
    readonly getParameterStore: (name: string, options?: import("@statsig/client-core").EvaluationOptionsCommon | undefined) => {
        readonly name: string;
        readonly details: import("@statsig/client-core").EvaluationDetails;
        readonly get: import("@statsig/client-core").TypedGet;
        readonly __configuration: import("@statsig/client-core").ParamStoreConfig | null;
    };
    /**
     * Logs an event to the internal logging system. This function allows logging by either passing a fully formed event object or by specifying the event name with optional value and metadata.
     *
     * @param {StatsigEvent|string} eventOrName - The event object conforming to the StatsigEvent interface, or the name of the event as a string.
     * @param {string|number} value - Optional. The value associated with the event, which can be a string or a number. This parameter is ignored if the first parameter is a StatsigEvent object.
     * @param {Record<string, string>} metadata - Optional. A key-value record containing metadata about the event. This is also ignored if the first parameter is an event object.
     */
    logEvent(eventOrName: StatsigEvent | string, value?: string | number, metadata?: Record<string, string>): void;
    /**
     * Updates the user with analytics only metadata. This will override any existing analytics only metadata.
     *
     * @param {Record<string, string | number | boolean>} metadata - The metadata to add to the user.
     */
    updateUserWithAnalyticsOnlyMetadata(metadata: Record<string, string | number | boolean>): void;
    protected _primeReadyRipcord(): void;
    private _initializeAsyncImpl;
    private _createErrorUpdateDetails;
    private _finalizeUpdate;
    private _runPostUpdate;
    private _resetForUser;
    private _configureUser;
    private _getFeatureGateImpl;
    private _getDynamicConfigImpl;
    private _getExperimentImpl;
    private _getConfigListImpl;
    private _getLayerImpl;
    private _getParameterStoreImpl;
}
export {};
