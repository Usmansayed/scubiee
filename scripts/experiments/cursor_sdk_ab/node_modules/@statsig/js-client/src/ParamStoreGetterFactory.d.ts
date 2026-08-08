import { ParamStoreConfig, ParameterStoreEvaluationOptions, TypedGet } from '@statsig/client-core';
import StatsigClient from './StatsigClient';
export declare function _makeParamStoreGetter(client: StatsigClient, config: ParamStoreConfig | null, options: ParameterStoreEvaluationOptions | undefined): TypedGet;
