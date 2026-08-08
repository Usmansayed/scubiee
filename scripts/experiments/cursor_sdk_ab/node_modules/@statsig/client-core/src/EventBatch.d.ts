import { StatsigEventInternal } from './StatsigEvent';
export declare class EventBatch {
    attempts: number;
    readonly events: StatsigEventInternal[];
    readonly createdAt: number;
    constructor(events: StatsigEventInternal[]);
    incrementAttempts(): void;
}
