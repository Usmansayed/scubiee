"use strict";
/* eslint-disable @typescript-eslint/no-unsafe-assignment */
var _a, _b, _c;
Object.defineProperty(exports, "__esModule", { value: true });
exports._getInstance = exports._getStatsigGlobalFlag = exports._getStatsigGlobal = void 0;
const Log_1 = require("./Log");
const _getStatsigGlobal = () => {
    // Avoid ReferenceError, which is happening with Cloudflare pages
    try {
        return typeof __STATSIG__ !== 'undefined' ? __STATSIG__ : statsigGlobal;
    }
    catch (e) {
        return statsigGlobal;
    }
};
exports._getStatsigGlobal = _getStatsigGlobal;
const _getStatsigGlobalFlag = (flag) => {
    return (0, exports._getStatsigGlobal)()[flag];
};
exports._getStatsigGlobalFlag = _getStatsigGlobalFlag;
const _getInstance = (sdkKey) => {
    const gbl = (0, exports._getStatsigGlobal)();
    if (!sdkKey) {
        if (gbl.instances && Object.keys(gbl.instances).length > 1) {
            Log_1.Log.warn('Call made to Statsig global instance without an SDK key but there is more than one client instance. If you are using mulitple clients, please specify the SDK key.');
        }
        return gbl.firstInstance;
    }
    return gbl.instances && gbl.instances[sdkKey];
};
exports._getInstance = _getInstance;
const GLOBAL_KEY = '__STATSIG__';
const _window = typeof window !== 'undefined' ? window : {};
const _global = typeof global !== 'undefined' ? global : {};
const _globalThis = typeof globalThis !== 'undefined' ? globalThis : {};
const statsigGlobal = (_c = (_b = (_a = _window[GLOBAL_KEY]) !== null && _a !== void 0 ? _a : _global[GLOBAL_KEY]) !== null && _b !== void 0 ? _b : _globalThis[GLOBAL_KEY]) !== null && _c !== void 0 ? _c : {
    instance: exports._getInstance,
};
_window[GLOBAL_KEY] = statsigGlobal;
_global[GLOBAL_KEY] = statsigGlobal;
_globalThis[GLOBAL_KEY] = statsigGlobal;
