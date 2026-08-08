import { NetworkArgs } from './NetworkConfig';
export declare function _fetchTxtRecords(networkFunc: (url: string, args: NetworkArgs) => Promise<Response>): Promise<string[]>;
