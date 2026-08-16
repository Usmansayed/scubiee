from pipeline.dirty_ledger import DirtyLedger


def test_rewrite_extends_only_that_path_quiet_window():
    ledger = DirtyLedger(debounce_ms=1500, rewrite_debounce_ms=2500)

    ledger.mark(["a.py", "b.py"], reason="write", now=0.0)
    ledger.mark(["a.py"], reason="write", now=1.0)

    assert ledger.due_paths(now=1.6) == ["b.py"]
    assert ledger.due_paths(now=3.6) == ["a.py"]


def test_complete_without_publish_reports_overlay_ready():
    ledger = DirtyLedger()

    ledger.mark(["a.py"], reason="write", now=0.0)
    ledger.begin(["a.py"])
    ledger.complete(["a.py"], published=False)

    assert ledger.snapshot()["paths"]["a.py"]["state"] == "overlay_ready"
