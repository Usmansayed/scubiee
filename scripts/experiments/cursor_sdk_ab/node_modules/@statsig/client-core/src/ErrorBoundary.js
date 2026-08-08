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
exports.ErrorBoundary = exports.EXCEPTION_ENDPOINT = void 0;
const Log_1 = require("./Log");
const SDKType_1 = require("./SDKType");
const StatsigMetadata_1 = require("./StatsigMetadata");
exports.EXCEPTION_ENDPOINT = 'https://statsigapi.net/v1/sdk_exception';
const UNKNOWN_ERROR = '[Statsig] UnknownError';
class ErrorBoundary {
    constructor(_sdkKey, _options, _emitter, _lastSeenError) {
        this._sdkKey = _sdkKey;
        this._options = _options;
        this._emitter = _emitter;
        this._lastSeenError = _lastSeenError;
        this._seen = new Set();
    }
    wrap(instance, namePrefix) {
        try {
            const obj = instance;
            _getAllInstanceMethodNames(obj).forEach((name) => {
                const original = obj[name];
                if ('$EB' in original) {
                    return;
                }
                obj[name] = (...args) => {
                    return this._capture(namePrefix ? `${namePrefix}:${name}` : name, () => original.apply(instance, args));
                };
                obj[name].$EB = true;
            });
        }
        catch (err) {
            this._onError('eb:wrap', err);
        }
    }
    logError(tag, error) {
        this._onError(tag, error);
    }
    getLastSeenErrorAndReset() {
        const tempError = this._lastSeenError;
        this._lastSeenError = undefined;
        return tempError !== null && tempError !== void 0 ? tempError : null;
    }
    attachErrorIfNoneExists(error) {
        if (this._lastSeenError) {
            return;
        }
        this._lastSeenError = _resolveError(error);
    }
    _capture(tag, task) {
        try {
            const res = task();
            if (res && res instanceof Promise) {
                return res.catch((err) => this._onError(tag, err));
            }
            return res;
        }
        catch (error) {
            this._onError(tag, error);
            return null;
        }
    }
    _onError(tag, error) {
        try {
            Log_1.Log.warn(`Caught error in ${tag}`, { error });
            const impl = () => __awaiter(this, void 0, void 0, function* () {
                var _a, _b, _c, _d, _e, _f, _g;
                const unwrapped = (error ? error : Error(UNKNOWN_ERROR));
                const isError = unwrapped instanceof Error;
                const name = isError ? unwrapped.name : 'No Name';
                const resolvedError = _resolveError(unwrapped);
                this._lastSeenError = resolvedError;
                if (this._seen.has(name)) {
                    return;
                }
                this._seen.add(name);
                if ((_b = (_a = this._options) === null || _a === void 0 ? void 0 : _a.networkConfig) === null || _b === void 0 ? void 0 : _b.preventAllNetworkTraffic) {
                    (_c = this._emitter) === null || _c === void 0 ? void 0 : _c.call(this, {
                        name: 'error',
                        error,
                        tag,
                    });
                    return;
                }
                const sdkType = SDKType_1.SDKType._get(this._sdkKey);
                const statsigMetadata = StatsigMetadata_1.StatsigMetadataProvider.get();
                const info = isError ? unwrapped.stack : _getDescription(unwrapped);
                const body = Object.assign({ tag, exception: name, info, statsigOptions: _getStatsigOptionLoggingCopy(this._options) }, Object.assign(Object.assign({}, statsigMetadata), { sdkType }));
                const func = (_f = (_e = (_d = this._options) === null || _d === void 0 ? void 0 : _d.networkConfig) === null || _e === void 0 ? void 0 : _e.networkOverrideFunc) !== null && _f !== void 0 ? _f : fetch;
                yield func(exports.EXCEPTION_ENDPOINT, {
                    method: 'POST',
                    headers: {
                        'STATSIG-API-KEY': this._sdkKey,
                        'STATSIG-SDK-TYPE': String(sdkType),
                        'STATSIG-SDK-VERSION': String(statsigMetadata.sdkVersion),
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(body),
                });
                (_g = this._emitter) === null || _g === void 0 ? void 0 : _g.call(this, {
                    name: 'error',
                    error,
                    tag,
                });
            });
            impl()
                .then(() => {
                /* noop */
            })
                .catch(() => {
                /* noop */
            });
        }
        catch (_error) {
            /* noop */
        }
    }
}
exports.ErrorBoundary = ErrorBoundary;
function _resolveError(error) {
    if (error instanceof Error) {
        return error;
    }
    else if (typeof error === 'string') {
        return new Error(error);
    }
    else {
        return new Error('An unknown error occurred.');
    }
}
function _getDescription(obj) {
    try {
        return JSON.stringify(obj);
    }
    catch (_a) {
        return UNKNOWN_ERROR;
    }
}
function _getAllInstanceMethodNames(instance) {
    const names = new Set();
    let proto = Object.getPrototypeOf(instance);
    while (proto && proto !== Object.prototype) {
        Object.getOwnPropertyNames(proto)
            .filter((prop) => typeof (proto === null || proto === void 0 ? void 0 : proto[prop]) === 'function')
            .forEach((name) => names.add(name));
        proto = Object.getPrototypeOf(proto);
    }
    return Array.from(names);
}
function _getStatsigOptionLoggingCopy(options) {
    if (!options) {
        return {};
    }
    const loggingCopy = {};
    Object.keys(options).forEach((key) => {
        const option = key;
        const value = options[option];
        const valueType = typeof value;
        switch (valueType) {
            case 'number':
            case 'bigint':
            case 'boolean':
                loggingCopy[String(option)] = value;
                break;
            case 'string':
                if (value.length < 50) {
                    loggingCopy[String(option)] = value;
                }
                else {
                    loggingCopy[String(option)] = 'set';
                }
                break;
            case 'object':
                if (option === 'environment') {
                    loggingCopy['environment'] = value;
                }
                else if (option === 'networkConfig') {
                    loggingCopy['networkConfig'] = value;
                }
                else {
                    loggingCopy[String(option)] = value != null ? 'set' : 'unset';
                }
                break;
            default:
            // Ignore other fields
        }
    });
    return loggingCopy;
}
