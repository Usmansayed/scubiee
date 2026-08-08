type Primitive = 'string' | 'number' | 'bigint' | 'boolean' | 'symbol' | 'undefined' | 'object' | 'function';
export type Flatten<T> = {
    [K in keyof T]: T[K];
} & {};
export declare function _typeOf(input: unknown): Primitive | 'array';
export declare function _isTypeMatch<T>(a: unknown, b: unknown): a is T;
export {};
