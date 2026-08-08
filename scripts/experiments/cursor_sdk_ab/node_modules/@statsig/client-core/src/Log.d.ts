export declare const LogLevel: {
    readonly None: 0;
    readonly Error: 1;
    readonly Warn: 2;
    readonly Info: 3;
    readonly Debug: 4;
};
export type LogLevel = (typeof LogLevel)[keyof typeof LogLevel];
export declare abstract class Log {
    static level: LogLevel;
    static info(...args: unknown[]): void;
    static debug(...args: unknown[]): void;
    static warn(...args: unknown[]): void;
    static error(...args: unknown[]): void;
}
