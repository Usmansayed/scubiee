export type StorageProvider = {
    isReady: () => boolean;
    isReadyResolver: () => Promise<void> | null;
    getProviderName: () => string;
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
    removeItem: (key: string) => void;
    getAllKeys: () => readonly string[];
};
type StorageProviderManagment = {
    _setProvider: (newProvider: StorageProvider) => void;
    _setDisabled: (isDisabled: boolean) => void;
};
export declare const Storage: StorageProvider & StorageProviderManagment;
export declare function _getObjectFromStorage<T>(key: string): T | null;
export declare function _setObjectInStorage(key: string, obj: unknown): void;
export {};
