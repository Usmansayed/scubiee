"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._cloneObject = exports._getUnloadEvent = exports._getCurrentPageUrlSafe = exports._addDocumentEventListenerSafe = exports._addWindowEventListenerSafe = exports._isServerEnv = exports._getDocumentSafe = exports._getWindowSafe = void 0;
const Log_1 = require("./Log");
const _getWindowSafe = () => {
    return typeof window !== 'undefined' ? window : null;
};
exports._getWindowSafe = _getWindowSafe;
const _getDocumentSafe = () => {
    var _a;
    const win = (0, exports._getWindowSafe)();
    return (_a = win === null || win === void 0 ? void 0 : win.document) !== null && _a !== void 0 ? _a : null;
};
exports._getDocumentSafe = _getDocumentSafe;
const _isServerEnv = () => {
    if ((0, exports._getDocumentSafe)() !== null) {
        return false;
    }
    const isNode = typeof process !== 'undefined' &&
        process.versions != null &&
        process.versions.node != null;
    const isVercel = typeof EdgeRuntime === 'string';
    return isVercel || isNode;
};
exports._isServerEnv = _isServerEnv;
const _addWindowEventListenerSafe = (key, listener) => {
    const win = (0, exports._getWindowSafe)();
    if (typeof (win === null || win === void 0 ? void 0 : win.addEventListener) === 'function') {
        win.addEventListener(key, listener);
    }
};
exports._addWindowEventListenerSafe = _addWindowEventListenerSafe;
const _addDocumentEventListenerSafe = (key, listener) => {
    const doc = (0, exports._getDocumentSafe)();
    if (typeof (doc === null || doc === void 0 ? void 0 : doc.addEventListener) === 'function') {
        doc.addEventListener(key, listener);
    }
};
exports._addDocumentEventListenerSafe = _addDocumentEventListenerSafe;
const _getCurrentPageUrlSafe = () => {
    var _a;
    try {
        return (_a = (0, exports._getWindowSafe)()) === null || _a === void 0 ? void 0 : _a.location.href.split(/[?#]/)[0];
    }
    catch (_b) {
        return;
    }
};
exports._getCurrentPageUrlSafe = _getCurrentPageUrlSafe;
const _getUnloadEvent = () => {
    const win = (0, exports._getWindowSafe)();
    if (!win) {
        return 'beforeunload';
    }
    const eventType = 'onpagehide' in win ? 'pagehide' : 'beforeunload';
    return eventType;
};
exports._getUnloadEvent = _getUnloadEvent;
const _cloneObject = (tag, obj) => {
    try {
        return JSON.parse(JSON.stringify(obj));
    }
    catch (error) {
        Log_1.Log.error(`Failed to clone object ${tag}`);
        return null;
    }
};
exports._cloneObject = _cloneObject;
