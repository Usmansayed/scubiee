"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.V1InitializeContainer = void 0;
const client_core_1 = require("@statsig/client-core");
class V1InitializeContainer {
    constructor(_values) {
        this._values = _values;
    }
    getGate(name) {
        return this._getResultFromLookup(this._values.feature_gates, name);
    }
    getConfig(name) {
        return this._getResultFromLookup(this._values.dynamic_configs, name);
    }
    getLayer(name) {
        return this._getResultFromLookup(this._values.layer_configs, name);
    }
    getParamStore(name) {
        return this._getResultFromLookup(this._values.param_stores, name);
    }
    getConfigList() {
        return Object.keys(this._values.dynamic_configs);
    }
    getExposureMapping() {
        return this._values.exposures;
    }
    _getResultFromLookup(lookup, name) {
        var _a, _b;
        if (!lookup) {
            return null;
        }
        return (_b = (_a = lookup[name]) !== null && _a !== void 0 ? _a : lookup[(0, client_core_1._DJB2)(name)]) !== null && _b !== void 0 ? _b : null;
    }
}
exports.V1InitializeContainer = V1InitializeContainer;
