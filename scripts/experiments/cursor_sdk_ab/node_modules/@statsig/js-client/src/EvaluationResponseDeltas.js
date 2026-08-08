"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._resolveDeltasResponse = void 0;
const client_core_1 = require("@statsig/client-core");
const MAX_DELTAS_SORT_DEPTH = 2;
function _resolveDeltasResponse(cache, deltasString) {
    const deltas = (0, client_core_1._typedJsonParse)(deltasString, 'checksum', 'DeltasEvaluationResponse');
    if (!deltas) {
        return {
            hadBadDeltaChecksum: true,
        };
    }
    const merged = _mergeDeltasIntoCache(cache, deltas);
    const resolved = _handleDeletedEntries(merged);
    const actualChecksum = (0, client_core_1._DJB2Object)({
        feature_gates: resolved.feature_gates,
        dynamic_configs: resolved.dynamic_configs,
        layer_configs: resolved.layer_configs,
    }, MAX_DELTAS_SORT_DEPTH);
    const isMatch = actualChecksum === deltas.checksumV2;
    if (!isMatch) {
        return {
            hadBadDeltaChecksum: true,
            badChecksum: actualChecksum,
            badMergedConfigs: resolved,
            badFullResponse: deltas.deltas_full_response,
        };
    }
    return JSON.stringify(resolved);
}
exports._resolveDeltasResponse = _resolveDeltasResponse;
function _mergeDeltasIntoCache(cache, deltas) {
    return Object.assign(Object.assign(Object.assign({}, cache), deltas), { feature_gates: Object.assign(Object.assign({}, cache.feature_gates), deltas.feature_gates), layer_configs: Object.assign(Object.assign({}, cache.layer_configs), deltas.layer_configs), dynamic_configs: Object.assign(Object.assign({}, cache.dynamic_configs), deltas.dynamic_configs) });
}
function _handleDeletedEntries(deltas) {
    const result = deltas;
    _deleteEntriesInRecord(deltas.deleted_gates, result.feature_gates);
    delete result.deleted_gates;
    _deleteEntriesInRecord(deltas.deleted_configs, result.dynamic_configs);
    delete result.deleted_configs;
    _deleteEntriesInRecord(deltas.deleted_layers, result.layer_configs);
    delete result.deleted_layers;
    return result;
}
function _deleteEntriesInRecord(keys, values) {
    keys === null || keys === void 0 ? void 0 : keys.forEach((key) => {
        delete values[key];
    });
}
