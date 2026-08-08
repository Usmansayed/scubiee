"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._isTypeMatch = exports._typeOf = void 0;
function _typeOf(input) {
    return Array.isArray(input) ? 'array' : typeof input;
}
exports._typeOf = _typeOf;
function _isTypeMatch(a, b) {
    const typeOf = (x) => Array.isArray(x) ? 'array' : x === null ? 'null' : typeof x;
    return typeOf(a) === typeOf(b);
}
exports._isTypeMatch = _isTypeMatch;
