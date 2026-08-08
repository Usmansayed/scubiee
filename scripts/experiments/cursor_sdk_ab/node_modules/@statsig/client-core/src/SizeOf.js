"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._fastApproxSizeOf = void 0;
const CURLY_AND_SQUARE_BRACKET_SIZE = 2; // [] for array, {} for object
const APPROX_ADDITIONAL_SIZE = 1; // additional size for comma and stuff
const _fastApproxSizeOf = (obj, max) => {
    let size = 0;
    const keys = Object.keys(obj);
    for (let i = 0; i < keys.length; i++) {
        const key = keys[i];
        const value = obj[key];
        size += key.length;
        if (typeof value === 'object' && value !== null) {
            size += (0, exports._fastApproxSizeOf)(value, max) + CURLY_AND_SQUARE_BRACKET_SIZE;
        }
        else {
            size += String(value).length + APPROX_ADDITIONAL_SIZE;
        }
        if (size >= max) {
            // exit early if we've exceeded the max
            return size;
        }
    }
    return size;
};
exports._fastApproxSizeOf = _fastApproxSizeOf;
