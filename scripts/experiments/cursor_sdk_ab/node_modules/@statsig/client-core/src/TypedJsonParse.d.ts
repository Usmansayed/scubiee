/**
 *
 * @param {string} data The values to parse into T
 * @param {string} guard A field that must exists on the parsed object for the parse to be valid
 * @param {string} error An error to print via Log.error() when parsing fails
 * @returns {T | null} The parse object T or null if it failed
 */
export declare function _typedJsonParse<T>(data: string, guard: string, typeName: string): T | null;
