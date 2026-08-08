import { StatsigWarnings } from './EvaluationTypes';
import { DataSource } from './StatsigDataAdapter';
export type StatsigUpdateDetails = {
    duration: number;
    source: DataSource;
    success: boolean;
    error: Error | null;
    sourceUrl: string | null;
    warnings?: StatsigWarnings[];
};
export declare const createUpdateDetails: (success: boolean, source: DataSource, initDuration: number, error: Error | null, sourceUrl: string | null, warnings?: StatsigWarnings[]) => StatsigUpdateDetails;
export declare const UPDATE_DETAIL_ERROR_MESSAGES: {
    NO_NETWORK_DATA: string;
};
