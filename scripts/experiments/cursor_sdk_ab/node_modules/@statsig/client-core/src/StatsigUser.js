"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._getFullUserHash = exports._normalizeUser = void 0;
const Hashing_1 = require("./Hashing");
const Log_1 = require("./Log");
const SafeJs_1 = require("./SafeJs");
function _normalizeUser(original, options, fallbackEnvironment) {
    const copy = (0, SafeJs_1._cloneObject)('StatsigUser', original);
    if (copy == null) {
        Log_1.Log.error('Failed to clone user');
        return { statsigEnvironment: undefined };
    }
    if (options != null && options.environment != null) {
        copy.statsigEnvironment = options.environment;
    }
    else if (fallbackEnvironment != null) {
        copy.statsigEnvironment = { tier: fallbackEnvironment };
    }
    return copy;
}
exports._normalizeUser = _normalizeUser;
function _getFullUserHash(user) {
    return user ? (0, Hashing_1._DJB2Object)(user) : null;
}
exports._getFullUserHash = _getFullUserHash;
