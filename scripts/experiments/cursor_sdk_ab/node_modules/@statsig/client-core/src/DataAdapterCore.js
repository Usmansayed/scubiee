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
exports._makeDataAdapterResult = exports.DataAdapterCore = void 0;
const Log_1 = require("./Log");
const StableID_1 = require("./StableID");
const StatsigUser_1 = require("./StatsigUser");
const StorageProvider_1 = require("./StorageProvider");
const TypedJsonParse_1 = require("./TypedJsonParse");
const CACHE_LIMIT = 10;
const MAX_CACHE_WRITE_ATTEMPTS = 8;
class DataAdapterCore {
    constructor(_adapterName, _cacheSuffix) {
        this._adapterName = _adapterName;
        this._cacheSuffix = _cacheSuffix;
        this._options = null;
        this._sdkKey = null;
        this._cacheLimit = CACHE_LIMIT;
        this._lastModifiedStoreKey = `statsig.last_modified_time.${_cacheSuffix}`;
        this._inMemoryCache = new InMemoryCache();
    }
    attach(sdkKey, options, _network) {
        this._sdkKey = sdkKey;
        this._options = options;
    }
    getDataSync(user) {
        const normalized = user && (0, StatsigUser_1._normalizeUser)(user, this._options);
        const cacheKey = this._getCacheKey(normalized);
        const inMem = this._inMemoryCache.get(cacheKey, normalized);
        if (inMem && this._getIsCacheValueValid(inMem)) {
            return inMem;
        }
        const cache = this._loadFromCache(cacheKey);
        if (cache && this._getIsCacheValueValid(cache)) {
            this._inMemoryCache.add(cacheKey, cache, this._cacheLimit);
            return this._inMemoryCache.get(cacheKey, normalized);
        }
        return null;
    }
    setData(data, user) {
        const normalized = user && (0, StatsigUser_1._normalizeUser)(user, this._options);
        const cacheKey = this._getCacheKey(normalized);
        this._inMemoryCache.add(cacheKey, _makeDataAdapterResult('Bootstrap', data, null, normalized), this._cacheLimit);
    }
    _getIsCacheValueValid(current) {
        return (current.stableID == null ||
            current.stableID === StableID_1.StableID.get(this._getSdkKey()));
    }
    _getDataAsyncImpl(current, user, options) {
        return __awaiter(this, void 0, void 0, function* () {
            if (!StorageProvider_1.Storage.isReady()) {
                yield StorageProvider_1.Storage.isReadyResolver();
            }
            const cache = current !== null && current !== void 0 ? current : this.getDataSync(user);
            const ops = [this._fetchAndPrepFromNetwork(cache, user, options)];
            if (options === null || options === void 0 ? void 0 : options.timeoutMs) {
                ops.push(new Promise((r) => setTimeout(r, options.timeoutMs)).then(() => {
                    Log_1.Log.debug('Fetching latest value timed out');
                    return null;
                }));
            }
            return yield Promise.race(ops);
        });
    }
    _prefetchDataImpl(user, options) {
        return __awaiter(this, void 0, void 0, function* () {
            const normalized = user && (0, StatsigUser_1._normalizeUser)(user, this._options);
            const cacheKey = this._getCacheKey(normalized);
            const result = yield this._getDataAsyncImpl(null, normalized, options);
            if (result) {
                this._inMemoryCache.add(cacheKey, Object.assign(Object.assign({}, result), { source: 'Prefetch' }), this._cacheLimit);
            }
        });
    }
    _fetchAndPrepFromNetwork(cachedResult, user, options) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a;
            const cachedData = (_a = cachedResult === null || cachedResult === void 0 ? void 0 : cachedResult.data) !== null && _a !== void 0 ? _a : null;
            const isCacheValidFor204 = cachedResult != null &&
                this._isCachedResultValidFor204(cachedResult, user);
            const latest = yield this._fetchFromNetwork(cachedData, user, options, isCacheValidFor204);
            if (!latest) {
                Log_1.Log.debug('No response returned for latest value');
                return null;
            }
            const response = (0, TypedJsonParse_1._typedJsonParse)(latest, 'has_updates', 'Response');
            const sdkKey = this._getSdkKey();
            const stableID = StableID_1.StableID.get(sdkKey);
            let result = null;
            if ((response === null || response === void 0 ? void 0 : response.has_updates) === true) {
                result = _makeDataAdapterResult('Network', latest, stableID, user);
            }
            else if (cachedData && (response === null || response === void 0 ? void 0 : response.has_updates) === false) {
                result = _makeDataAdapterResult('NetworkNotModified', cachedData, stableID, user);
            }
            else {
                return null;
            }
            const cacheKey = this._getCacheKey(user);
            this._inMemoryCache.add(cacheKey, result, this._cacheLimit);
            this._writeToCache(cacheKey, result);
            return result;
        });
    }
    _getSdkKey() {
        if (this._sdkKey != null) {
            return this._sdkKey;
        }
        Log_1.Log.error(`${this._adapterName} is not attached to a Client`);
        return '';
    }
    _loadFromCache(cacheKey) {
        var _a;
        const cache = (_a = StorageProvider_1.Storage.getItem) === null || _a === void 0 ? void 0 : _a.call(StorageProvider_1.Storage, cacheKey);
        if (cache == null) {
            return null;
        }
        const result = (0, TypedJsonParse_1._typedJsonParse)(cache, 'source', 'Cached Result');
        return result ? Object.assign(Object.assign({}, result), { source: 'Cache' }) : null;
    }
    _writeToCache(cacheKey, result) {
        const resultString = JSON.stringify(result);
        for (let i = 0; i < MAX_CACHE_WRITE_ATTEMPTS; i++) {
            try {
                StorageProvider_1.Storage.setItem(cacheKey, resultString);
                break;
            }
            catch (error) {
                if (!(error instanceof Error) ||
                    !(error.toString().includes('QuotaExceededError') ||
                        error.toString().includes('QUOTA_EXCEEDED_ERR')) ||
                    this._cacheLimit <= 1) {
                    throw error;
                }
                this._cacheLimit = Math.ceil(this._cacheLimit / 2);
                this._runLocalStorageCacheEviction(cacheKey, this._cacheLimit - 1);
            }
        }
        this._runLocalStorageCacheEviction(cacheKey);
    }
    _runLocalStorageCacheEviction(cacheKey, cacheLimit = this._cacheLimit) {
        var _a;
        const lastModifiedTimeMap = (_a = (0, StorageProvider_1._getObjectFromStorage)(this._lastModifiedStoreKey)) !== null && _a !== void 0 ? _a : {};
        lastModifiedTimeMap[cacheKey] = Date.now();
        const evictableKeys = _getEvictableKeys(lastModifiedTimeMap, cacheLimit);
        for (const evictable of evictableKeys) {
            delete lastModifiedTimeMap[evictable];
            StorageProvider_1.Storage.removeItem(evictable);
        }
        (0, StorageProvider_1._setObjectInStorage)(this._lastModifiedStoreKey, lastModifiedTimeMap);
    }
}
exports.DataAdapterCore = DataAdapterCore;
function _makeDataAdapterResult(source, data, stableID, user) {
    return {
        source,
        data,
        receivedAt: Date.now(),
        stableID,
        fullUserHash: (0, StatsigUser_1._getFullUserHash)(user),
    };
}
exports._makeDataAdapterResult = _makeDataAdapterResult;
class InMemoryCache {
    constructor() {
        this._data = {};
    }
    get(cacheKey, user) {
        var _a;
        const result = this._data[cacheKey];
        const cached = result === null || result === void 0 ? void 0 : result.stableID;
        const provided = (_a = user === null || user === void 0 ? void 0 : user.customIDs) === null || _a === void 0 ? void 0 : _a.stableID;
        if (provided && cached && provided !== cached) {
            Log_1.Log.warn("'StatsigUser.customIDs.stableID' mismatch");
            return null;
        }
        return result;
    }
    add(cacheKey, value, cacheLimit) {
        const evictableKeys = _getEvictableKeys(this._data, cacheLimit - 1);
        for (const evictable of evictableKeys) {
            delete this._data[evictable];
        }
        this._data[cacheKey] = value;
    }
    merge(values) {
        this._data = Object.assign(Object.assign({}, this._data), values);
    }
}
function _getEvictableKeys(data, limit) {
    const keys = Object.keys(data);
    if (keys.length <= limit) {
        return [];
    }
    if (limit === 0) {
        return keys;
    }
    return keys
        .sort((keyA, keyB) => {
        const valueA = data[keyA];
        const valueB = data[keyB];
        if (typeof valueA === 'object' && typeof valueB === 'object') {
            return valueA.receivedAt - valueB.receivedAt;
        }
        return valueA - valueB;
    })
        .slice(0, keys.length - limit);
}
