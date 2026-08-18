# Live reindexing delivery notes

Changed-file producers call `pipeline.live_reindex.notify_changed_files(repo, paths)`.
It accepts only repository-relative paths and forwards them to the daemon's
`/v1/dirty` endpoint; it never selects a full-index path.

The live loop coalesces writes, processes at most 40 files and 100 changed
chunks per batch, and exposes `catchup_chunked` plus `needs_full` telemetry
when it must catch up. It does not schedule a background full index. Locate
activity holds publication briefly; `final_check` forces a pending publish on
shutdown. Processed paths invalidate only matching session-store spans.
