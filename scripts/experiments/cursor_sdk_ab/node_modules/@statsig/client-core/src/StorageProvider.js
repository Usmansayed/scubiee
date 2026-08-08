"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._setObjectInStorage = exports._getObjectFromStorage = exports.Storage = void 0;
const Log_1 = require("./Log");
const SafeJs_1 = require("./SafeJs");
const inMemoryStore = {};
const _inMemoryProvider = {
    isReady: () => true,
    isReadyResolver: () => null,
    getProviderName: () => 'InMemory',
    getItem: (key) => inMemoryStore[key] ? inMemoryStore[key] : null,
    setItem: (key, value) => {
        inMemoryStore[key] = value;
    },
    removeItem: (key) => {
        delete inMemoryStore[key];
    },
    getAllKeys: () => Object.keys(inMemoryStore),
};
let _localStorageProvider = null;
try {
    const win = (0, SafeJs_1._getWindowSafe)();
    if (win &&
        win.localStorage &&
        typeof win.localStorage.getItem === 'function') {
        _localStorageProvider = {
            isReady: () => true,
            isReadyResolver: () => null,
            getProviderName: () => 'LocalStorage',
            getItem: (key) => win.localStorage.getItem(key),
            setItem: (key, value) => win.localStorage.setItem(key, value),
            removeItem: (key) => win.localStorage.removeItem(key),
            getAllKeys: () => Object.keys(win.localStorage),
        };
    }
}
catch (error) {
    Log_1.Log.warn('Failed to setup localStorageProvider.');
}
let _main = _localStorageProvider !== null && _localStorageProvider !== void 0 ? _localStorageProvider : _inMemoryProvider;
let _current = _main;
function _inMemoryBreaker(action) {
    try {
        return action();
    }
    catch (error) {
        if (error instanceof Error && error.name === 'SecurityError') {
            exports.Storage._setProvider(_inMemoryProvider);
            return null;
        }
        throw error;
    }
}
exports.Storage = {
    isReady: () => _current.isReady(),
    isReadyResolver: () => _current.isReadyResolver(),
    getProviderName: () => _current.getProviderName(),
    getItem: (key) => _inMemoryBreaker(() => _current.getItem(key)),
    setItem: (key, value) => _inMemoryBreaker(() => _current.setItem(key, value)),
    removeItem: (key) => _current.removeItem(key),
    getAllKeys: () => _current.getAllKeys(),
    // StorageProviderManagment
    _setProvider: (newProvider) => {
        _main = newProvider;
        _current = newProvider;
    },
    _setDisabled: (isDisabled) => {
        if (isDisabled) {
            _current = _inMemoryProvider;
        }
        else {
            _current = _main;
        }
    },
};
function _getObjectFromStorage(key) {
    const value = exports.Storage.getItem(key);
    try {
        return JSON.parse(value !== null && value !== void 0 ? value : 'null');
    }
    catch (e) {
        Log_1.Log.error(`Failed to parse value for key "${key}"`);
        return null;
    }
}
exports._getObjectFromStorage = _getObjectFromStorage;
function _setObjectInStorage(key, obj) {
    exports.Storage.setItem(key, JSON.stringify(obj));
}
exports._setObjectInStorage = _setObjectInStorage;
