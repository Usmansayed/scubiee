type SessionTimeoutID = ReturnType<typeof setTimeout>;
type SessionData = {
    sessionID: string;
    startTime: number;
    lastUpdate: number;
};
export type StatsigSession = {
    data: SessionData;
    sdkKey: string;
    ageTimeoutID?: SessionTimeoutID;
    idleTimeoutID?: SessionTimeoutID;
};
export declare const SessionID: {
    get: (sdkKey: string) => string;
};
export declare const StatsigSession: {
    get: (sdkKey: string) => StatsigSession;
    overrideInitialSessionID: (override: string, sdkKey: string) => void;
};
export {};
