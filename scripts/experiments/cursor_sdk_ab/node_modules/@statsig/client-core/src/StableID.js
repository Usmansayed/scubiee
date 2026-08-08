"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getCookieName = exports.StableID = void 0;
const CacheKey_1 = require("./CacheKey");
const Log_1 = require("./Log");
const SafeJs_1 = require("./SafeJs");
const StorageProvider_1 = require("./StorageProvider");
const UUID_1 = require("./UUID");
const PROMISE_MAP = {};
const COOKIE_ENABLED_MAP = {};
const DISABLED_MAP = {};
exports.StableID = {
    cookiesEnabled: false,
    randomID: Math.random().toString(36),
    get: (sdkKey) => {
        if (DISABLED_MAP[sdkKey]) {
            return null;
        }
        if (PROMISE_MAP[sdkKey] != null) {
            return PROMISE_MAP[sdkKey];
        }
        let stableID = null;
        stableID = _loadFromCookie(sdkKey);
        if (stableID != null) {
            PROMISE_MAP[sdkKey] = stableID;
            _persistToStorage(stableID, sdkKey);
            return stableID;
        }
        stableID = _loadFromStorage(sdkKey);
        if (stableID == null) {
            stableID = (0, UUID_1.getUUID)();
        }
        _persistToStorage(stableID, sdkKey);
        _persistToCookie(stableID, sdkKey);
        PROMISE_MAP[sdkKey] = stableID;
        return stableID;
    },
    setOverride: (override, sdkKey) => {
        PROMISE_MAP[sdkKey] = override;
        _persistToStorage(override, sdkKey);
        _persistToCookie(override, sdkKey);
    },
    _setCookiesEnabled: (sdkKey, cookiesEnabled) => {
        COOKIE_ENABLED_MAP[sdkKey] = cookiesEnabled;
    },
    _setDisabled: (sdkKey, disabled) => {
        DISABLED_MAP[sdkKey] = disabled;
    },
};
function _getStableIDStorageKey(sdkKey) {
    return `statsig.stable_id.${(0, CacheKey_1._getStorageKey)(sdkKey)}`;
}
function _persistToStorage(stableID, sdkKey) {
    const storageKey = _getStableIDStorageKey(sdkKey);
    try {
        (0, StorageProvider_1._setObjectInStorage)(storageKey, stableID);
    }
    catch (e) {
        Log_1.Log.warn('Failed to save StableID to storage');
    }
}
function _loadFromStorage(sdkKey) {
    const storageKey = _getStableIDStorageKey(sdkKey);
    return (0, StorageProvider_1._getObjectFromStorage)(storageKey);
}
function _loadFromCookie(sdkKey) {
    if (!COOKIE_ENABLED_MAP[sdkKey] || (0, SafeJs_1._getDocumentSafe)() == null) {
        return null;
    }
    const cookies = document.cookie.split(';');
    for (const cookie of cookies) {
        const [key, value] = cookie.trim().split('=');
        if (key === getCookieName(sdkKey)) {
            return decodeURIComponent(value);
        }
    }
    return null;
}
function _persistToCookie(stableID, sdkKey) {
    if (!COOKIE_ENABLED_MAP[sdkKey] || (0, SafeJs_1._getDocumentSafe)() == null) {
        return;
    }
    const expiryDate = new Date();
    expiryDate.setFullYear(expiryDate.getFullYear() + 1);
    document.cookie = `${getCookieName(sdkKey)}=${encodeURIComponent(stableID)}; expires=${expiryDate.toUTCString()}; path=/`;
}
function getCookieName(sdkKey) {
    return `statsig.stable_id.${(0, CacheKey_1._getStorageKey)(sdkKey)}`;
}
exports.getCookieName = getCookieName;
