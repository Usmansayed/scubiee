"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._getSortedObject = exports._DJB2Object = exports._DJB2 = void 0;
const TypingUtils_1 = require("./TypingUtils");
const _DJB2 = (value) => {
    let hash = 0;
    for (let i = 0; i < value.length; i++) {
        const character = value.charCodeAt(i);
        hash = (hash << 5) - hash + character;
        hash = hash & hash; // Convert to 32bit integer
    }
    return String(hash >>> 0);
};
exports._DJB2 = _DJB2;
const _DJB2Object = (value, maxLevels) => {
    return (0, exports._DJB2)(JSON.stringify((0, exports._getSortedObject)(value, maxLevels)));
};
exports._DJB2Object = _DJB2Object;
const _getSortedObject = (object, maxDepth) => {
    if (object == null) {
        return null;
    }
    const keys = Object.keys(object).sort();
    const sortedObject = {};
    keys.forEach((key) => {
        const value = object[key];
        if (maxDepth === 0 || (0, TypingUtils_1._typeOf)(value) !== 'object') {
            sortedObject[key] = value;
            return;
        }
        sortedObject[key] = (0, exports._getSortedObject)(value, maxDepth != null ? maxDepth - 1 : maxDepth);
    });
    return sortedObject;
};
exports._getSortedObject = _getSortedObject;
