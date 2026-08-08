"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._getStorageKey = exports._getUserStorageKey = void 0;
const Hashing_1 = require("./Hashing");
function _getUserStorageKey(sdkKey, user, customKeyGenerator) {
    var _a;
    if (customKeyGenerator) {
        return customKeyGenerator(sdkKey, user);
    }
    const cids = user && user.customIDs ? user.customIDs : {};
    const parts = [
        `uid:${(_a = user === null || user === void 0 ? void 0 : user.userID) !== null && _a !== void 0 ? _a : ''}`,
        `cids:${Object.keys(cids)
            .sort((leftKey, rightKey) => leftKey.localeCompare(rightKey))
            .map((key) => `${key}-${cids[key]}`)
            .join(',')}`,
        `k:${sdkKey}`,
    ];
    return (0, Hashing_1._DJB2)(parts.join('|'));
}
exports._getUserStorageKey = _getUserStorageKey;
function _getStorageKey(sdkKey, user, customKeyGenerator) {
    if (user) {
        return _getUserStorageKey(sdkKey, user, customKeyGenerator);
    }
    return (0, Hashing_1._DJB2)(`k:${sdkKey}`);
}
exports._getStorageKey = _getStorageKey;
