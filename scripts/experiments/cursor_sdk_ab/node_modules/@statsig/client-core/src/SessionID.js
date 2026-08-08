"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.StatsigSession = exports.SessionID = void 0;
const __StatsigGlobal_1 = require("./$_StatsigGlobal");
const CacheKey_1 = require("./CacheKey");
const Log_1 = require("./Log");
const StorageProvider_1 = require("./StorageProvider");
const UUID_1 = require("./UUID");
const MAX_SESSION_IDLE_TIME = 30 * 60 * 1000; // 30 minutes
const MAX_SESSION_AGE = 4 * 60 * 60 * 1000; // 4 hours
const PROMISE_MAP = {};
exports.SessionID = {
    get: (sdkKey) => {
        return exports.StatsigSession.get(sdkKey).data.sessionID;
    },
};
exports.StatsigSession = {
    get: (sdkKey) => {
        if (PROMISE_MAP[sdkKey] == null) {
            PROMISE_MAP[sdkKey] = _loadSession(sdkKey);
        }
        const session = PROMISE_MAP[sdkKey];
        return _bumpSession(session);
    },
    overrideInitialSessionID: (override, sdkKey) => {
        PROMISE_MAP[sdkKey] = _overrideSessionId(override, sdkKey);
    },
};
function _loadSession(sdkKey) {
    let data = _loadFromStorage(sdkKey);
    const now = Date.now();
    if (!data) {
        data = {
            sessionID: (0, UUID_1.getUUID)(),
            startTime: now,
            lastUpdate: now,
        };
    }
    return {
        data,
        sdkKey,
    };
}
function _overrideSessionId(override, sdkKey) {
    const now = Date.now();
    return {
        data: {
            sessionID: override,
            startTime: now,
            lastUpdate: now,
        },
        sdkKey,
    };
}
function _bumpSession(session) {
    const now = Date.now();
    const data = session.data;
    const sdkKey = session.sdkKey;
    if (_isIdle(data) || _hasRunTooLong(data)) {
        data.sessionID = (0, UUID_1.getUUID)();
        data.startTime = now;
        const client = __STATSIG__ === null || __STATSIG__ === void 0 ? void 0 : __STATSIG__.instance(sdkKey);
        if (client) {
            client.$emt({ name: 'session_expired' });
        }
    }
    data.lastUpdate = now;
    _persistToStorage(data, session.sdkKey);
    clearTimeout(session.idleTimeoutID);
    clearTimeout(session.ageTimeoutID);
    const lifetime = now - data.startTime;
    session.idleTimeoutID = _createSessionTimeout(sdkKey, MAX_SESSION_IDLE_TIME);
    session.ageTimeoutID = _createSessionTimeout(sdkKey, MAX_SESSION_AGE - lifetime);
    return session;
}
function _createSessionTimeout(sdkKey, duration) {
    return setTimeout(() => {
        var _a;
        const client = (_a = (0, __StatsigGlobal_1._getStatsigGlobal)()) === null || _a === void 0 ? void 0 : _a.instance(sdkKey);
        if (client) {
            client.$emt({ name: 'session_expired' });
        }
    }, duration);
}
function _isIdle({ lastUpdate }) {
    return Date.now() - lastUpdate > MAX_SESSION_IDLE_TIME;
}
function _hasRunTooLong({ startTime }) {
    return Date.now() - startTime > MAX_SESSION_AGE;
}
function _getSessionIDStorageKey(sdkKey) {
    return `statsig.session_id.${(0, CacheKey_1._getStorageKey)(sdkKey)}`;
}
function _persistToStorage(session, sdkKey) {
    const storageKey = _getSessionIDStorageKey(sdkKey);
    try {
        (0, StorageProvider_1._setObjectInStorage)(storageKey, session);
    }
    catch (e) {
        Log_1.Log.warn('Failed to save SessionID');
    }
}
function _loadFromStorage(sdkKey) {
    const storageKey = _getSessionIDStorageKey(sdkKey);
    return (0, StorageProvider_1._getObjectFromStorage)(storageKey);
}
