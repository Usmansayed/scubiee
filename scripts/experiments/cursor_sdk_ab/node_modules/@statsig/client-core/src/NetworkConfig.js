"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.NetworkParam = exports.NetworkDefault = exports.Endpoint = void 0;
exports.Endpoint = {
    _initialize: 'initialize',
    _rgstr: 'rgstr',
    _download_config_specs: 'download_config_specs',
};
exports.NetworkDefault = {
    [exports.Endpoint._rgstr]: 'https://prodregistryv2.org/v1',
    [exports.Endpoint._initialize]: 'https://featureassets.org/v1',
    [exports.Endpoint._download_config_specs]: 'https://api.statsigcdn.com/v1',
};
exports.NetworkParam = {
    EventCount: 'ec',
    SdkKey: 'k',
    SdkType: 'st',
    SdkVersion: 'sv',
    Time: 't',
    SessionID: 'sid',
    StatsigEncoded: 'se',
    IsGzipped: 'gz',
};
