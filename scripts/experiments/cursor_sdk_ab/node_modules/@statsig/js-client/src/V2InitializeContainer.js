"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.V2InitializeContainer = void 0;
const client_core_1 = require("@statsig/client-core");
class V2InitializeContainer {
    constructor(_values) {
        this._values = _values;
    }
    getGate(name) {
        var _a, _b, _c;
        const evalV2 = this._getResultFromLookup(this._values.feature_gates, name);
        if (!evalV2) {
            return null;
        }
        return {
            name: name,
            value: evalV2.v === true,
            rule_id: (_a = evalV2.r) !== null && _a !== void 0 ? _a : 'default',
            secondary_exposures: (_b = evalV2.s) !== null && _b !== void 0 ? _b : [],
            id_type: (_c = evalV2.i) !== null && _c !== void 0 ? _c : '',
        };
    }
    getConfig(name) {
        var _a, _b, _c, _d;
        const evalV2 = this._getResultFromLookup(this._values.dynamic_configs, name);
        if (!evalV2) {
            return null;
        }
        return {
            name: name,
            value: (_a = this._values.values[evalV2.v]) !== null && _a !== void 0 ? _a : {},
            rule_id: evalV2.r,
            secondary_exposures: (_b = evalV2.s) !== null && _b !== void 0 ? _b : [],
            id_type: (_c = evalV2.i) !== null && _c !== void 0 ? _c : '',
            is_user_in_experiment: evalV2.ue === true ? true : false,
            passed: evalV2.p === true,
            group_name: (_d = evalV2.gn) !== null && _d !== void 0 ? _d : undefined,
            is_experiment_active: evalV2.ea === true ? true : false,
            group: evalV2.r,
            is_device_based: evalV2.i === 'stableID',
        };
    }
    getLayer(name) {
        var _a, _b, _c, _d, _e, _f;
        const evalV2 = this._getResultFromLookup(this._values.layer_configs, name);
        if (!evalV2) {
            return null;
        }
        return {
            name: name,
            value: (_a = this._values.values[evalV2.v]) !== null && _a !== void 0 ? _a : {},
            rule_id: evalV2.r,
            secondary_exposures: (_b = evalV2.s) !== null && _b !== void 0 ? _b : [],
            is_user_in_experiment: evalV2.ue === true ? true : false,
            group_name: (_c = evalV2.gn) !== null && _c !== void 0 ? _c : undefined,
            is_experiment_active: evalV2.ea === true ? true : false,
            group: evalV2.r,
            is_device_based: evalV2.i === 'stableID',
            allocated_experiment_name: (_d = evalV2.ae) !== null && _d !== void 0 ? _d : '',
            explicit_parameters: (_e = evalV2.ep) !== null && _e !== void 0 ? _e : [],
            undelegated_secondary_exposures: (_f = evalV2.us) !== null && _f !== void 0 ? _f : [],
            parameter_rule_ids: evalV2.pr,
        };
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
exports.V2InitializeContainer = V2InitializeContainer;
