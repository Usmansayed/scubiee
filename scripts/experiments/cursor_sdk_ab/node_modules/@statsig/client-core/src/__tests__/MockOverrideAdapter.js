"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.MockOverrideAdapter = void 0;
class MockOverrideAdapter {
    getGateOverride(_current, _user, _options) {
        return null;
    }
    getDynamicConfigOverride(_current, _user, _options) {
        return null;
    }
    getExperimentOverride(_current, _user, _options) {
        return null;
    }
    getLayerOverride(_current, _user, _options) {
        return null;
    }
    getParamStoreOverride(_current, _options) {
        return null;
    }
}
exports.MockOverrideAdapter = MockOverrideAdapter;
