import { StatsigGlobal } from '@statsig/client-core';
import StatsigClient from './StatsigClient';
import type { StatsigOptions } from './StatsigOptions';
export * from '@statsig/client-core';
export type { StatsigEnvironment, StatsigEvent, StatsigUser, InitializeResponse, StatsigPlugin, } from '@statsig/client-core';
export type { StatsigOptions };
export { StatsigClient };
declare const __STATSIG__: StatsigGlobal;
export default __STATSIG__;
