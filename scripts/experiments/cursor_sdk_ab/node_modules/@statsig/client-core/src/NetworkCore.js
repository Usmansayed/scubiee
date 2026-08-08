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
exports.NetworkCore = void 0;
require("./$_StatsigGlobal");
const __StatsigGlobal_1 = require("./$_StatsigGlobal");
const Diagnostics_1 = require("./Diagnostics");
const Log_1 = require("./Log");
const NetworkConfig_1 = require("./NetworkConfig");
const NetworkFallbackResolver_1 = require("./NetworkFallbackResolver");
const SDKFlags_1 = require("./SDKFlags");
const SDKType_1 = require("./SDKType");
const SafeJs_1 = require("./SafeJs");
const SessionID_1 = require("./SessionID");
const StableID_1 = require("./StableID");
const StatsigClientEventEmitter_1 = require("./StatsigClientEventEmitter");
const StatsigMetadata_1 = require("./StatsigMetadata");
const StatsigOptionsCommon_1 = require("./StatsigOptionsCommon");
const VisibilityObserving_1 = require("./VisibilityObserving");
const DEFAULT_TIMEOUT_MS = 10000;
const BACKOFF_BASE_MS = 500;
const BACKOFF_MAX_MS = 30000;
const RATE_LIMIT_WINDOW_MS = 1000;
const RATE_LIMIT_MAX_REQ_COUNT = 50;
const LEAK_RATE = RATE_LIMIT_MAX_REQ_COUNT / RATE_LIMIT_WINDOW_MS;
const RETRYABLE_CODES = new Set([408, 500, 502, 503, 504, 522, 524, 599]);
class NetworkCore {
    constructor(options, _emitter) {
        this._emitter = _emitter;
        this._errorBoundary = null;
        this._timeout = DEFAULT_TIMEOUT_MS;
        this._netConfig = {};
        this._options = {};
        this._leakyBucket = {};
        this._lastUsedInitUrl = null;
        if (options) {
            this._options = options;
        }
        if (this._options.networkConfig) {
            this._netConfig = this._options.networkConfig;
        }
        if (this._netConfig.networkTimeoutMs) {
            this._timeout = this._netConfig.networkTimeoutMs;
        }
        this._fallbackResolver = new NetworkFallbackResolver_1.NetworkFallbackResolver(this._options);
        this.setLogEventCompressionMode(this._getLogEventCompressionMode(options));
    }
    setLogEventCompressionMode(mode) {
        this._options.logEventCompressionMode = mode;
    }
    setErrorBoundary(errorBoundary) {
        this._errorBoundary = errorBoundary;
        this._errorBoundary.wrap(this);
        this._errorBoundary.wrap(this._fallbackResolver);
        this._fallbackResolver.setErrorBoundary(errorBoundary);
    }
    isBeaconSupported() {
        return (typeof navigator !== 'undefined' &&
            typeof navigator.sendBeacon === 'function');
    }
    getLastUsedInitUrlAndReset() {
        const tempUrl = this._lastUsedInitUrl;
        this._lastUsedInitUrl = null;
        return tempUrl;
    }
    beacon(args) {
        if (!_ensureValidSdkKey(args)) {
            return false;
        }
        const argsInternal = this._getInternalRequestArgs('POST', args);
        const url = this._getPopulatedURL(argsInternal);
        const nav = navigator;
        return nav.sendBeacon.bind(nav)(url, argsInternal.body);
    }
    post(args) {
        return __awaiter(this, void 0, void 0, function* () {
            const argsInternal = this._getInternalRequestArgs('POST', args);
            this._tryEncodeBody(argsInternal);
            yield this._tryToCompressBody(argsInternal);
            return this._sendRequest(argsInternal);
        });
    }
    get(args) {
        const argsInternal = this._getInternalRequestArgs('GET', args);
        return this._sendRequest(argsInternal);
    }
    _sendRequest(args) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a, _b, _c, _d;
            if (!_ensureValidSdkKey(args)) {
                return null;
            }
            if (this._netConfig.preventAllNetworkTraffic) {
                return null;
            }
            const { method, body, retries, attempt } = args;
            const endpoint = args.urlConfig.endpoint;
            if (this._isRateLimited(endpoint)) {
                Log_1.Log.warn(`Request to ${endpoint} was blocked because you are making requests too frequently.`);
                return null;
            }
            const currentAttempt = attempt !== null && attempt !== void 0 ? attempt : 1;
            let reqTimedOut = false;
            const populatedUrl = this._getPopulatedURL(args);
            let response = null;
            const keepalive = (0, VisibilityObserving_1._isUnloading)();
            try {
                const config = {
                    method,
                    body,
                    headers: Object.assign({}, args.headers),
                    priority: args.priority,
                    keepalive,
                };
                _tryMarkInitStart(args, currentAttempt);
                const bucket = this._leakyBucket[endpoint];
                if (bucket) {
                    bucket.lastRequestTime = Date.now();
                    this._leakyBucket[endpoint] = bucket;
                }
                const func = (_a = this._netConfig.networkOverrideFunc) !== null && _a !== void 0 ? _a : fetch;
                let timeoutId;
                response = yield Promise.race([
                    func(populatedUrl, config).finally(() => clearTimeout(timeoutId)),
                    new Promise((_, reject) => {
                        timeoutId = setTimeout(() => {
                            reqTimedOut = true;
                            reject(new Error(`Timeout of ${this._timeout}ms expired.`));
                        }, this._timeout);
                    }),
                ]);
                if (!response.ok) {
                    const text = yield response.text().catch(() => 'No Text');
                    const err = new Error(`NetworkError: ${populatedUrl} ${text}`);
                    err.name = 'NetworkError';
                    throw err;
                }
                const text = yield response.text();
                _tryMarkInitEnd(args, response, currentAttempt, text);
                this._fallbackResolver.tryBumpExpiryTime(args.sdkKey, args.urlConfig);
                return {
                    body: text,
                    code: response.status,
                };
            }
            catch (error) {
                const errorMessage = _getErrorMessage(error);
                const timedOut = _didTimeout(errorMessage !== null && errorMessage !== void 0 ? errorMessage : '', reqTimedOut);
                _tryMarkInitEnd(args, response, currentAttempt, '', error);
                const fallbackUpdated = yield this._fallbackResolver.tryFetchUpdatedFallbackInfo(args.sdkKey, args.urlConfig, errorMessage, timedOut);
                if (fallbackUpdated) {
                    args.fallbackUrl = this._fallbackResolver.getActiveFallbackUrl(args.sdkKey, args.urlConfig);
                }
                if (!retries ||
                    currentAttempt > retries ||
                    !RETRYABLE_CODES.has((_b = response === null || response === void 0 ? void 0 : response.status) !== null && _b !== void 0 ? _b : 500)) {
                    (_c = this._emitter) === null || _c === void 0 ? void 0 : _c.call(this, {
                        name: 'error',
                        error,
                        tag: StatsigClientEventEmitter_1.ErrorTag.NetworkError,
                        requestArgs: args,
                    });
                    const formattedErrorMsg = `A networking error occurred during ${method} request to ${populatedUrl}.`;
                    Log_1.Log.error(formattedErrorMsg, errorMessage, error);
                    (_d = this._errorBoundary) === null || _d === void 0 ? void 0 : _d.attachErrorIfNoneExists(formattedErrorMsg);
                    return null;
                }
                yield _exponentialBackoff(currentAttempt);
                return this._sendRequest(Object.assign(Object.assign({}, args), { retries, attempt: currentAttempt + 1 }));
            }
        });
    }
    _getLogEventCompressionMode(options) {
        // Handle backward compatibility for deprecated disableCompression flag
        let compressionMode = options === null || options === void 0 ? void 0 : options.logEventCompressionMode;
        if (!compressionMode && (options === null || options === void 0 ? void 0 : options.disableCompression) === true) {
            compressionMode = StatsigOptionsCommon_1.LogEventCompressionMode.Disabled;
        }
        // Default to enabled if unset
        if (!compressionMode) {
            compressionMode = StatsigOptionsCommon_1.LogEventCompressionMode.Enabled;
        }
        return compressionMode;
    }
    _isRateLimited(endpoint) {
        var _a;
        const now = Date.now();
        const bucket = (_a = this._leakyBucket[endpoint]) !== null && _a !== void 0 ? _a : {
            count: 0,
            lastRequestTime: now,
        };
        const elapsed = now - bucket.lastRequestTime;
        const leakedRequests = Math.floor(elapsed * LEAK_RATE);
        bucket.count = Math.max(0, bucket.count - leakedRequests);
        if (bucket.count >= RATE_LIMIT_MAX_REQ_COUNT) {
            return true;
        }
        bucket.count += 1;
        bucket.lastRequestTime = now;
        this._leakyBucket[endpoint] = bucket;
        return false;
    }
    _getPopulatedURL(args) {
        var _a;
        const url = (_a = args.fallbackUrl) !== null && _a !== void 0 ? _a : args.urlConfig.getUrl();
        if (args.urlConfig.endpoint === NetworkConfig_1.Endpoint._initialize ||
            args.urlConfig.endpoint === NetworkConfig_1.Endpoint._download_config_specs) {
            this._lastUsedInitUrl = url;
        }
        const params = Object.assign({ [NetworkConfig_1.NetworkParam.SdkKey]: args.sdkKey, [NetworkConfig_1.NetworkParam.SdkType]: SDKType_1.SDKType._get(args.sdkKey), [NetworkConfig_1.NetworkParam.SdkVersion]: StatsigMetadata_1.SDK_VERSION, [NetworkConfig_1.NetworkParam.Time]: String(Date.now()), [NetworkConfig_1.NetworkParam.SessionID]: SessionID_1.SessionID.get(args.sdkKey) }, args.params);
        const query = Object.keys(params)
            .map((key) => {
            return `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`;
        })
            .join('&');
        return `${url}${query ? `?${query}` : ''}`;
    }
    _tryEncodeBody(args) {
        var _a;
        const win = (0, SafeJs_1._getWindowSafe)();
        const body = args.body;
        if (!args.isStatsigEncodable ||
            this._options.disableStatsigEncoding ||
            typeof body !== 'string' ||
            (0, __StatsigGlobal_1._getStatsigGlobalFlag)('no-encode') != null ||
            !(win === null || win === void 0 ? void 0 : win.btoa)) {
            return;
        }
        try {
            args.body = win.btoa(body).split('').reverse().join('');
            args.params = Object.assign(Object.assign({}, ((_a = args.params) !== null && _a !== void 0 ? _a : {})), { [NetworkConfig_1.NetworkParam.StatsigEncoded]: '1' });
        }
        catch (e) {
            Log_1.Log.warn(`Request encoding failed for ${args.urlConfig.getUrl()}`, e);
        }
    }
    _tryToCompressBody(args) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a;
            const body = args.body;
            if (typeof body !== 'string' || !_allowCompression(args, this._options)) {
                return;
            }
            try {
                const bytes = new TextEncoder().encode(body);
                const stream = new CompressionStream('gzip');
                const writer = stream.writable.getWriter();
                writer.write(bytes).catch(Log_1.Log.error);
                writer.close().catch(Log_1.Log.error);
                const reader = stream.readable.getReader();
                const chunks = [];
                let result;
                // eslint-disable-next-line no-await-in-loop
                while (!(result = yield reader.read()).done) {
                    chunks.push(result.value);
                }
                const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
                const combined = new Uint8Array(totalLength);
                let offset = 0;
                for (const chunk of chunks) {
                    combined.set(chunk, offset);
                    offset += chunk.length;
                }
                args.body = combined;
                args.params = Object.assign(Object.assign({}, ((_a = args.params) !== null && _a !== void 0 ? _a : {})), { [NetworkConfig_1.NetworkParam.IsGzipped]: '1' });
            }
            catch (e) {
                Log_1.Log.warn(`Request compression failed for ${args.urlConfig.getUrl()}`, e);
            }
        });
    }
    _getInternalRequestArgs(method, args) {
        const fallbackUrl = this._fallbackResolver.getActiveFallbackUrl(args.sdkKey, args.urlConfig);
        const result = Object.assign(Object.assign({}, args), { method,
            fallbackUrl });
        if ('data' in args) {
            _populateRequestBody(result, args.data);
        }
        return result;
    }
}
exports.NetworkCore = NetworkCore;
const _ensureValidSdkKey = (args) => {
    if (!args.sdkKey) {
        Log_1.Log.warn('Unable to make request without an SDK key');
        return false;
    }
    return true;
};
const _populateRequestBody = (args, data) => {
    const { sdkKey, fallbackUrl } = args;
    const stableID = StableID_1.StableID.get(sdkKey);
    const sessionID = SessionID_1.SessionID.get(sdkKey);
    const sdkType = SDKType_1.SDKType._get(sdkKey);
    args.body = JSON.stringify(Object.assign(Object.assign({}, data), { statsigMetadata: Object.assign(Object.assign({}, StatsigMetadata_1.StatsigMetadataProvider.get()), { stableID,
            sessionID,
            sdkType,
            fallbackUrl }) }));
};
function _allowCompression(args, options) {
    if (!args.isCompressable) {
        return false;
    }
    // Never compress if 'no-compress' is set globally or required APIs are unavailable
    if ((0, __StatsigGlobal_1._getStatsigGlobalFlag)('no-compress') != null ||
        typeof CompressionStream === 'undefined' ||
        typeof TextEncoder === 'undefined') {
        return false;
    }
    const isProxy = args.urlConfig.customUrl != null || args.urlConfig.fallbackUrls != null;
    const flagEnabled = SDKFlags_1.SDKFlags.get(args.sdkKey, 'enable_log_event_compression') === true;
    switch (options.logEventCompressionMode) {
        case StatsigOptionsCommon_1.LogEventCompressionMode.Disabled:
            return false;
        case StatsigOptionsCommon_1.LogEventCompressionMode.Enabled:
            // Only compress through proxy if flag is explicitly on
            if (isProxy && !flagEnabled) {
                return false;
            }
            return true;
        case StatsigOptionsCommon_1.LogEventCompressionMode.Forced:
            return true;
        default:
            return false;
    }
}
function _getErrorMessage(error) {
    if (typeof error === 'string') {
        return error;
    }
    if (error instanceof Error) {
        return `${error.name}: ${error.message}`;
    }
    return 'Unknown Error';
}
function _didTimeout(errorMsg, abortedByTimeout) {
    const timeout = errorMsg.includes('Timeout'); // probably not needed but just in case
    return timeout || abortedByTimeout;
}
function _tryMarkInitStart(args, attempt) {
    if (args.urlConfig.endpoint !== NetworkConfig_1.Endpoint._initialize) {
        return;
    }
    Diagnostics_1.Diagnostics._markInitNetworkReqStart(args.sdkKey, {
        attempt,
    });
}
function _tryMarkInitEnd(args, response, attempt, body, err) {
    if (args.urlConfig.endpoint !== NetworkConfig_1.Endpoint._initialize) {
        return;
    }
    Diagnostics_1.Diagnostics._markInitNetworkReqEnd(args.sdkKey, Diagnostics_1.Diagnostics._getDiagnosticsData(response, attempt, body, err));
}
function _exponentialBackoff(attempt) {
    return __awaiter(this, void 0, void 0, function* () {
        // 1*1*1000 1s
        // 2*2*1000 4s
        // 3*3*1000 9s
        // 4*4*1000 16s
        // 5*5*1000 25s
        yield new Promise((r) => setTimeout(r, Math.min(BACKOFF_BASE_MS * (attempt * attempt), BACKOFF_MAX_MS)));
    });
}
