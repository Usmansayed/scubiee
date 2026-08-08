import './$_StatsigGlobal';
import { ErrorBoundary } from './ErrorBoundary';
import { AnyEvaluationOptions, EvaluationOptionsCommon } from './EvaluationOptions';
import { EventLogger } from './EventLogger';
import { MemoPrefix } from './MemoKey';
import { NetworkCore } from './NetworkCore';
import { OverrideAdapter } from './OverrideAdapter';
import { AnyStatsigClientEvent, StatsigClientEventCallback, StatsigClientEventEmitterInterface, StatsigClientEventName, StatsigLoadingStatus } from './StatsigClientEventEmitter';
import { DataAdapterResult, EvaluationsDataAdapter, SpecsDataAdapter } from './StatsigDataAdapter';
import { StatsigEventInternal } from './StatsigEvent';
import { AnyStatsigOptions, StatsigRuntimeMutableOptions } from './StatsigOptionsCommon';
import { StatsigUpdateDetails } from './StatsigUpdateDetails';
import { StorageProvider } from './StorageProvider';
export type StatsigClientEmitEventFunc = (event: AnyStatsigClientEvent) => void;
export type StatsigContext = {
    sdkKey: string;
    options: AnyStatsigOptions;
    sessionID: string;
    values: unknown;
};
export declare abstract class StatsigClientBase<TAdapter extends EvaluationsDataAdapter | SpecsDataAdapter> implements StatsigClientEventEmitterInterface {
    loadingStatus: StatsigLoadingStatus;
    readonly dataAdapter: TAdapter;
    readonly overrideAdapter: OverrideAdapter | null;
    readonly storageProvider: StorageProvider;
    protected readonly _sdkKey: string;
    protected readonly _options: AnyStatsigOptions;
    protected readonly _errorBoundary: ErrorBoundary;
    protected readonly _logger: EventLogger;
    protected _initializePromise: Promise<StatsigUpdateDetails> | null;
    protected _memoCache: Record<string, unknown>;
    private _listeners;
    constructor(sdkKey: string, adapter: TAdapter, network: NetworkCore, options: AnyStatsigOptions | null);
    /**
     * Updates runtime configuration options for the SDK, allowing toggling of certain behaviors such as logging and storage to comply with user preferences or regulations such as GDPR.
     *
     * @param {StatsigRuntimeMutableOptions} options - The configuration options that dictate the runtime behavior of the SDK.
     */
    updateRuntimeOptions(options: StatsigRuntimeMutableOptions): void;
    /**
     * Flushes any currently queued events.
     */
    flush(): Promise<void>;
    /**
     * Gracefully shuts down the SDK, ensuring that all pending events are send before the SDK stops.
     * This function emits a 'pre_shutdown' event and then waits for the logger to complete its shutdown process.
     *
     * @returns {Promise<void>} A promise that resolves when all shutdown procedures, including logging shutdown, have been completed.
     */
    shutdown(): Promise<void>;
    /**
     * Subscribes a callback function to a specific {@link StatsigClientEvent} or all StatsigClientEvents if the wildcard '*' is used.
     * Once subscribed, the listener callback will be invoked whenever the specified event is emitted.
     *
     * @param {StatsigClientEventName} event - The name of the event to subscribe to, or '*' to subscribe to all events.
     * @param {StatsigClientEventCallback<T>} listener - The callback function to execute when the event occurs. The function receives event-specific data as its parameter.
     * @see {@link off} for unsubscribing from events.
     */
    on<T extends StatsigClientEventName>(event: T, listener: StatsigClientEventCallback<T>): void;
    /**
     * Unsubscribes a previously registered callback function from a specific {@link StatsigClientEvent} or all StatsigClientEvents if the wildcard '*' is used.
     *
     * @param {StatsigClientEventName} event - The name of the event from which to unsubscribe, or '*' to unsubscribe from all events.
     * @param {StatsigClientEventCallback<T>} listener - The callback function to remove from the event's notification list.
     * @see {@link on} for subscribing to events.
     */
    off<T extends StatsigClientEventName>(event: T, listener: StatsigClientEventCallback<T>): void;
    $on<T extends StatsigClientEventName>(event: T, listener: StatsigClientEventCallback<T>): void;
    $emt(event: AnyStatsigClientEvent): void;
    protected _setStatus(newStatus: StatsigLoadingStatus, values: DataAdapterResult | null): void;
    protected _enqueueExposure(name: string, exposure: StatsigEventInternal, options?: EvaluationOptionsCommon): void;
    protected _memoize<T, O extends AnyEvaluationOptions>(prefix: MemoPrefix, fn: (name: string, options?: O) => T): (name: string, options?: O) => T;
    protected abstract _primeReadyRipcord(): void;
}
