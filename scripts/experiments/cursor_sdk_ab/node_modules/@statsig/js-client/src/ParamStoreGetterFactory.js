"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._makeParamStoreGetter = void 0;
const client_core_1 = require("@statsig/client-core");
const NO_EXPOSURE_OPT = {
    disableExposureLog: true,
};
function _shouldLogExposure(options) {
    return options == null || options.disableExposureLog === false;
}
function _shouldReturnFallback(value, fallback) {
    return fallback != null && !(0, client_core_1._isTypeMatch)(value, fallback);
}
function _getMappedStaticValue(param, _options) {
    return param.value;
}
function _getMappedGateValue(client, param, options) {
    const gate = client.getFeatureGate(param.gate_name, _shouldLogExposure(options) ? undefined : NO_EXPOSURE_OPT);
    if (gate.value) {
        return param.pass_value;
    }
    return param.fail_value;
}
function _getMappedDynamicConfigValue(client, param, fallback, options) {
    const config = client.getDynamicConfig(param.config_name, _shouldLogExposure(options) ? undefined : NO_EXPOSURE_OPT);
    const value = config.get(param.param_name);
    if (_shouldReturnFallback(value, fallback)) {
        return fallback;
    }
    return value;
}
function _getMappedExperimentValue(client, param, fallback, options) {
    const experiment = client.getExperiment(param.experiment_name, _shouldLogExposure(options) ? undefined : NO_EXPOSURE_OPT);
    const value = experiment.get(param.param_name);
    if (_shouldReturnFallback(value, fallback)) {
        return fallback;
    }
    return value;
}
function _getMappedLayerValue(client, param, fallback, options) {
    const layer = client.getLayer(param.layer_name, _shouldLogExposure(options) ? undefined : NO_EXPOSURE_OPT);
    const value = layer.get(param.param_name);
    if (_shouldReturnFallback(value, fallback)) {
        return fallback;
    }
    return value;
}
function _makeParamStoreGetter(client, config, options) {
    return (paramName, fallback) => {
        if (config == null) {
            return fallback;
        }
        const param = config[paramName];
        if (param == null ||
            (fallback != null && (0, client_core_1._typeOf)(fallback) !== param.param_type)) {
            return fallback;
        }
        switch (param.ref_type) {
            case 'static':
                return _getMappedStaticValue(param, options);
            case 'gate':
                return _getMappedGateValue(client, param, options);
            case 'dynamic_config':
                return _getMappedDynamicConfigValue(client, param, fallback, options);
            case 'experiment':
                return _getMappedExperimentValue(client, param, fallback, options);
            case 'layer':
                return _getMappedLayerValue(client, param, fallback, options);
            default:
                return fallback;
        }
    };
}
exports._makeParamStoreGetter = _makeParamStoreGetter;
