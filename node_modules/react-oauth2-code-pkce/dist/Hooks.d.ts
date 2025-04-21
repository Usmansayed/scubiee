declare function useBrowserStorage<T>(key: string, initialValue: T, type: 'session' | 'local'): [T, (v: T) => void];
export default useBrowserStorage;
