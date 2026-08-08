"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.StatsigMetadataProvider = exports.SDK_VERSION = void 0;
exports.SDK_VERSION = '3.31.0';
let metadata = {
    sdkVersion: exports.SDK_VERSION,
    sdkType: 'js-mono', // js-mono is overwritten by Precomp and OnDevice clients
};
exports.StatsigMetadataProvider = {
    get: () => metadata,
    add: (additions) => {
        metadata = Object.assign(Object.assign({}, metadata), additions);
    },
};
