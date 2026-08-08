declare const FOREGROUND = "foreground";
declare const BACKGROUND = "background";
export type Visibility = typeof FOREGROUND | typeof BACKGROUND;
type VisibilityChangedCallback = (visibility: Visibility) => void;
export declare const _isCurrentlyVisible: () => boolean;
export declare const _isUnloading: () => boolean;
export declare const _subscribeToVisiblityChanged: (listener: VisibilityChangedCallback) => void;
export declare const _notifyVisibilityChanged: (visibility: Visibility) => void;
export {};
