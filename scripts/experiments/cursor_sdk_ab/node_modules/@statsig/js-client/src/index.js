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
var __exportStar = (this && this.__exportStar) || function(m, exports) {
    for (var p in m) if (p !== "default" && !Object.prototype.hasOwnProperty.call(exports, p)) __createBinding(exports, m, p);
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.StatsigClient = void 0;
const client_core_1 = require("@statsig/client-core");
const StatsigClient_1 = require("./StatsigClient");
exports.StatsigClient = StatsigClient_1.default;
__exportStar(require("@statsig/client-core"), exports);
const __STATSIG__ = Object.assign((0, client_core_1._getStatsigGlobal)(), {
    StatsigClient: StatsigClient_1.default,
});
exports.default = __STATSIG__;
