from __future__ import annotations

import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.dashboard_server import create_dashboard_server


UI_ROOT = Path("packages/pipeline/dashboard_ui")


def _get(url: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(url, timeout=2) as response:
        return (
            response.status,
            response.headers.get_content_type(),
            response.read().decode("utf-8"),
        )


def test_ce_dashboard_serves_light_sidebar_shell_and_assets():
    server = create_dashboard_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/ce-dashboard"
    try:
        status, content_type, html = _get(f"{base}/")
        assert status == 200
        assert content_type == "text/html"
        for label in (
            "Overview",
            "Repositories",
            "Index &amp; Sync",
            "Storage",
            "Health",
            "Runtime",
            "Graph",
            "Settings",
        ):
            assert label in html

        css_status, css_type, css = _get(f"{base}/styles.css")
        assert css_status == 200
        assert css_type == "text/css"
        assert "--surface:" in css

        js_status, js_type, javascript = _get(f"{base}/app.js")
        assert js_status == 200
        assert js_type in {"application/javascript", "text/javascript"}
        assert '"/ce-dashboard/api"' in javascript

        lucide_status, lucide_type, lucide = _get(f"{base}/lucide.min.js")
        assert lucide_status == 200
        assert lucide_type in {"application/javascript", "text/javascript"}
        assert "lucide" in lucide.lower()
        assert "/ce-dashboard/lucide.min.js" in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_repository_and_settings_safety_contracts_are_present():
    html = (UI_ROOT / "index.html").read_text(encoding="utf-8")
    javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="forget-dialog"' in html
    assert 'id="forget-confirmation"' in html
    assert "type the repository" in html.lower()
    assert "Source files stay on disk" in html
    assert 'value="automatic"' in html
    assert 'value="mcp_cli"' in html
    assert "admission_mode" in javascript
    assert "clear-index" in javascript
    assert 'runRepoAction(projectId, "forget"' in javascript
    assert "Forget is unavailable until presence validation" not in javascript
    assert 'data-action="forget"' in javascript
    assert "${repo.forget_allowed" not in javascript
    assert 'id="apply-safe-repairs"' in html
    assert "Apply safe repairs" in html
    assert 'api("doctor"' in javascript
    assert 'api("repair"' in javascript


def test_graph_ui_bounds_rendered_and_listed_links():
    javascript = (UI_ROOT / "app.js").read_text(encoding="utf-8")

    assert "const edges = allEdges.filter((edge) =>" in javascript
    assert "nodeIds.has(String(edge.target))\n    ).slice(0, 100);" in javascript
    assert '$("#graph-edge-list").innerHTML = edges.length' in javascript
    assert "Showing ${edges.length} of ${allEdges.length} links" in javascript


def test_storage_payload_renders_object_arrays_as_readable_rows():
    payload = {
        "repositories": [
            {
                "project_id": "ce_alpha",
                "store_dir": "C:/context-engine/projects/ce_alpha",
                "collection": "code",
                "collection_dir": "C:/context-engine/projects/ce_alpha/code",
                "store_bytes": 1024,
                "vector_bytes": 1024,
                "bytes_used": 2048,
                "reclaimable_bytes": 256,
                "live_vectors": 12,
                "dead_vectors": 2,
                "last_access": 1_786_985_000,
                "pinned": True,
                "managed": True,
            },
            {
                "project_id": "ce_beta",
                "store_dir": "C:/context-engine/projects/ce_beta",
                "collection": "code",
                "collection_dir": "C:/context-engine/projects/ce_beta/code",
                "store_bytes": 3072,
                "vector_bytes": 1024,
                "bytes_used": 4096,
                "reclaimable_bytes": 0,
                "live_vectors": 8,
                "dead_vectors": 0,
                "last_access": 1_786_985_100,
                "pinned": False,
                "managed": True,
            },
            {
                "project_id": "ce_orphan",
                "store_dir": "C:/context-engine/projects/ce_orphan",
                "collection": "code",
                "collection_dir": "C:/context-engine/projects/ce_orphan/code",
                "store_bytes": 512,
                "vector_bytes": 512,
                "bytes_used": 1024,
                "reclaimable_bytes": 1024,
                "live_vectors": 0,
                "dead_vectors": 4,
                "last_access": 1_786_980_000,
                "pinned": False,
                "managed": False,
            },
        ],
        "eviction": {
            "candidates": [
                {
                    "project_id": "ce_old",
                    "store_dir": "C:/context-engine/projects/ce_old",
                    "collection": "code",
                    "bytes_used": 8192,
                    "reclaimable_bytes": 6144,
                    "last_access": 1_786_900_000,
                }
            ]
        },
    }
    script = (
        "const render = require('./packages/pipeline/dashboard_ui/storage_render.js');"
        f"const html = render.renderStorageSections({json.dumps(payload)});"
        "process.stdout.write(html);"
    )

    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "ce_alpha" in result.stdout
    assert "C:/context-engine/projects/ce_alpha" in result.stdout
    assert "2 KB" in result.stdout
    assert ">pinned<" in result.stdout
    assert "ce_beta" in result.stdout
    assert ">managed<" in result.stdout
    assert "ce_orphan" in result.stdout
    assert ">unmanaged<" in result.stdout
    assert "ce_old" in result.stdout
    assert "C:/context-engine/projects/ce_old" in result.stdout
    assert "8 KB" in result.stdout
    assert ">candidate<" in result.stdout
    assert "[object Object]" not in result.stdout


def test_dashboard_static_handler_rejects_unknown_assets():
    server = create_dashboard_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = (
        f"http://127.0.0.1:{server.server_address[1]}"
        "/ce-dashboard/not-a-real-asset.js"
    )
    try:
        try:
            urllib.request.urlopen(url, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
            assert exc.headers.get_content_type() == "application/json"
        else:
            raise AssertionError("unknown dashboard assets must return 404")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
