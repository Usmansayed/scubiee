"use strict";
/* eslint-disable no-console */
Object.defineProperty(exports, "__esModule", { value: true });
exports.Log = exports.LogLevel = void 0;
// intentionally spaced for formatting
const DEBUG = ' DEBUG ';
const _INFO = '  INFO ';
const _WARN = '  WARN ';
const ERROR = ' ERROR ';
function addTag(args) {
    args.unshift('[Statsig]');
    return args; // ['[Statsig]', ...args];
}
exports.LogLevel = {
    None: 0,
    Error: 1,
    Warn: 2,
    Info: 3,
    Debug: 4,
};
class Log {
    static info(...args) {
        if (Log.level >= exports.LogLevel.Info) {
            console.info(_INFO, ...addTag(args));
        }
    }
    static debug(...args) {
        if (Log.level >= exports.LogLevel.Debug) {
            console.debug(DEBUG, ...addTag(args));
        }
    }
    static warn(...args) {
        if (Log.level >= exports.LogLevel.Warn) {
            console.warn(_WARN, ...addTag(args));
        }
    }
    static error(...args) {
        if (Log.level >= exports.LogLevel.Error) {
            console.error(ERROR, ...addTag(args));
        }
    }
}
exports.Log = Log;
Log.level = exports.LogLevel.Warn;
