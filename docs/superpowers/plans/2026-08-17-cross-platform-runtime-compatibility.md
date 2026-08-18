# Cross-Platform Runtime Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist one install-time OS/hardware profile, run it without re-selection, and keep CE searchable through portable resource pressure and temporary CPU backup.

**Architecture:** `ctx init` is the only profile chooser: it detects the host, validates one provider, calibrates batch, derives an initial RAM envelope, and writes a preferred profile. Runtime loads that profile unchanged; the portable ResourceManager applies live pressure limits without selecting another OS stack. A failed accelerated session may use a temporary CPU backup but never overwrites the installed preference.

**Tech Stack:** Python 3.13, FastEmbed, ONNX Runtime CUDA/DirectML/CPU providers, psutil, pytest.

## Global Constraints

- `ctx init` / `ctx setup` are the only commands that choose a stack, provider device, package set, or batch winner.
- Normal `ctx serve`, MCP, doctor, indexing, and ResourceManager must load the persisted profile; they must not re-calibrate or re-select a stack.
- Batch candidates are `8`, `16`, `20`; prefer `16`; promote `20` only for ≥10% and ≥3 t/s gain.
- Resource policy is portable across Windows, Linux, and macOS; OS-specific package/provider handling is install-only.
- Runtime accelerated failures use a temporary CPU backup and preserve `accel.json`.
- Keep last coherent search available when indexing is reduced, deferred, or temporarily backed up.
- Native hardware/client labs may skip neutrally and never increase passed count.

---

### Task 1: Persist an install-time preferred profile and runtime state

**Files:**
- Modify: `packages/pipeline/accel.py`
- Create: `packages/pipeline/runtime_profile.py`
- Test: `tests/test_runtime_profile.py`

**Interfaces:**
- Produces `InstalledProfile(preferred: AccelProfile, envelope: EnvelopeConfig, hardware_fingerprint: str)`.
- Produces `RuntimeProfileState(preferred_profile: str, active_profile: str, backup_reason: str | None)`.
- Produces `load_installed_profile() -> InstalledProfile | None`.
- Produces `activate_cpu_backup(reason: str) -> RuntimeProfileState`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_runtime_loads_saved_profile_without_recommendation(monkeypatch, tmp_path):
    saved = AccelProfile(profile="dml", provider="DmlExecutionProvider", batch_size=16)
    save_accel(saved, tmp_path / "accel.json")
    monkeypatch.setattr(runtime_profile, "ACCEL_PATH", tmp_path / "accel.json")
    monkeypatch.setattr(accel, "recommend_profile", lambda: pytest.fail("must not re-choose"))
    assert load_installed_profile().preferred.profile == "dml"

def test_cpu_backup_keeps_preferred_profile(tmp_path):
    state = RuntimeProfileState(preferred_profile="dml", active_profile="dml")
    backed_up = activate_cpu_backup(state, "provider session failed")
    assert backed_up.preferred_profile == "dml"
    assert backed_up.active_profile == "cpu"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_profile.py -q`

Expected: FAIL because `runtime_profile` and its interfaces do not exist.

- [ ] **Step 3: Implement profile/state boundaries**

```python
@dataclass(frozen=True)
class RuntimeProfileState:
    preferred_profile: str
    active_profile: str
    backup_reason: str | None = None

def activate_cpu_backup(state: RuntimeProfileState, reason: str) -> RuntimeProfileState:
    return replace(state, active_profile="cpu", backup_reason=reason)
```

`load_installed_profile()` must read saved profile data only; it must never call provider selection or calibration.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_profile.py -q`

Expected: PASS.

### Task 2: Add portable available-memory envelope policy

**Files:**
- Create: `packages/pipeline/resource_envelope.py`
- Modify: `packages/pipeline/resources.py`
- Test: `tests/test_resource_envelope.py`

**Interfaces:**
- Produces `EnvelopeTier = Literal["low", "standard", "high"]`.
- Produces `derive_envelope(total_mb: float, available_mb: float, calibrated_batch: int, cpu_count: int) -> EnvelopeConfig`.
- `EnvelopeConfig` exposes `tier`, `batch_ceiling`, `embed_workers`, `index_workers`, `aggressive_unload`, and `queue_limit`.
- `ResourceManager.budget()` consumes the persisted calibrated batch capped by the current envelope; it never calls acceleration selection.

- [ ] **Step 1: Write failing tier tests**

```python
def test_low_memory_envelope_caps_batch_and_workers():
    env = derive_envelope(16_000, 2_500, calibrated_batch=16, cpu_count=8)
    assert env.tier == "low"
    assert env.batch_ceiling <= 4
    assert env.embed_workers == 1
    assert env.index_workers == 1

def test_high_memory_envelope_keeps_calibrated_16():
    env = derive_envelope(32_000, 20_000, calibrated_batch=16, cpu_count=16)
    assert env.tier == "high"
    assert env.batch_ceiling == 16
    assert env.embed_workers == 1
    assert env.index_workers > 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_resource_envelope.py -q`

Expected: FAIL because `resource_envelope` does not exist.

- [ ] **Step 3: Implement deterministic envelope derivation and integrate ResourceManager**

```python
def derive_envelope(total_mb, available_mb, calibrated_batch, cpu_count):
    if total_mb <= 8_192 or available_mb < 3_072:
        return EnvelopeConfig("low", min(4, calibrated_batch), 1, 1, True, 1)
    if total_mb >= 32_768 and available_mb >= 8_192:
        return EnvelopeConfig("high", calibrated_batch, 1, min(4, max(1, cpu_count // 4)), False, 4)
    return EnvelopeConfig("standard", min(16, calibrated_batch), 1, min(2, max(1, cpu_count // 4)), False, 2)
```

Add hysteresis in `ResourceManager`: require two consecutive lower-tier samples before demotion and two healthy samples before promotion.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_resource_envelope.py tests/test_resources.py -q`

Expected: PASS.

### Task 3: Make init the only OS/provider chooser

**Files:**
- Modify: `packages/pipeline/accel.py`
- Modify: `packages/pipeline/__main__.py`
- Modify: `packages/pipeline/hardware.py`
- Test: `tests/test_install_profile_selection.py`

**Interfaces:**
- `configure(...) -> AccelProfile` remains the install-time chooser and writes `batch_calibration`.
- `resolve_runtime() -> AccelProfile` loads saved profile only.
- `ctx init --repair` explicitly permits a new detect/install/probe/calibration cycle.
- `ctx init --status` is read-only and prints preferred profile plus envelope.

- [ ] **Step 1: Write failing install-only tests**

```python
def test_resolve_runtime_returns_saved_profile_without_detect(monkeypatch, tmp_path):
    monkeypatch.setattr(accel, "load_accel", lambda: AccelProfile("dml", "DmlExecutionProvider"))
    monkeypatch.setattr(accel, "recommend_profile", lambda: pytest.fail("runtime must not choose"))
    assert accel.resolve_runtime().profile == "dml"

def test_init_calibration_persists_preferred_profile(monkeypatch, tmp_path):
    profile = configure(install_pkgs=False, download_model=False, bench=True)
    assert profile.batch_calibration["winner"] in {8, 16, 20}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_install_profile_selection.py -q`

Expected: FAIL for missing runtime-only guard / repair interface.

- [ ] **Step 3: Implement init-only controls**

Add CLI `--repair` only to `init`; make it the explicit re-probe path. Keep `serve` free of `configure`, `recommend_profile`, package installation, and batch calibration calls.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_install_profile_selection.py tests/test_batch_calibration.py -q`

Expected: PASS.

### Task 4: Temporary CPU backup and portable runtime health/status

**Files:**
- Modify: `packages/pipeline/embedder.py`
- Modify: `packages/pipeline/resources.py`
- Modify: `packages/pipeline/ce_service.py`
- Modify: `packages/pipeline/doctor.py`
- Test: `tests/test_runtime_cpu_backup.py`

**Interfaces:**
- `Embedder` retries one failed accelerated embedding request with an in-process CPU embedder at one lower batch ceiling.
- `RuntimeManager.status()` exposes `preferred_profile`, `active_profile`, `backup_reason`, `envelope`, and `recommended_command`.
- `doctor` reports the saved preferred profile and active fallback state without reconfiguring.

- [ ] **Step 1: Write failing backup/status tests**

```python
def test_accelerated_embed_failure_uses_temporary_cpu_backup(monkeypatch):
    embedder = Embedder(...)
    monkeypatch.setattr(embedder, "_embed_fastembed", Mock(side_effect=RuntimeError("DML failed")))
    monkeypatch.setattr(embedder, "_embed_cpu_backup", Mock(return_value=[[0.0] * 768]))
    assert len(embedder.embed(["x"])) == 1
    assert embedder.runtime_state.active_profile == "cpu"
    assert embedder.runtime_state.preferred_profile == "dml"

def test_doctor_reports_preferred_and_active_backup():
    report = doctor_report(...)
    assert report["accel"]["preferred_profile"] == "dml"
    assert report["accel"]["active_profile"] == "cpu"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_cpu_backup.py -q`

Expected: FAIL because temporary backup state and doctor fields do not exist.

- [ ] **Step 3: Implement single-retry CPU backup**

The retry must be bounded to one attempt per embedding operation. It must not call `save_accel`, `configure`, or install packages. Persist only in-memory runtime state and include the exception reason in status.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runtime_cpu_backup.py tests/test_resources.py -q`

Expected: PASS.

### Task 5: Provider validation and cross-platform certification contract

**Files:**
- Modify: `packages/pipeline/preflight.py`
- Modify: `packages/pipeline/certify.py`
- Modify: `packages/pipeline/doctor.py`
- Create: `tests/test_cross_platform_profiles.py`
- Modify: `docs/reindexing/production-operator-runbook.md`

**Interfaces:**
- `validate_provider(profile) -> ProviderValidation` validates installed provider plus model warm-up.
- `recommended_server_command(profile) -> str` returns a command based on saved profile only.
- Certification checks return `passed`, `failed`, or neutral `skipped`; skipped hardware lanes never count as passed.

- [ ] **Step 1: Write failing platform simulation tests**

```python
@pytest.mark.parametrize(
    ("os_name", "nvidia", "providers", "expected"),
    [
        ("Windows", False, ["DmlExecutionProvider"], "dml"),
        ("Linux", True, ["CUDAExecutionProvider"], "cuda"),
        ("Linux", False, ["CPUExecutionProvider"], "cpu"),
        ("Darwin", False, ["CPUExecutionProvider"], "cpu"),
    ],
)
def test_install_profile_is_validated_or_cpu_safe(...):
    ...

def test_missing_hardware_lane_is_skipped_not_passed():
    check = certify_platform_lane(...)
    assert check["status"] == "skipped"
    assert check["ok"] is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cross_platform_profiles.py -q`

Expected: FAIL because simulated platform profile validation is incomplete.

- [ ] **Step 3: Implement provider validation/reporting and update runbook**

Keep Linux AMD and Apple Silicon GPU paths `cpu-safe unless provider validation succeeds`; do not claim ROCm/Metal support merely from OS detection. Document `ctx init`, `ctx init --repair`, `ctx doctor`, and `ctx serve` startup/recovery behavior.

- [ ] **Step 4: Run tests and certification**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cross_platform_profiles.py tests/test_preflight.py tests/test_doctor_certify.py -q`

Run: `PYTHONPATH=packages python -m pipeline doctor .`

Run: `PYTHONPATH=packages python -m pipeline certify .`

Expected: deterministic tests PASS; unavailable native hardware lanes SKIPPED neutrally.

### Task 6: Full regression and operator verification

**Files:**
- Modify: `questions-answered.md`
- Test: relevant core/fault suites

**Interfaces:**
- `questions-answered.md` accurately reflects install-only selection, portable runtime, and temporary CPU backup.

- [ ] **Step 1: Update answer evidence**

Add the install-only policy and certification results. Do not claim Linux AMD or Apple GPU acceleration unless a real provider/model lab passed.

- [ ] **Step 2: Run full relevant regression**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_batch_calibration.py tests/test_runtime_profile.py tests/test_resource_envelope.py tests/test_install_profile_selection.py tests/test_runtime_cpu_backup.py tests/test_cross_platform_profiles.py tests/test_resources.py tests/test_preflight.py tests/test_doctor_certify.py tests/test_production_scenarios.py -q`

Expected: PASS, apart from explicitly marked neutral native-hardware skips.

- [ ] **Step 3: Run DML native lab**

Run: `PYTHONPATH=packages python -m pipeline init --status`

Run: `PYTHONPATH=packages python -m pipeline doctor .`

Expected: installed DML preferred profile, active DML profile, calibrated batch 16 unless the ROI rule promoted 20.
