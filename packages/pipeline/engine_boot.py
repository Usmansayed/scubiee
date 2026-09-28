"""Boot shim for an engine created by WMI (outside the caller's process tree/job).

``Win32_Process.Create`` cannot pass stdio handles or an environment, so the
spawner writes both into a one-shot JSON file. This shim applies the
environment, deletes the file, points stdout/stderr at engine.log, and then runs
``python -m pipeline <args>`` exactly as the Popen path would.

    pythonw -u -m pipeline.engine_boot <boot.json> engine run <repo> --host .. --port ..
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: python -m pipeline.engine_boot <boot.json> <pipeline args...>")
    boot_path = Path(args[0])
    rest = args[1:]
    data: dict = {}
    try:
        data = json.loads(boot_path.read_text(encoding="utf-8"))
    finally:
        # Environment may carry config the user set for the IDE; do not leave it on disk.
        try:
            boot_path.unlink()
        except OSError:
            pass
    for key, value in (data.get("env") or {}).items():
        os.environ[str(key)] = str(value)
    os.environ["CTX_ENGINE_SPAWN_METHOD"] = "wmi"
    log = data.get("log")
    if log:
        from pipeline.engine_log import redirect_stdio_to

        redirect_stdio_to(
            log,
            banner=(
                f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"(wmi orphan pid={os.getpid()} requested_by={data.get('requested_by')}) ---\n"
            ),
        )
    sys.argv = [sys.argv[0], *rest]
    runpy.run_module("pipeline", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
