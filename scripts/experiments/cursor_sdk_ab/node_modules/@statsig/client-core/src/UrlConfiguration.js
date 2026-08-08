"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.UrlConfiguration = void 0;
const Hashing_1 = require("./Hashing");
const NetworkConfig_1 = require("./NetworkConfig");
const ENDPOINT_DNS_KEY_MAP = {
    [NetworkConfig_1.Endpoint._initialize]: 'i',
    [NetworkConfig_1.Endpoint._rgstr]: 'e',
    [NetworkConfig_1.Endpoint._download_config_specs]: 'd',
};
class UrlConfiguration {
    constructor(endpoint, customUrl, customApi, fallbackUrls) {
        this.customUrl = null;
        this.fallbackUrls = null;
        this.endpoint = endpoint;
        this.endpointDnsKey = ENDPOINT_DNS_KEY_MAP[endpoint];
        if (customUrl) {
            this.customUrl = customUrl;
        }
        if (!customUrl && customApi) {
            this.customUrl = customApi.endsWith('/')
                ? `${customApi}${endpoint}`
                : `${customApi}/${endpoint}`;
        }
        if (fallbackUrls) {
            this.fallbackUrls = fallbackUrls;
        }
        const defaultApi = NetworkConfig_1.NetworkDefault[endpoint];
        this.defaultUrl = `${defaultApi}/${endpoint}`;
    }
    getUrl() {
        var _a;
        return (_a = this.customUrl) !== null && _a !== void 0 ? _a : this.defaultUrl;
    }
    getChecksum() {
        var _a;
        const fallbacks = ((_a = this.fallbackUrls) !== null && _a !== void 0 ? _a : []).sort().join(',');
        return (0, Hashing_1._DJB2)(this.customUrl + fallbacks);
    }
}
exports.UrlConfiguration = UrlConfiguration;
