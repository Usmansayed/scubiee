"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.Diagnostics = void 0;
const MARKER_MAP = new Map();
const ACT_START = 'start';
const ACT_END = 'end';
const DIAGNOSTICS_EVENT = 'statsig::diagnostics';
exports.Diagnostics = {
    _getMarkers: (sdkKey) => {
        return MARKER_MAP.get(sdkKey);
    },
    _markInitOverallStart: (sdkKey) => {
        _addMarker(sdkKey, _createMarker({}, ACT_START, 'overall'));
    },
    _markInitOverallEnd: (sdkKey, success, evaluationDetails) => {
        _addMarker(sdkKey, _createMarker({
            success,
            error: success
                ? undefined
                : { name: 'InitializeError', message: 'Failed to initialize' },
            evaluationDetails,
        }, ACT_END, 'overall'));
    },
    _markInitNetworkReqStart: (sdkKey, data) => {
        _addMarker(sdkKey, _createMarker(data, ACT_START, 'initialize', 'network_request'));
    },
    _markInitNetworkReqEnd: (sdkKey, data) => {
        _addMarker(sdkKey, _createMarker(data, ACT_END, 'initialize', 'network_request'));
    },
    _markInitProcessStart: (sdkKey) => {
        _addMarker(sdkKey, _createMarker({}, ACT_START, 'initialize', 'process'));
    },
    _markInitProcessEnd: (sdkKey, data) => {
        _addMarker(sdkKey, _createMarker(data, ACT_END, 'initialize', 'process'));
    },
    _clearMarkers: (sdkKey) => {
        MARKER_MAP.delete(sdkKey);
    },
    _formatError(e) {
        if (!(e && typeof e === 'object')) {
            return;
        }
        return {
            code: _safeGetField(e, 'code'),
            name: _safeGetField(e, 'name'),
            message: _safeGetField(e, 'message'),
        };
    },
    _getDiagnosticsData(res, attempt, body, e) {
        var _a;
        return {
            success: (res === null || res === void 0 ? void 0 : res.ok) === true,
            statusCode: res === null || res === void 0 ? void 0 : res.status,
            sdkRegion: (_a = res === null || res === void 0 ? void 0 : res.headers) === null || _a === void 0 ? void 0 : _a.get('x-statsig-region'),
            isDelta: body.includes('"is_delta":true') === true ? true : undefined,
            attempt,
            error: exports.Diagnostics._formatError(e),
        };
    },
    _enqueueDiagnosticsEvent(user, logger, sdk, options) {
        const markers = exports.Diagnostics._getMarkers(sdk);
        if (markers == null || markers.length <= 0) {
            return -1;
        }
        const overallInitDuration = markers[markers.length - 1].timestamp - markers[0].timestamp;
        exports.Diagnostics._clearMarkers(sdk);
        const event = _makeDiagnosticsEvent(user, {
            context: 'initialize',
            markers: markers.slice(),
            statsigOptions: options,
        });
        logger.enqueue(event);
        return overallInitDuration;
    },
};
function _createMarker(data, action, key, step) {
    return Object.assign({ key: key, action: action, step: step, timestamp: Date.now() }, data);
}
function _makeDiagnosticsEvent(user, data) {
    const latencyEvent = {
        eventName: DIAGNOSTICS_EVENT,
        user,
        value: null,
        metadata: data,
        time: Date.now(),
    };
    return latencyEvent;
}
function _addMarker(sdkKey, marker) {
    var _a;
    const markers = (_a = MARKER_MAP.get(sdkKey)) !== null && _a !== void 0 ? _a : [];
    markers.push(marker);
    MARKER_MAP.set(sdkKey, markers);
}
function _safeGetField(data, field) {
    if (field in data) {
        return data[field];
    }
    return undefined;
}
