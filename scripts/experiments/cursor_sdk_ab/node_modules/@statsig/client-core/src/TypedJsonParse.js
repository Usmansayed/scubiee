"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports._typedJsonParse = void 0;
const Log_1 = require("./Log");
/**
 *
 * @param {string} data The values to parse into T
 * @param {string} guard A field that must exists on the parsed object for the parse to be valid
 * @param {string} error An error to print via Log.error() when parsing fails
 * @returns {T | null} The parse object T or null if it failed
 */
function _typedJsonParse(data, guard, typeName) {
    try {
        const result = JSON.parse(data);
        if (result &&
            typeof result === 'object' &&
            guard in result) {
            return result;
        }
    }
    catch (_a) {
        // noop
    }
    Log_1.Log.error(`Failed to parse ${typeName}`);
    return null;
}
exports._typedJsonParse = _typedJsonParse;
