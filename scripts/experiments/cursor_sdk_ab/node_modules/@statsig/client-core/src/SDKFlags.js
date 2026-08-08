"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SDKFlags = void 0;
const FLAGMAP = {};
exports.SDKFlags = {
    setFlags: (sdkKey, flags) => {
        FLAGMAP[sdkKey] = flags;
    },
    get: (sdkKey, flagKey) => {
        var _a, _b;
        return (_b = (_a = FLAGMAP[sdkKey]) === null || _a === void 0 ? void 0 : _a[flagKey]) !== null && _b !== void 0 ? _b : false;
    },
};
