import { AnyEvaluationOptions } from './EvaluationOptions';
export declare const MemoPrefix: {
    readonly _gate: "g";
    readonly _dynamicConfig: "c";
    readonly _experiment: "e";
    readonly _configList: "cl";
    readonly _layer: "l";
    readonly _paramStore: "p";
};
export type MemoPrefix = (typeof MemoPrefix)[keyof typeof MemoPrefix];
export declare function createMemoKey(prefix: MemoPrefix, name: string, options?: AnyEvaluationOptions): string | undefined;
