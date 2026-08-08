import { StatsigClientInterface } from './ClientInterfaces';
export type StatsigPlugin<T extends StatsigClientInterface> = {
    readonly __plugin: 'session-replay' | 'auto-capture' | 'triggered-session-replay' | 'cli-session-replay-node' | (string & {});
    bind: (client: T) => void;
};
