"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || function (mod) {
    if (mod && mod.__esModule) return mod;
    var result = {};
    if (mod != null) for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
    __setModuleDefault(result, mod);
    return result;
};
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.AuthProvider = exports.AuthContext = void 0;
const react_1 = __importStar(require("react"));
const Hooks_1 = __importDefault(require("./Hooks"));
const authConfig_1 = require("./authConfig");
const authentication_1 = require("./authentication");
const decodeJWT_1 = require("./decodeJWT");
const errors_1 = require("./errors");
const timeUtils_1 = require("./timeUtils");
exports.AuthContext = (0, react_1.createContext)({
    token: '',
    login: () => null,
    logIn: () => null,
    logOut: () => null,
    error: null,
    loginInProgress: false,
});
const AuthProvider = ({ authConfig, children }) => {
    const config = (0, react_1.useMemo)(() => (0, authConfig_1.createInternalConfig)(authConfig), [authConfig]);
    const [refreshToken, setRefreshToken] = (0, Hooks_1.default)(`${config.storageKeyPrefix}refreshToken`, undefined, config.storage);
    const [refreshTokenExpire, setRefreshTokenExpire] = (0, Hooks_1.default)(`${config.storageKeyPrefix}refreshTokenExpire`, undefined, config.storage);
    const [token, setToken] = (0, Hooks_1.default)(`${config.storageKeyPrefix}token`, '', config.storage);
    const [tokenExpire, setTokenExpire] = (0, Hooks_1.default)(`${config.storageKeyPrefix}tokenExpire`, (0, timeUtils_1.epochAtSecondsFromNow)(timeUtils_1.FALLBACK_EXPIRE_TIME), config.storage);
    const [idToken, setIdToken] = (0, Hooks_1.default)(`${config.storageKeyPrefix}idToken`, undefined, config.storage);
    const [loginInProgress, setLoginInProgress] = (0, Hooks_1.default)(`${config.storageKeyPrefix}loginInProgress`, false, config.storage);
    const [refreshInProgress, setRefreshInProgress] = (0, Hooks_1.default)(`${config.storageKeyPrefix}refreshInProgress`, false, config.storage);
    const [loginMethod, setLoginMethod] = (0, Hooks_1.default)(`${config.storageKeyPrefix}loginMethod`, 'redirect', config.storage);
    const [tokenData, setTokenData] = (0, react_1.useState)();
    const [idTokenData, setIdTokenData] = (0, react_1.useState)();
    const [error, setError] = (0, react_1.useState)(null);
    function clearStorage() {
        setRefreshToken(undefined);
        setToken('');
        setTokenExpire((0, timeUtils_1.epochAtSecondsFromNow)(timeUtils_1.FALLBACK_EXPIRE_TIME));
        setRefreshTokenExpire(undefined);
        setIdToken(undefined);
        setTokenData(undefined);
        setIdTokenData(undefined);
        setLoginInProgress(false);
    }
    function logOut(state, logoutHint, additionalParameters) {
        clearStorage();
        setError(null);
        if ((config === null || config === void 0 ? void 0 : config.logoutEndpoint) && token)
            (0, authentication_1.redirectToLogout)(config, token, refreshToken, idToken, state, logoutHint, additionalParameters);
    }
    function logIn(state, additionalParameters, method = 'redirect') {
        clearStorage();
        setLoginInProgress(true);
        setLoginMethod(method);
        // TODO: Raise error on wrong state type in v2
        let typeSafePassedState = state;
        if (state && typeof state !== 'string') {
            const jsonState = JSON.stringify(state);
            console.warn(`Passed login state must be of type 'string'. Received '${jsonState}'. Ignoring value. In a future version, an error will be thrown here.`);
            typeSafePassedState = undefined;
        }
        (0, authentication_1.redirectToLogin)(config, typeSafePassedState, additionalParameters, method).catch((error) => {
            console.error(error);
            setError(error.message);
            setLoginInProgress(false);
        });
    }
    function handleTokenResponse(response) {
        var _a, _b, _c;
        setToken(response.access_token);
        if (response.id_token) {
            setIdToken(response.id_token);
        }
        let tokenExp = timeUtils_1.FALLBACK_EXPIRE_TIME;
        // Decode IdToken, so we can use "exp" from that as fallback if expire not returned in the response
        try {
            if (response.id_token) {
                const decodedToken = (0, decodeJWT_1.decodeJWT)(response.id_token);
                tokenExp = Math.round(Number(decodedToken.exp) - Date.now() / 1000); // number of seconds from now
            }
        }
        catch (e) {
            console.warn(`Failed to decode idToken: ${e.message}`);
        }
        const tokenExpiresIn = (_b = (_a = config.tokenExpiresIn) !== null && _a !== void 0 ? _a : response.expires_in) !== null && _b !== void 0 ? _b : tokenExp;
        setTokenExpire((0, timeUtils_1.epochAtSecondsFromNow)(tokenExpiresIn));
        const refreshTokenExpiresIn = (_c = config.refreshTokenExpiresIn) !== null && _c !== void 0 ? _c : (0, timeUtils_1.getRefreshExpiresIn)(tokenExpiresIn, response);
        if (response.refresh_token) {
            setRefreshToken(response.refresh_token);
            if (!refreshTokenExpire || config.refreshTokenExpiryStrategy !== 'absolute') {
                setRefreshTokenExpire((0, timeUtils_1.epochAtSecondsFromNow)(refreshTokenExpiresIn));
            }
        }
    }
    function handleExpiredRefreshToken(initial = false) {
        // If it's the first page load, OR there is no sessionExpire callback, we trigger a new login
        if (initial)
            return logIn();
        // TODO: Breaking change - remove automatic login during ongoing session
        if (!config.onRefreshTokenExpire)
            return logIn();
        config.onRefreshTokenExpire({
            login: logIn,
            logIn,
        });
    }
    function refreshAccessToken(initial = false) {
        if (!token)
            return;
        // The token has not expired. Do nothing
        if (!(0, timeUtils_1.epochTimeIsPast)(tokenExpire))
            return;
        // Other instance (tab) is currently refreshing. This instance skip the refresh if not initial
        if (refreshInProgress && !initial)
            return;
        // If no refreshToken, act as if the refreshToken expired (session expired)
        if (!refreshToken)
            return handleExpiredRefreshToken(initial);
        // The refreshToken has expired
        if (refreshTokenExpire && (0, timeUtils_1.epochTimeIsPast)(refreshTokenExpire))
            return handleExpiredRefreshToken(initial);
        // The access_token has expired, and we have a non-expired refresh_token. Use it to refresh access_token.
        if (refreshToken) {
            setRefreshInProgress(true);
            (0, authentication_1.fetchWithRefreshToken)({ config, refreshToken })
                .then((result) => handleTokenResponse(result))
                .catch((error) => {
                if (error instanceof errors_1.FetchError) {
                    // If the fetch failed with status 400, assume expired refresh token
                    if (error.status === 400) {
                        handleExpiredRefreshToken(initial);
                        return;
                    }
                    // Unknown error. Set error, and log in if first page load
                    console.error(error);
                    setError(error.message);
                    if (initial)
                        logIn();
                }
                // Unknown error. Set error, and log in if first page load
                else if (error instanceof Error) {
                    console.error(error);
                    setError(error.message);
                    if (initial)
                        logIn();
                }
            })
                .finally(() => {
                setRefreshInProgress(false);
            });
            return;
        }
        console.warn('Failed to refresh access_token. Most likely there is no refresh_token, or the authentication server did not reply with an explicit expire time, and the default expire times are longer than the actual tokens expire time');
    }
    // Register the 'check for soon expiring access token' interval (every ~10 seconds).
    (0, react_1.useEffect)(() => {
        // The randomStagger is used to avoid multiple tabs logging in at the exact same time.
        const randomStagger = 10000 * Math.random();
        const interval = setInterval(() => refreshAccessToken(), 5000 + randomStagger);
        return () => clearInterval(interval);
    }, [token, refreshToken, refreshTokenExpire, tokenExpire, refreshInProgress]); // Replace the interval with a new when values used inside refreshAccessToken changes
    // This ref is used to make sure the 'fetchTokens' call is only made once.
    // Multiple calls with the same code will, and should, return an error from the API
    // See: https://beta.reactjs.org/learn/synchronizing-with-effects#how-to-handle-the-effect-firing-twice-in-development
    const didFetchTokens = (0, react_1.useRef)(false);
    // Load token-/idToken-data when tokens change
    (0, react_1.useEffect)(() => {
        try {
            if (idToken)
                setIdTokenData((0, decodeJWT_1.decodeJWT)(idToken));
        }
        catch (e) {
            console.warn(`Failed to decode idToken: ${e.message}`);
        }
        try {
            if (token && config.decodeToken)
                setTokenData((0, decodeJWT_1.decodeJWT)(token));
        }
        catch (e) {
            console.warn(`Failed to decode access token: ${e.message}`);
        }
    }, [token, idToken]);
    // Runs once on page load
    (0, react_1.useEffect)(() => {
        // The client has been redirected back from the auth endpoint with an auth code
        if (loginInProgress) {
            const urlParams = new URLSearchParams(window.location.search);
            if (!urlParams.get('code')) {
                // This should not happen. There should be a 'code' parameter in the url by now...
                const error_description = urlParams.get('error_description') ||
                    'Bad authorization state. Refreshing the page and log in again might solve the issue.';
                console.error(`${error_description}\nExpected  to find a '?code=' parameter in the URL by now. Did the authentication get aborted or interrupted?`);
                setError(error_description);
                clearStorage();
                return;
            }
            // Make sure we only try to use the auth code once
            if (!didFetchTokens.current) {
                didFetchTokens.current = true;
                try {
                    (0, authentication_1.validateState)(urlParams, config.storage);
                }
                catch (e) {
                    console.error(e);
                    setError(e.message);
                }
                // Request tokens from auth server with the auth code
                (0, authentication_1.fetchTokens)(config)
                    .then((tokens) => {
                    handleTokenResponse(tokens);
                    // Call any postLogin function in authConfig
                    if (config === null || config === void 0 ? void 0 : config.postLogin)
                        config.postLogin();
                    if (loginMethod === 'popup')
                        window.close();
                })
                    .catch((error) => {
                    console.error(error);
                    setError(error.message);
                })
                    .finally(() => {
                    if (config.clearURL) {
                        // Clear ugly url params
                        window.history.replaceState(null, '', `${window.location.pathname}${window.location.hash}`);
                    }
                    setLoginInProgress(false);
                });
            }
            return;
        }
        // First page visit
        if (!token && config.autoLogin)
            return logIn();
        refreshAccessToken(true); // Check if token should be updated
    }, []);
    return (react_1.default.createElement(exports.AuthContext.Provider, { value: {
            token,
            tokenData,
            idToken,
            idTokenData,
            login: logIn,
            logIn,
            logOut,
            error,
            loginInProgress,
        } }, children));
};
exports.AuthProvider = AuthProvider;
