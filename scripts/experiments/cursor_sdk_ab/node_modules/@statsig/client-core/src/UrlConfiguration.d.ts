import { Endpoint } from './NetworkConfig';
export type EndpointDnsKey = 'i' | 'e' | 'd';
export declare class UrlConfiguration {
    readonly endpoint: Endpoint;
    readonly endpointDnsKey: EndpointDnsKey;
    readonly defaultUrl: string;
    readonly customUrl: string | null;
    readonly fallbackUrls: string[] | null;
    constructor(endpoint: Endpoint, customUrl: string | undefined | null, customApi: string | undefined | null, fallbackUrls: string[] | undefined | null);
    getUrl(): string;
    getChecksum(): string;
}
