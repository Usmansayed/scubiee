export declare const _getWindowSafe: () => Window | null;
export declare const _getDocumentSafe: () => Document | null;
export declare const _isServerEnv: () => boolean;
export declare const _addWindowEventListenerSafe: (key: string, listener: () => void) => void;
export declare const _addDocumentEventListenerSafe: (key: string, listener: () => void) => void;
export declare const _getCurrentPageUrlSafe: () => string | undefined;
export declare const _getUnloadEvent: () => string;
export declare const _cloneObject: <T>(tag: string, obj: T) => T | null;
