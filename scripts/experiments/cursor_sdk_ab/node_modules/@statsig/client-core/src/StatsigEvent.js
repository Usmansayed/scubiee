"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._createLayerParameterExposure = exports._createConfigExposure = exports._mapExposures = exports._createGateExposure = exports._isExposureEvent = void 0;
const CONFIG_EXPOSURE_NAME = 'statsig::config_exposure';
const GATE_EXPOSURE_NAME = 'statsig::gate_exposure';
const LAYER_EXPOSURE_NAME = 'statsig::layer_exposure';
const _createExposure = (eventName, user, details, metadata, secondaryExposures) => {
    if (details.bootstrapMetadata) {
        metadata['bootstrapMetadata'] = details.bootstrapMetadata;
    }
    return {
        eventName,
        user,
        value: null,
        metadata: _addEvaluationDetailsToMetadata(details, metadata),
        secondaryExposures,
        time: Date.now(),
    };
};
const _isExposureEvent = ({ eventName, }) => {
    return (eventName === GATE_EXPOSURE_NAME ||
        eventName === CONFIG_EXPOSURE_NAME ||
        eventName === LAYER_EXPOSURE_NAME);
};
exports._isExposureEvent = _isExposureEvent;
const _createGateExposure = (user, gate, exposureMapping) => {
    var _a, _b, _c;
    const metadata = {
        gate: gate.name,
        gateValue: String(gate.value),
        ruleID: gate.ruleID,
    };
    if (((_a = gate.__evaluation) === null || _a === void 0 ? void 0 : _a.version) != null) {
        metadata['configVersion'] = gate.__evaluation.version;
    }
    return _createExposure(GATE_EXPOSURE_NAME, user, gate.details, metadata, _mapExposures((_c = (_b = gate.__evaluation) === null || _b === void 0 ? void 0 : _b.secondary_exposures) !== null && _c !== void 0 ? _c : [], exposureMapping));
};
exports._createGateExposure = _createGateExposure;
function _mapExposures(exposures, exposureMapping) {
    return exposures
        .map((exposure) => {
        if (typeof exposure === 'string') {
            return (exposureMapping !== null && exposureMapping !== void 0 ? exposureMapping : {})[exposure];
        }
        return exposure;
    })
        .filter((exposure) => exposure != null);
}
exports._mapExposures = _mapExposures;
const _createConfigExposure = (user, config, exposureMapping) => {
    var _a, _b, _c, _d;
    const metadata = {
        config: config.name,
        ruleID: config.ruleID,
    };
    if (((_a = config.__evaluation) === null || _a === void 0 ? void 0 : _a.version) != null) {
        metadata['configVersion'] = config.__evaluation.version;
    }
    if (((_b = config.__evaluation) === null || _b === void 0 ? void 0 : _b.passed) != null) {
        metadata['rulePassed'] = String(config.__evaluation.passed);
    }
    return _createExposure(CONFIG_EXPOSURE_NAME, user, config.details, metadata, _mapExposures((_d = (_c = config.__evaluation) === null || _c === void 0 ? void 0 : _c.secondary_exposures) !== null && _d !== void 0 ? _d : [], exposureMapping));
};
exports._createConfigExposure = _createConfigExposure;
const _createLayerParameterExposure = (user, layer, parameterName, exposureMapping) => {
    var _a, _b, _c, _d, _e, _f, _g;
    const evaluation = layer.__evaluation;
    const isExplicit = ((_a = evaluation === null || evaluation === void 0 ? void 0 : evaluation.explicit_parameters) === null || _a === void 0 ? void 0 : _a.includes(parameterName)) === true;
    let allocatedExperiment = '';
    let secondaryExposures = (_b = evaluation === null || evaluation === void 0 ? void 0 : evaluation.undelegated_secondary_exposures) !== null && _b !== void 0 ? _b : [];
    if (isExplicit) {
        allocatedExperiment = (_c = evaluation.allocated_experiment_name) !== null && _c !== void 0 ? _c : '';
        secondaryExposures = (_d = evaluation.secondary_exposures) !== null && _d !== void 0 ? _d : [];
    }
    const parameterRuleIDs = (_e = layer.__evaluation) === null || _e === void 0 ? void 0 : _e.parameter_rule_ids;
    const metadata = {
        config: layer.name,
        parameterName,
        ruleID: (_f = parameterRuleIDs === null || parameterRuleIDs === void 0 ? void 0 : parameterRuleIDs[parameterName]) !== null && _f !== void 0 ? _f : layer.ruleID,
        allocatedExperiment,
        isExplicitParameter: String(isExplicit),
    };
    if (((_g = layer.__evaluation) === null || _g === void 0 ? void 0 : _g.version) != null) {
        metadata['configVersion'] = layer.__evaluation.version;
    }
    return _createExposure(LAYER_EXPOSURE_NAME, user, layer.details, metadata, _mapExposures(secondaryExposures, exposureMapping));
};
exports._createLayerParameterExposure = _createLayerParameterExposure;
const _addEvaluationDetailsToMetadata = (details, metadata) => {
    metadata['reason'] = details.reason;
    if (details.lcut) {
        metadata['lcut'] = String(details.lcut);
    }
    if (details.receivedAt) {
        metadata['receivedAt'] = String(details.receivedAt);
    }
    return metadata;
};
