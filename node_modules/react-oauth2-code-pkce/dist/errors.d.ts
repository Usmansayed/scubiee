export declare class FetchError extends Error {
    status: number;
    statusText: string;
    constructor(status: number, statusText: string, message: string);
}
