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
exports.StatsigEvaluationsDataAdapter = void 0;
const client_core_1 = require("@statsig/client-core");
const Network_1 = require("./Network");
class StatsigEvaluationsDataAdapter extends client_core_1.DataAdapterCore {
    constructor() {
        super('EvaluationsDataAdapter', 'evaluations');
        this._network = null;
        this._options = null;
    }
    attach(sdkKey, options, network) {
        super.attach(sdkKey, options, network);
        if (network !== null && network instanceof Network_1.default) {
            this._network = network;
        }
        else {
            this._network = new Network_1.default(options !== null && options !== void 0 ? options : {});
        }
    }
    getDataAsync(current, user, options) {
        return this._getDataAsyncImpl(current, (0, client_core_1._normalizeUser)(user, this._options), options);
    }
    prefetchData(user, options) {
        return this._prefetchDataImpl(user, options);
    }
    setData(data) {
        const values = (0, client_core_1._typedJsonParse)(data, 'has_updates', 'data');
        if (values && 'user' in values) {
            super.setData(data, values.user);
        }
        else {
            client_core_1.Log.error('StatsigUser not found. You may be using an older server SDK version. Please upgrade your SDK or use setDataLegacy.');
        }
    }
    setDataLegacy(data, user) {
        super.setData(data, user);
    }
    _fetchFromNetwork(current, user, options, isCacheValidFor204) {
        return __awaiter(this, void 0, void 0, function* () {
            var _a;
            const result = yield ((_a = this._network) === null || _a === void 0 ? void 0 : _a.fetchEvaluations(this._getSdkKey(), current, options === null || options === void 0 ? void 0 : options.priority, user, isCacheValidFor204));
            return result !== null && result !== void 0 ? result : null;
        });
    }
    _getCacheKey(user) {
        var _a;
        const key = (0, client_core_1._getStorageKey)(this._getSdkKey(), user, (_a = this._options) === null || _a === void 0 ? void 0 : _a.customUserCacheKeyFunc);
        return `${client_core_1.DataAdapterCachePrefix}.${this._cacheSuffix}.${key}`;
    }
    _isCachedResultValidFor204(result, user) {
        return (result.fullUserHash != null &&
            result.fullUserHash === (0, client_core_1._getFullUserHash)(user));
    }
}
exports.StatsigEvaluationsDataAdapter = StatsigEvaluationsDataAdapter;
