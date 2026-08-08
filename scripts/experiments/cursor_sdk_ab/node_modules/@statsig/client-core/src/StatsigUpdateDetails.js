"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.UPDATE_DETAIL_ERROR_MESSAGES = exports.createUpdateDetails = void 0;
const createUpdateDetails = (success, source, initDuration, error, sourceUrl, warnings) => {
    return {
        duration: initDuration,
        source,
        success,
        error,
        sourceUrl,
        warnings,
    };
};
exports.createUpdateDetails = createUpdateDetails;
exports.UPDATE_DETAIL_ERROR_MESSAGES = {
    NO_NETWORK_DATA: 'No data was returned from the network. This may be due to a network timeout if a timeout value was specified in the options or ad blocker error.',
};
