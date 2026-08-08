"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
Object.defineProperty(exports, "__esModule", { value: true });
const client_core_1 = require("@statsig/client-core");
const EvaluationStore_1 = require("./EvaluationStore");
const Network_1 = require("./Network");
const ParamStoreGetterFactory_1 = require("./ParamStoreGetterFactory");
const StatsigEvaluationsDataAdapter_1 = require("./StatsigEvaluationsDataAdapter");
class StatsigClient extends client_core_1.StatsigClientBase {
    /**
     * Retrieves an instance of the StatsigClient based on the provided SDK key.
     *  If no SDK key is provided, the method returns the most recently created instance of the StatsigClient.
     *  The method ensures that each unique SDK key corresponds to a single instance of StatsigClient, effectively implementing a singleton pattern for each key.
     *  If no instance exists for the given SDK key, a new StatsigClient instance will be created and returned.
     *
     * @param {string} [sdkKey] - Optional. The SDK key used to identify a specific instance of the StatsigClient. If omitted, the method returns the last created instance.
     * @returns {StatsigClient} Returns the StatsigClient instance associated with the given SDK key, creating a new one if needed.
     */
    static instance(sdkKey) {
        const instance = (0, client_core_1._getStatsigGlobal)().instance(sdkKey);
        if (instance instanceof StatsigClient) {
            return instance;
        }
        client_core_1.Log.warn((0, client_core_1._isServerEnv)()
            ? 'StatsigClient.instance is not supported in server environments'
            : 'Unable to find StatsigClient instance');
        return new StatsigClient(sdkKey !== null && sdkKey !== void 0 ? sdkKey : '', {});
    }
    /**
     * StatsigClient constructor
     *
     * @param {string} sdkKey A Statsig client SDK key. eg "client-xyz123..."
     * @param {StatsigUser} user StatsigUser object containing various attributes related to a user.
     * @param {StatsigOptions | null} options StatsigOptions, used to customize the behavior of the SDK.
     */
    constructor(sdkKey, user, options = null) {
        var _a, _b;
        client_core_1.SDKType._setClientType(sdkKey, 'javascript-client');
        const network = new Network_1.default(options, (e) => {
            this.$emt(e);
        });
        super(sdkKey, (_a = options === null || options === void 0 ? void 0 : options.dataAdapter) !== null && _a !== void 0 ? _a : new StatsigEvaluationsDataAdapter_1.StatsigEvaluationsDataAdapter(), network, options);
        this._possibleFirstTouchMetadata = {};
        /**
         * Retrieves the value of a feature gate for the current user, represented as a {@link FeatureGate} object.
         *
         * @param {string} name - The name of the feature gate to retrieve.
         * @param {FeatureGateEvaluationOptions} [options] - Optional. Additional options to customize the method call.
         * @returns {FeatureGate} - The {@link FeatureGate} object representing the gate's current evaluation results for the user.
         */
        this.getFeatureGate = this._memoize(client_core_1.MemoPrefix._gate, this._getFeatureGateImpl.bind(this));
        /**
         * Retrieves the value of a dynamic config for the current user.
         *
         * @param {string} name The name of the dynamic config to get.
         * @param {DynamicConfigEvaluationOptions} [options] - Optional. Additional options to customize the method call.
         * @returns {DynamicConfig} - The {@link DynamicConfig} object representing the dynamic configs's current evaluation results for the user.
         */
        this.getDynamicConfig = this._memoize(client_core_1.MemoPrefix._dynamicConfig, this._getDynamicConfigImpl.bind(this));
        /**
         * Retrieves the value of a experiment for the current user.
         *
         * @param {string} name The name of the experiment to get.
         * @param {ExperimentEvaluationOptions} [options] - Optional. Additional options to customize the method call.
         * @returns {Experiment} - The {@link Experiment} object representing the experiments's current evaluation results for the user.
         */
        this.getExperiment = this._memoize(client_core_1.MemoPrefix._experiment, this._getExperimentImpl.bind(this));
        /**
         * Retrieves the list of all Dynamic Configs and Experiments for the current user.
         *
         * @returns {string[]} The list of all Dynamic Config and Experiment names for the current user. Note - these will be hashed unless you've disabled hashing.
         * This is intended to be used for debugging.
         */
        this.getConfigList = this._memoize(client_core_1.MemoPrefix._configList, this._getConfigListImpl.bind(this));
        /**
         * Retrieves the value of a layer for the current user.
         *
         * @param {string} name The name of the layer to get.
         * @param {LayerEvaluationOptions} [options] - Optional. Additional options to customize the method call.
         * @returns {Layer} - The {@link Layer} object representing the layers's current evaluation results for the user.
         */
        this.getLayer = this._memoize(client_core_1.MemoPrefix._layer, this._getLayerImpl.bind(this));
        /**
         * Retrieves the value of a parameter store for the current user.
         *
         * @param {string} name The name of the parameter store to get.
         * @param {ParameterStoreEvaluationOptions} [options] - Optional. Additional options to customize the method call.
         * @returns {ParameterStore} - The {@link ParameterStore} object representing the parameter store's current mappings for the user.
         */
        this.getParameterStore = this._memoize(client_core_1.MemoPrefix._paramStore, this._getParameterStoreImpl.bind(this));
        this._store = new EvaluationStore_1.default(sdkKey);
        this._network = network;
        this._user = this._configureUser(user, options);
        this._sdkInstanceID = (0, client_core_1.getUUID)();
        const plugins = (_b = options === null || options === void 0 ? void 0 : options.plugins) !== null && _b !== void 0 ? _b : [];
        for (const plugin of plugins) {
            plugin.bind(this);
        }
    }
    /**
     * Initializes the StatsigClient using cached values. This method sets up the client synchronously by utilizing previously cached values.
     * After initialization, cache values are updated in the background for future use, either in subsequent sessions or when `updateUser` is called.
     * This is useful for quickly starting with the last-known-good configurations while refreshing data to keep settings up-to-date.
     *
     * @see {@link initializeAsync} for the asynchronous version of this method.
     */
    initializeSync(options) {
        var _a;
        if (this.loadingStatus !== 'Uninitialized') {
            return (0, client_core_1.createUpdateDetails)(true, this._store.getSource(), -1, null, null, ['MultipleInitializations', ...((_a = this._store.getWarnings()) !== null && _a !== void 0 ? _a : [])]);
        }
        this._logger.start();
        return this.updateUserSync(this._user, options);
    }
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
    initializeAsync(options) {
        return __awaiter(this, void 0, void 0, function* () {
            if (this._initializePromise) {
                return this._initializePromise;
            }
            this._initializePromise = this._initializeAsyncImpl(options);
            return this._initializePromise;
        });
    }
    /**
     * Synchronously updates the user in the Statsig client and switches the internal state to use cached values for the newly specified user.
     * After the initial switch to cached values, this method updates these values in the background, preparing them for future sessions or subsequent calls to updateUser.
     * This method ensures the client is quickly ready with available data.
     *
     * @param {StatsigUser} user - The new StatsigUser for which the client should update its internal state.
     * @see {@link updateUserAsync} for the asynchronous version of this method.
     */
    updateUserSync(user, options) {
        const startTime = performance.now();
        try {
            return this._updateUserSyncImpl(user, options, startTime);
        }
        catch (e) {
            const err = e instanceof Error ? e : new Error(String(e));
            return this._createErrorUpdateDetails(err, startTime);
        }
    }
    _updateUserSyncImpl(user, options, startTime) {
        var _a;
        const warnings = [...((_a = this._store.getWarnings()) !== null && _a !== void 0 ? _a : [])];
        this._resetForUser(user);
        const result = this.dataAdapter.getDataSync(this._user);
        if (result == null) {
            warnings.push('NoCachedValues');
        }
        this._store.setValues(result, this._user);
        this._finalizeUpdate(result);
        const disable = options === null || options === void 0 ? void 0 : options.disableBackgroundCacheRefresh;
        if (disable === true ||
            (disable == null && (result === null || result === void 0 ? void 0 : result.source) === 'Bootstrap')) {
            return (0, client_core_1.createUpdateDetails)(true, this._store.getSource(), performance.now() - startTime, this._errorBoundary.getLastSeenErrorAndReset(), this._network.getLastUsedInitUrlAndReset(), warnings);
        }
        this._runPostUpdate(result !== null && result !== void 0 ? result : null, this._user);
        return (0, client_core_1.createUpdateDetails)(true, this._store.getSource(), performance.now() - startTime, this._errorBoundary.getLastSeenErrorAndReset(), this._network.getLastUsedInitUrlAndReset(), warnings);
    }
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
    updateUserAsync(user, options) {
        return __awaiter(this, void 0, void 0, function* () {
            const startTime = performance.now();
            try {
                return yield this._updateUserAsyncImpl(user, options);
            }
            catch (e) {
                const err = e instanceof Error ? e : new Error(String(e));
                return this._createErrorUpdateDetails(err, startTime);
            }
        });
    }
    _updateUserAsyncImpl(user, options) {
        return __awaiter(this, void 0, void 0, function* () {
            this._resetForUser(user);
            const initiator = this._user;
            client_core_1.Diagnostics._markInitOverallStart(this._sdkKey);
            let result = this.dataAdapter.getDataSync(initiator);
            this._store.setValues(result, this._user);
            this._setStatus('Loading', result);
            result = yield this.dataAdapter.getDataAsync(result, initiator, options);
            // ensure the user hasn't changed while we were waiting
            if (initiator !== this._user) {
                return (0, client_core_1.createUpdateDetails)(false, this._store.getSource(), -1, new Error('User changed during update'), this._network.getLastUsedInitUrlAndReset());
            }
            let isUsingNetworkValues = false;
            if (result != null) {
                client_core_1.Diagnostics._markInitProcessStart(this._sdkKey);
                isUsingNetworkValues = this._store.setValues(result, this._user);
                client_core_1.Diagnostics._markInitProcessEnd(this._sdkKey, {
                    success: isUsingNetworkValues,
                });
            }
            this._finalizeUpdate(result);
            if (!isUsingNetworkValues) {
                this._errorBoundary.attachErrorIfNoneExists(client_core_1.UPDATE_DETAIL_ERROR_MESSAGES.NO_NETWORK_DATA);
                this.$emt({ name: 'initialization_failure' });
            }
            client_core_1.Diagnostics._markInitOverallEnd(this._sdkKey, isUsingNetworkValues, this._store.getCurrentSourceDetails());
            const initDuration = client_core_1.Diagnostics._enqueueDiagnosticsEvent(this._user, this._logger, this._sdkKey, this._options);
            return (0, client_core_1.createUpdateDetails)(isUsingNetworkValues, this._store.getSource(), initDuration, this._errorBoundary.getLastSeenErrorAndReset(), this._network.getLastUsedInitUrlAndReset(), this._store.getWarnings());
        });
    }
    /**
     * Retrieves a synchronous context containing data currently being used by the SDK. Represented as a {@link PrecomputedEvaluationsContext} object.
     *
     * @returns {PrecomputedEvaluationsContext} The current synchronous context for the this StatsigClient instance.
     */
    getContext() {
        let user = (0, client_core_1._cloneObject)('StatsigUser', this._user);
        if (user == null) {
            client_core_1.Log.error('Failed to clone user');
            user = {};
        }
        return {
            sdkKey: this._sdkKey,
            options: this._options,
            values: this._store.getValues(),
            user,
            errorBoundary: this._errorBoundary,
            session: client_core_1.StatsigSession.get(this._sdkKey),
            stableID: client_core_1.StableID.get(this._sdkKey),
            sdkInstanceID: this._sdkInstanceID,
        };
    }
    /**
     * Retrieves the value of a feature gate for the current user, represented as a simple boolean.
     *
     * @param {string} name - The name of the feature gate to retrieve.
     * @param {FeatureGateEvaluationOptions} [options] - Optional. Additional options to customize the method call.
     * @returns {boolean} - The boolean value representing the gate's current evaluation results for the user.
     */
    checkGate(name, options) {
        return this.getFeatureGate(name, options).value;
    }
    /**
     * Logs an event to the internal logging system. This function allows logging by either passing a fully formed event object or by specifying the event name with optional value and metadata.
     *
     * @param {StatsigEvent|string} eventOrName - The event object conforming to the StatsigEvent interface, or the name of the event as a string.
     * @param {string|number} value - Optional. The value associated with the event, which can be a string or a number. This parameter is ignored if the first parameter is a StatsigEvent object.
     * @param {Record<string, string>} metadata - Optional. A key-value record containing metadata about the event. This is also ignored if the first parameter is an event object.
     */
    logEvent(eventOrName, value, metadata) {
        const event = typeof eventOrName === 'string'
            ? {
                eventName: eventOrName,
                value,
                metadata,
            }
            : eventOrName;
        this.$emt({
            name: 'log_event_called',
            event,
        });
        this._logger.enqueue(Object.assign(Object.assign({}, event), { user: this._user, time: Date.now() }));
    }
    /**
     * Updates the user with analytics only metadata. This will override any existing analytics only metadata.
     *
     * @param {Record<string, string | number | boolean>} metadata - The metadata to add to the user.
     */
    updateUserWithAnalyticsOnlyMetadata(metadata) {
        this._user = this._configureUser(Object.assign(Object.assign({}, this._user), { analyticsOnlyMetadata: metadata }), this._options);
    }
    _primeReadyRipcord() {
        this.$on('error', () => {
            this.loadingStatus === 'Loading' && this._finalizeUpdate(null);
        });
    }
    _initializeAsyncImpl(options) {
        return __awaiter(this, void 0, void 0, function* () {
            if (!client_core_1.Storage.isReady()) {
                yield client_core_1.Storage.isReadyResolver();
            }
            this._logger.start();
            return this.updateUserAsync(this._user, options);
        });
    }
    _createErrorUpdateDetails(error, startTime) {
        var _a;
        return (0, client_core_1.createUpdateDetails)(false, this._store.getSource(), performance.now() - startTime, error, null, [...((_a = this._store.getWarnings()) !== null && _a !== void 0 ? _a : [])]);
    }
    _finalizeUpdate(values) {
        this._store.finalize();
        this._setStatus('Ready', values);
    }
    _runPostUpdate(current, user) {
        this.dataAdapter
            .getDataAsync(current, user, { priority: 'low' })
            .catch((err) => {
            client_core_1.Log.error('An error occurred after update.', err);
        });
    }
    _resetForUser(user) {
        this._logger.reset();
        this._store.reset();
        this._user = this._configureUser(user, this._options);
    }
    _configureUser(originalUser, options) {
        var _a, _b, _c;
        const user = (0, client_core_1._normalizeUser)(originalUser, options);
        const stableIdOverride = (_a = user.customIDs) === null || _a === void 0 ? void 0 : _a.stableID;
        if (stableIdOverride) {
            const readyPromise = (_c = (_b = this.storageProvider).isReadyResolver) === null || _c === void 0 ? void 0 : _c.call(_b);
            if (readyPromise) {
                readyPromise.then(() => client_core_1.StableID.setOverride(stableIdOverride, this._sdkKey), () => client_core_1.StableID.setOverride(stableIdOverride, this._sdkKey));
            }
            else {
                client_core_1.StableID.setOverride(stableIdOverride, this._sdkKey);
            }
        }
        // Only attach first touch metadata if it's not empty
        if (Object.keys(this._possibleFirstTouchMetadata).length > 0) {
            user.analyticsOnlyMetadata = Object.assign(Object.assign({}, user.analyticsOnlyMetadata), this._possibleFirstTouchMetadata);
        }
        return user;
    }
    _getFeatureGateImpl(name, options) {
        var _a, _b;
        const { result: evaluation, details } = this._store.getGate(name);
        const gate = (0, client_core_1._makeFeatureGate)(name, details, evaluation);
        const overridden = (_b = (_a = this.overrideAdapter) === null || _a === void 0 ? void 0 : _a.getGateOverride) === null || _b === void 0 ? void 0 : _b.call(_a, gate, this._user, options);
        const result = overridden !== null && overridden !== void 0 ? overridden : gate;
        this._enqueueExposure(name, (0, client_core_1._createGateExposure)(this._user, result, this._store.getExposureMapping()), options);
        this.$emt({ name: 'gate_evaluation', gate: result });
        return result;
    }
    _getDynamicConfigImpl(name, options) {
        var _a, _b;
        const { result: evaluation, details } = this._store.getConfig(name);
        const config = (0, client_core_1._makeDynamicConfig)(name, details, evaluation);
        const overridden = (_b = (_a = this.overrideAdapter) === null || _a === void 0 ? void 0 : _a.getDynamicConfigOverride) === null || _b === void 0 ? void 0 : _b.call(_a, config, this._user, options);
        const result = overridden !== null && overridden !== void 0 ? overridden : config;
        this._enqueueExposure(name, (0, client_core_1._createConfigExposure)(this._user, result, this._store.getExposureMapping()), options);
        this.$emt({ name: 'dynamic_config_evaluation', dynamicConfig: result });
        return result;
    }
    _getExperimentImpl(name, options) {
        var _a, _b, _c, _d;
        const { result: evaluation, details } = this._store.getConfig(name);
        const experiment = (0, client_core_1._makeExperiment)(name, details, evaluation);
        if (experiment.__evaluation != null) {
            experiment.__evaluation.secondary_exposures = (0, client_core_1._mapExposures)((_b = (_a = experiment.__evaluation) === null || _a === void 0 ? void 0 : _a.secondary_exposures) !== null && _b !== void 0 ? _b : [], this._store.getExposureMapping());
        }
        const overridden = (_d = (_c = this.overrideAdapter) === null || _c === void 0 ? void 0 : _c.getExperimentOverride) === null || _d === void 0 ? void 0 : _d.call(_c, experiment, this._user, options);
        const result = overridden !== null && overridden !== void 0 ? overridden : experiment;
        this._enqueueExposure(name, (0, client_core_1._createConfigExposure)(this._user, result, this._store.getExposureMapping()), options);
        this.$emt({ name: 'experiment_evaluation', experiment: result });
        return result;
    }
    _getConfigListImpl() {
        return this._store.getConfigList();
    }
    _getLayerImpl(name, options) {
        var _a, _b, _c;
        const { result: evaluation, details } = this._store.getLayer(name);
        const layer = (0, client_core_1._makeLayer)(name, details, evaluation);
        const overridden = (_b = (_a = this.overrideAdapter) === null || _a === void 0 ? void 0 : _a.getLayerOverride) === null || _b === void 0 ? void 0 : _b.call(_a, layer, this._user, options);
        if (options === null || options === void 0 ? void 0 : options.disableExposureLog) {
            this._logger.incrementNonExposureCount(name);
        }
        const result = (0, client_core_1._mergeOverride)(layer, overridden, (_c = overridden === null || overridden === void 0 ? void 0 : overridden.__value) !== null && _c !== void 0 ? _c : layer.__value, (param) => {
            if (options === null || options === void 0 ? void 0 : options.disableExposureLog) {
                return;
            }
            this._enqueueExposure(name, (0, client_core_1._createLayerParameterExposure)(this._user, result, param, this._store.getExposureMapping()), options);
        });
        this.$emt({ name: 'layer_evaluation', layer: result });
        return result;
    }
    _getParameterStoreImpl(name, options) {
        var _a, _b;
        const { result: configuration, details } = this._store.getParamStore(name);
        this._logger.incrementNonExposureCount(name);
        const paramStore = {
            name,
            details: details,
            __configuration: configuration,
            get: (0, ParamStoreGetterFactory_1._makeParamStoreGetter)(this, configuration, options),
        };
        const overridden = (_b = (_a = this.overrideAdapter) === null || _a === void 0 ? void 0 : _a.getParamStoreOverride) === null || _b === void 0 ? void 0 : _b.call(_a, paramStore, options);
        if (overridden != null) {
            paramStore.__configuration = overridden.config;
            paramStore.details = overridden.details;
            paramStore.get = (0, ParamStoreGetterFactory_1._makeParamStoreGetter)(this, overridden.config, options);
        }
        return paramStore;
    }
}
exports.default = StatsigClient;
