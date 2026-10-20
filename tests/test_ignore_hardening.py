"""Builtin ignore hardening: case variants, real env detection, minified blobs —
and the false positives each rule must NOT produce."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.ignore import (
    clear_ignore_cache,
    content_indexable,
    filter_dirty_paths,
    is_builtin_ignored_dir_name,
    load_scubiee_ignore,
    should_index_rel,
)
from pipeline.merkle import scan_file_hashes
from pipeline.paths import collect_index_relpaths, index_rel_ok


@pytest.fixture(autouse=True)
def _clear():
    clear_ignore_cache()
    yield
    clear_ignore_cache()


def _scan(root: Path) -> set[str]:
    return {k.replace("\\", "/") for k in scan_file_hashes(root)}


def _w(root: Path, rel: str, text: str = "x = 1\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "rel",
    [
        "Node_Modules/pkg/index.js",
        "NODE_MODULES/pkg/index.js",
        "lib/Site-Packages/requests/api.py",
        "src/__PYCACHE__/x.py",
        "Venv/Lib/x.py",
        "venv2/lib/x.py",
        "venv-3.11/lib/x.py",
        "venv_old/lib/x.py",
        "venvs/proj/lib/x.py",
        ".Venv/lib/x.py",
    ],
)
def test_dependency_dirs_any_case_skipped(rel: str):
    assert not should_index_rel(None, rel)


@pytest.mark.parametrize(
    "rel",
    [
        "venvtools/cli.py",
        "venvironment/setup.py",
        "src/Build/Build.cs",
        "Vendor/Lib/Thing.cs",
        "Dist/main.go",
        "Coverage/report.py",
        "Target/app.rs",
        "packages/pipeline/ignore.py",
        "lib/node_helpers.js",
        "src/env/config.py",
    ],
)
def test_normal_source_kept(rel: str):
    assert should_index_rel(None, rel)


def test_name_rule_unchanged_for_lowercase_build_without_root():
    assert is_builtin_ignored_dir_name("build")
    assert not is_builtin_ignored_dir_name("Build")
    assert not is_builtin_ignored_dir_name("venvtools")


def test_custom_named_venv_detected_by_pyvenv_cfg(tmp_path: Path):
    _w(tmp_path, "env/pyvenv.cfg", "home = C:/Python311\n")
    _w(tmp_path, "env/Scripts/activate_this.py")
    _w(tmp_path, "py311/pyvenv.cfg", "home = x\n")
    _w(tmp_path, "py311/Lib/foo.py")
    _w(tmp_path, "src/app.py")
    rels = collect_index_relpaths(tmp_path)
    assert rels == {"src/app.py"}
    assert _scan(tmp_path) == {"src/app.py"}


def test_conda_env_detected_by_conda_meta(tmp_path: Path):
    (tmp_path / "envs/ml/conda-meta").mkdir(parents=True)
    _w(tmp_path, "envs/ml/lib/x.py")
    _w(tmp_path, "src/app.py")
    assert collect_index_relpaths(tmp_path) == {"src/app.py"}


def test_folder_named_env_without_marker_is_kept(tmp_path: Path):
    _w(tmp_path, "env/settings.py")
    _w(tmp_path, "src/env/loader.py")
    assert collect_index_relpaths(tmp_path) == {"env/settings.py", "src/env/loader.py"}


def test_build_and_out_kept_when_python_package(tmp_path: Path):
    _w(tmp_path, "src/build/__init__.py")
    _w(tmp_path, "src/build/compiler.py")
    _w(tmp_path, "tools/out/__init__.py")
    _w(tmp_path, "tools/out/report.py")
    _w(tmp_path, "build/lib/app.py")
    _w(tmp_path, "out/bundle.js")
    rels = collect_index_relpaths(tmp_path)
    assert rels == {
        "src/build/__init__.py",
        "src/build/compiler.py",
        "tools/out/__init__.py",
        "tools/out/report.py",
    }
    assert _scan(tmp_path) == rels


def test_lowercased_key_into_pascalcase_build_dir_is_kept(tmp_path: Path):
    _w(tmp_path, "Build/Build.cs", "class Build {}\n")
    # Windows Merkle keys are lower-cased; the real folder name decides.
    assert should_index_rel(tmp_path, "Build/Build.cs")
    assert should_index_rel(tmp_path, "build/build.cs")
    kept, dropped = filter_dirty_paths(tmp_path, ["build\\build.cs"])
    assert dropped == []
    assert [k.replace("\\", "/") for k in kept] == ["build/build.cs"]


def test_real_lowercase_build_dir_still_ignored_with_root(tmp_path: Path):
    _w(tmp_path, "build/lib/app.py")
    assert not should_index_rel(tmp_path, "build/lib/app.py")
    assert not should_index_rel(tmp_path, "build", is_dir=True)


def test_deleted_build_package_key_is_not_junk(tmp_path: Path):
    # A stored key under a folder that no longer exists must stay visible so the
    # poll reports the deletion and the chunks are pruned.
    assert should_index_rel(tmp_path, "build_pkg/build/compiler.py")
    assert should_index_rel(tmp_path, "build/build.cs")


def test_minified_by_name_skipped_but_normal_js_kept(tmp_path: Path):
    _w(tmp_path, "static/app.min.js", "var a=1;\n")
    _w(tmp_path, "static/app.js", "var a = 1;\n")
    _w(tmp_path, "static/admin.mjs", "export const a = 1;\n")
    assert collect_index_relpaths(tmp_path) == {"static/app.js", "static/admin.mjs"}


def test_one_line_blob_skipped_but_large_normal_file_kept(tmp_path: Path):
    blob = _w(tmp_path, "gen/bundle.js", "var a=1;" * 20_000)
    big = _w(tmp_path, "src/big.py", "".join(f"x{i} = {i}\n" for i in range(8_000)))
    long_first = _w(tmp_path, "src/long.py", "# " + "y" * 9_000 + "\nx = 1\n")
    assert big.stat().st_size > 50_000
    assert not content_indexable(blob)
    assert content_indexable(big)
    assert content_indexable(long_first)  # small file: a long line is fine
    assert collect_index_relpaths(tmp_path) == {"src/big.py", "src/long.py"}


def test_filter_dirty_drops_case_variants_and_relativises(tmp_path: Path):
    _w(tmp_path, "src/app.py")
    kept, dropped = filter_dirty_paths(
        tmp_path,
        [
            "Node_Modules/x/index.js",
            "lib/Site-Packages/r/api.py",
            "static/app.min.js",
            str(tmp_path / "src" / "app.py"),
            "venvtools/cli.py",
        ],
    )
    assert {d["path"] for d in dropped} == {
        "Node_Modules/x/index.js",
        "lib/Site-Packages/r/api.py",
        "static/app.min.js",
    }
    assert "venvtools/cli.py" in kept
    assert any(k.endswith("src/app.py") for k in kept)


def test_index_rel_ok_rejects_file_inside_custom_venv(tmp_path: Path):
    _w(tmp_path, "tools_env/pyvenv.cfg", "home = x\n")
    _w(tmp_path, "tools_env/Lib/mod.py")
    rules = load_scubiee_ignore(tmp_path)
    assert not index_rel_ok(tmp_path, "tools_env/Lib/mod.py", rules=rules)


def _gitignore_repo(root: Path) -> None:
    _w(root, ".gitignore", "laya_bench/\nsecret_*.py\n*.log\n")
    _w(root, "laya_bench/bench.py")
    _w(root, "src/secret_keys.py")
    _w(root, "src/app.py")
    _w(root, "src/laya_benchmark.py")


def test_gitignored_files_refused_on_dirty_path_and_scan_matches_collector(tmp_path: Path):
    _gitignore_repo(tmp_path)
    rules = load_scubiee_ignore(tmp_path)
    assert not index_rel_ok(tmp_path, "laya_bench/bench.py", rules=rules)
    assert not index_rel_ok(tmp_path, "src/secret_keys.py", rules=rules)
    assert index_rel_ok(tmp_path, "src/app.py", rules=rules)
    assert index_rel_ok(tmp_path, "src/laya_benchmark.py", rules=rules)
    expected = {"src/app.py", "src/laya_benchmark.py"}
    assert collect_index_relpaths(tmp_path) == expected
    assert _scan(tmp_path) == expected


def test_gitignored_folder_pattern_does_not_hide_deleted_folder(tmp_path: Path):
    from pipeline.paths import gitignored

    _w(tmp_path, ".gitignore", "build_out/\n")
    # Folder gone: a stored path under it must stay visible so its removal syncs.
    assert not gitignored(tmp_path, "build_out/gen.py")
    _w(tmp_path, "build_out/gen.py")
    clear_ignore_cache()
    assert gitignored(tmp_path, "build_out/gen.py")


def test_unindexable_includes_gitignored_existing_files(tmp_path: Path):
    from pipeline.incremental import _unindexable

    _gitignore_repo(tmp_path)
    out = _unindexable(
        tmp_path, ["laya_bench/bench.py", "src/secret_keys.py", "src/app.py", "laya_bench/gone.py"]
    )
    assert out == {"laya_bench/bench.py", "src/secret_keys.py"}


def test_unindexable_marks_forced_junk_only(tmp_path: Path):
    from pipeline.incremental import _unindexable

    _w(tmp_path, "src/app.py")
    _w(tmp_path, "Node_Modules/x/index.js")
    _w(tmp_path, "static/app.min.js")
    out = _unindexable(
        tmp_path, ["src/app.py", "Node_Modules/x/index.js", "static/app.min.js", "gone.py"]
    )
    assert out == {"Node_Modules/x/index.js", "static/app.min.js"}
