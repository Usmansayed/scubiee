"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
Object.defineProperty(exports, "__esModule", { value: true });
exports._fetchTxtRecords = void 0;
// See example: https://github.com/statsig-io/private-js-client-monorepo/pull/340
const FEATURE_ASSETS_DNS_QUERY = new Uint8Array([
    0x00, 0x00, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x0d,
    0x66, 0x65, 0x61, 0x74, 0x75, 0x72, 0x65, 0x61, 0x73, 0x73, 0x65, 0x74, 0x73,
    0x03, 0x6f, 0x72, 0x67, 0x00, 0x00, 0x10, 0x00, 0x01,
]);
const DNS_QUERY_ENDPOINT = 'https://cloudflare-dns.com/dns-query';
const DOMAIN_CHARS = [
    'i', // initialize
    'e', // events
    'd', // dcs
];
const MAX_START_LOOKUP = 200;
function _fetchTxtRecords(networkFunc) {
    return __awaiter(this, void 0, void 0, function* () {
        const response = yield networkFunc(DNS_QUERY_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/dns-message',
                Accept: 'application/dns-message',
            },
            body: FEATURE_ASSETS_DNS_QUERY,
        });
        if (!response.ok) {
            const err = new Error('Failed to fetch TXT records from DNS');
            err.name = 'DnsTxtFetchError';
            throw err;
        }
        const data = yield response.arrayBuffer();
        const bytes = new Uint8Array(data);
        return _parseDnsResponse(bytes);
    });
}
exports._fetchTxtRecords = _fetchTxtRecords;
function _parseDnsResponse(input) {
    // loop until we find the first valid domain char. One of [i=, e=, d=]
    const start = input.findIndex((byte, index) => index < MAX_START_LOOKUP &&
        String.fromCharCode(byte) === '=' &&
        DOMAIN_CHARS.includes(String.fromCharCode(input[index - 1])));
    if (start === -1) {
        const err = new Error('Failed to parse TXT records from DNS');
        err.name = 'DnsTxtParseError';
        throw err;
    }
    // decode the remaining bytes as a string
    let result = '';
    for (let i = start - 1; i < input.length; i++) {
        result += String.fromCharCode(input[i]);
    }
    return result.split(',');
}
