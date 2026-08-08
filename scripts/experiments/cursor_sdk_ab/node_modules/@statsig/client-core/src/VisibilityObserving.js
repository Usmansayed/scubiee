"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._notifyVisibilityChanged = exports._subscribeToVisiblityChanged = exports._isUnloading = exports._isCurrentlyVisible = void 0;
const SafeJs_1 = require("./SafeJs");
const FOREGROUND = 'foreground';
const BACKGROUND = 'background';
const LISTENERS = [];
let current = FOREGROUND;
let isUnloading = false;
const _isCurrentlyVisible = () => {
    return current === FOREGROUND;
};
exports._isCurrentlyVisible = _isCurrentlyVisible;
const _isUnloading = () => isUnloading;
exports._isUnloading = _isUnloading;
const _subscribeToVisiblityChanged = (listener) => {
    LISTENERS.unshift(listener);
};
exports._subscribeToVisiblityChanged = _subscribeToVisiblityChanged;
const _notifyVisibilityChanged = (visibility) => {
    if (visibility === current) {
        return;
    }
    current = visibility;
    LISTENERS.forEach((l) => l(visibility));
};
exports._notifyVisibilityChanged = _notifyVisibilityChanged;
(0, SafeJs_1._addWindowEventListenerSafe)('focus', () => {
    isUnloading = false;
    (0, exports._notifyVisibilityChanged)(FOREGROUND);
});
(0, SafeJs_1._addWindowEventListenerSafe)('blur', () => (0, exports._notifyVisibilityChanged)(BACKGROUND));
(0, SafeJs_1._addDocumentEventListenerSafe)('visibilitychange', () => {
    (0, exports._notifyVisibilityChanged)(document.visibilityState === 'visible' ? FOREGROUND : BACKGROUND);
});
(0, SafeJs_1._addWindowEventListenerSafe)((0, SafeJs_1._getUnloadEvent)(), () => {
    isUnloading = true;
    (0, exports._notifyVisibilityChanged)(BACKGROUND);
});
