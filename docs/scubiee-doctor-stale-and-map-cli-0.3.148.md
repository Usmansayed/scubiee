# 0.3.148: doctor stale-entry handling + map CLI path-arg fix

Two UX issues flagged during the production review, fixed after a reasoning pass
on the correct behavior (not just the symptom).

## 1. `doctor` reported `ok=False` from stale registry entries

**Symptom.** After deleting/moving a repo folder without `scubiee remove`, the
global registry keeps an entry whose path no longer exists. `audit_connect_registry`
treated every such `stale_registry_path` as a *blocking* warning, so `doctor`
reported `ok=False` and exited non-zero, even though the user's actual working
repo was perfectly healthy.

**Reasoning / decision.** Three options were weighed:
- Auto-prune in doctor → rejected: doctor is read-only by contract (a test
  enforces it), and deleting on `path.is_dir()==False` would wrongly forget a
  repo on a temporarily-unmounted drive before the existing 24h retention window.
- Downgrade stale to a non-blocking warning → chosen. A stale entry is advisory,
  not a health failure of the current repo. Matches the existing precedent where
  an unbound daemon (`bind_daemon`) is already carved out as non-blocking.
- Add a retention-safe prune to `doctor --fix` → chosen as a complement, so the
  user has a one-command cleanup that still protects unmounted drives.

**Fix.**
- `managed_repos.audit_connect_registry`: `stale_registry_path` removed from the
  `blocking` set (still emitted as a warning; now carries `project_id`/`path`
  structurally). `connected_tools_no_managed_repos` and `shared_id_copy_collision`
  stay blocking.
- `doctor.doctor_repo`: `stale_registry_path` added to the non-blocking carve-out
  (alongside `bind_daemon`) so it never forces `ok=False`.
- `doctor.plan_repairs` / `apply_safe_repairs`: `stale_registry_path` is a *safe*
  repair that prunes via `forget_repo(pid)`, which refuses unless the path has
  been missing past the retention window. A freshly-missing repo (possible
  unmounted drive) is kept; a long-gone one is pruned.
- `doctor.doctor_repo` and `apply_safe_repairs` hardened against a missing repo
  root (`FileNotFoundError`/`NotADirectoryError`/`OSError`): a diagnostic must
  never crash on a stale/unmounted path. Path-dependent safe repairs
  (bind_daemon, initialize_index, replay_dirty_journal, reconcile_git_family)
  are skipped to manual when the repo dir is absent.

**Tests.** `test_doctor_connect_registry.py`: stale path is detected + warned but
`ok=True`; `--fix` prunes a long-gone entry; a recently-missing entry (unmounted
drive) is retained. 14/14 doctor tests green.

## 2. `map` CLI reported `(not resolved: .)` for a trailing path arg

**Symptom.** `scubiee map --config focus --names <sym> .` showed the result AND a
spurious `(not resolved: .)`. argparse's `--names` (nargs="*") greedily swallowed
the trailing `.` path positional, so `.` was treated as a second symbol name.

**Fix.** `cmd_map`: a symbol name is never a real directory, pull dir-like
entries (`.`, `..`, or an existing dir) out of `names` and use the last as the
repo path. `path` defaults to ".", so detection is on the names themselves, not
on whether `path` was set.

## Not changed (deliberately)

- `replay_dirty_journal` remaining a blocking repair when a dirty journal is
  pending is correct (real queued work), a separate subsystem from the reported
  issues, and left as-is.
- Large-repo scale, grammar-less languages, and non-Apple-Silicon platforms are
  documented limits, not changed speculatively.
