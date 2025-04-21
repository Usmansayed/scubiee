"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const react_1 = require("react");
function useBrowserStorage(key, initialValue, type) {
    const storage = type === 'session' ? sessionStorage : localStorage;
    const [storedValue, setStoredValue] = (0, react_1.useState)(() => {
        const item = storage.getItem(key);
        try {
            return item ? JSON.parse(item) : initialValue;
        }
        catch (error) {
            console.warn(`Failed to parse stored value for '${key}'.\nContinuing with default value.`);
            return initialValue;
        }
    });
    const setValue = (value) => {
        if (value === undefined) {
            // Delete item if set to undefined. This avoids warning on loading invalid json
            setStoredValue(value);
            storage.removeItem(key);
            return;
        }
        try {
            const valueToStore = value instanceof Function ? value(storedValue) : value;
            setStoredValue(valueToStore);
            storage.setItem(key, JSON.stringify(valueToStore));
        }
        catch (error) {
            console.error(`Failed to store value '${value}' for key '${key}'`);
        }
    };
    (0, react_1.useEffect)(() => {
        const storageEventHandler = (event) => {
            var _a;
            if (event.storageArea === storage && event.key === key) {
                if (event.newValue === null) {
                    setStoredValue(undefined);
                }
                else {
                    try {
                        setStoredValue(JSON.parse((_a = event.newValue) !== null && _a !== void 0 ? _a : ''));
                    }
                    catch (error) {
                        console.warn(`Failed to handle storageEvent's newValue='${event.newValue}' for key '${key}'`);
                    }
                }
            }
        };
        window.addEventListener('storage', storageEventHandler, false);
        return () => window.removeEventListener('storage', storageEventHandler, false);
    });
    return [storedValue, setValue];
}
exports.default = useBrowserStorage;
