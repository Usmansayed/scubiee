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
exports._isDomainFailure = exports.NetworkFallbackResolver = void 0;
const DnsTxtQuery_1 = require("./DnsTxtQuery");
const Hashing_1 = require("./Hashing");
const Log_1 = require("./Log");
const StorageProvider_1 = require("./StorageProvider");
const DEFAULT_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days
const COOLDOWN_TIME_MS = 4 * 60 * 60 * 1000; // 4 hours
class NetworkFallbackResolver {
    constructor(options) {
        var _a;
        this._fallbackInfo = null;
        this._errorBoundary = null;
        this._dnsQueryCooldowns = {};
        this._networkOverrideFunc = (_a = options.networkConfig) === null || _a === void 0 ? void 0 : _a.networkOverrideFunc;
    }
    setErrorBoundary(errorBoundary) {
        this._errorBoundary = errorBoundary;
    }
    tryBumpExpiryTime(sdkKey, urlConfig) {
        var _a;
        const info = (_a = this._fallbackInfo) === null || _a === void 0 ? void 0 : _a[urlConfig.endpoint];
        if (!info) {
            return;
        }
        info.expiryTime = Date.now() + DEFAULT_TTL_MS;
        _tryWriteFallbackInfoToCache(sdkKey, Object.assign(Object.assign({}, this._fallbackInfo), { [urlConfig.endpoint]: info }));
    }
    getActiveFallbackUrl(sdkKey, urlConfig) {
        var _a, _b;
        if (urlConfig.customUrl != null && urlConfig.fallbackUrls != null) {
            return null;
        }
        let info = this._fallbackInfo;
        if (info == null) {
            info = (_a = _readFallbackInfoFromCache(sdkKey)) !== null && _a !== void 0 ? _a : {};
            this._fallbackInfo = info;
        }
        const entry = info[urlConfig.endpoint];
        if (!entry ||
            Date.now() > ((_b = entry.expiryTime) !== null && _b !== void 0 ? _b : 0) ||
            urlConfig.getChecksum() !== entry.urlConfigChecksum) {
            delete info[urlConfig.endpoint];
            this._fallbackInfo = info;
            _tryWriteFallbackInfoToCache(sdkKey, this._fallbackInfo);
            return null;
        }
        if (entry.url) {
            return entry.url;
        }
        return null;
    }
    tryFetchUpdatedFallbackInfo(sdkKey, urlConfig, errorMessage, timedOut) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a, _b;
            try {
                if (!_isDomainFailure(errorMessage, timedOut)) {
                    return false;
                }
                const canUseNetworkFallbacks = urlConfig.customUrl == null && urlConfig.fallbackUrls == null;
                const urls = canUseNetworkFallbacks
                    ? yield this._tryFetchFallbackUrlsFromNetwork(urlConfig)
                    : urlConfig.fallbackUrls;
                const newUrl = this._pickNewFallbackUrl((_a = this._fallbackInfo) === null || _a === void 0 ? void 0 : _a[urlConfig.endpoint], urls);
                if (!newUrl) {
                    return false;
                }
                this._updateFallbackInfoWithNewUrl(sdkKey, urlConfig, newUrl);
                return true;
            }
            catch (error) {
                (_b = this._errorBoundary) === null || _b === void 0 ? void 0 : _b.logError('tryFetchUpdatedFallbackInfo', error);
                return false;
            }
        });
    }
    _updateFallbackInfoWithNewUrl(sdkKey, urlConfig, newUrl) {
        var _a, _b, _c;
        const newFallbackInfo = {
            urlConfigChecksum: urlConfig.getChecksum(),
            url: newUrl,
            expiryTime: Date.now() + DEFAULT_TTL_MS,
            previous: [],
        };
        const endpoint = urlConfig.endpoint;
        const previousInfo = (_a = this._fallbackInfo) === null || _a === void 0 ? void 0 : _a[endpoint];
        if (previousInfo) {
            newFallbackInfo.previous.push(...previousInfo.previous);
        }
        if (newFallbackInfo.previous.length > 10) {
            newFallbackInfo.previous = [];
        }
        const previousUrl = (_c = (_b = this._fallbackInfo) === null || _b === void 0 ? void 0 : _b[endpoint]) === null || _c === void 0 ? void 0 : _c.url;
        if (previousUrl != null) {
            newFallbackInfo.previous.push(previousUrl);
        }
        this._fallbackInfo = Object.assign(Object.assign({}, this._fallbackInfo), { [endpoint]: newFallbackInfo });
        _tryWriteFallbackInfoToCache(sdkKey, this._fallbackInfo);
    }
    _tryFetchFallbackUrlsFromNetwork(urlConfig) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a;
            const cooldown = this._dnsQueryCooldowns[urlConfig.endpoint];
            if (cooldown && Date.now() < cooldown) {
                return null;
            }
            this._dnsQueryCooldowns[urlConfig.endpoint] = Date.now() + COOLDOWN_TIME_MS;
            const result = [];
            const records = yield (0, DnsTxtQuery_1._fetchTxtRecords)((_a = this._networkOverrideFunc) !== null && _a !== void 0 ? _a : fetch);
            const path = _extractPathFromUrl(urlConfig.defaultUrl);
            for (const record of records) {
                if (!record.startsWith(urlConfig.endpointDnsKey + '=')) {
                    continue;
                }
                const parts = record.split('=');
                if (parts.length > 1) {
                    let baseUrl = parts[1];
                    if (baseUrl.endsWith('/')) {
                        baseUrl = baseUrl.slice(0, -1);
                    }
                    result.push(`https://${baseUrl}${path}`);
                }
            }
            return result;
        });
    }
    _pickNewFallbackUrl(currentFallbackInfo, urls) {
        var _a;
        if (urls == null) {
            return null;
        }
        const previouslyUsed = new Set((_a = currentFallbackInfo === null || currentFallbackInfo === void 0 ? void 0 : currentFallbackInfo.previous) !== null && _a !== void 0 ? _a : []);
        const currentFallbackUrl = currentFallbackInfo === null || currentFallbackInfo === void 0 ? void 0 : currentFallbackInfo.url;
        let found = null;
        for (const loopUrl of urls) {
            const url = loopUrl.endsWith('/') ? loopUrl.slice(0, -1) : loopUrl;
            if (!previouslyUsed.has(loopUrl) && url !== currentFallbackUrl) {
                found = url;
                break;
            }
        }
        return found;
    }
}
exports.NetworkFallbackResolver = NetworkFallbackResolver;
function _isDomainFailure(errorMsg, timedOut) {
    var _a;
    const lowerErrorMsg = (_a = errorMsg === null || errorMsg === void 0 ? void 0 : errorMsg.toLowerCase()) !== null && _a !== void 0 ? _a : '';
    return (timedOut ||
        lowerErrorMsg.includes('uncaught exception') ||
        lowerErrorMsg.includes('failed to fetch') ||
        lowerErrorMsg.includes('networkerror when attempting to fetch resource'));
}
exports._isDomainFailure = _isDomainFailure;
function _getFallbackInfoStorageKey(sdkKey) {
    return `statsig.network_fallback.${(0, Hashing_1._DJB2)(sdkKey)}`;
}
function _tryWriteFallbackInfoToCache(sdkKey, info) {
    const hashKey = _getFallbackInfoStorageKey(sdkKey);
    if (!info || Object.keys(info).length === 0) {
        StorageProvider_1.Storage.removeItem(hashKey);
        return;
    }
    StorageProvider_1.Storage.setItem(hashKey, JSON.stringify(info));
}
function _readFallbackInfoFromCache(sdkKey) {
    const hashKey = _getFallbackInfoStorageKey(sdkKey);
    const data = StorageProvider_1.Storage.getItem(hashKey);
    if (!data) {
        return null;
    }
    try {
        return JSON.parse(data);
    }
    catch (_a) {
        Log_1.Log.error('Failed to parse FallbackInfo');
        return null;
    }
}
function _extractPathFromUrl(urlString) {
    try {
        const url = new URL(urlString);
        return url.pathname;
    }
    catch (error) {
        return null;
    }
}
