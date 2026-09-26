from pipeline.dirty_ledger import DirtyLedger


def test_rewrite_extends_only_that_path_quiet_window():
    """Bulk/poll discovery keeps the long debounce and the long rewrite window."""
    ledger = DirtyLedger(debounce_ms=1500, rewrite_debounce_ms=2500)

    ledger.mark(["a.py", "b.py"], reason="disk_poll", now=0.0)
    ledger.mark(["a.py"], reason="disk_poll", now=1.0)

    assert ledger.due_paths(now=1.6) == ["b.py"]
    assert ledger.due_paths(now=3.6) == ["a.py"]


def test_hot_rewrite_extends_only_that_path_on_the_hot_window():
    """A save rewrite restarts its own quiet window — on the 250ms hot budget.

    Since 0.3.131 a save cannot wait out the 2.5s bulk rewrite window: the file
    has to be in map within 5s, and the embed stage alone costs ~1.7s here.
    """
    ledger = DirtyLedger(debounce_ms=1500, rewrite_debounce_ms=2500, hot_debounce_ms=250)

    ledger.mark(["a.py", "b.py"], reason="write", now=0.0)
    ledger.mark(["a.py"], reason="write", now=1.0)

    assert ledger.due_paths(now=0.3) == ["b.py"], "b.py settled on the hot window"
    assert ledger.due_paths(now=1.2) == []
    assert ledger.due_paths(now=1.26) == ["a.py"], "quiet window from the last save"


def test_complete_without_publish_reports_overlay_ready():
    ledger = DirtyLedger()

    ledger.mark(["a.py"], reason="write", now=0.0)
    ledger.begin(["a.py"])
    ledger.complete(["a.py"], published=False)

    assert ledger.snapshot()["paths"]["a.py"]["state"] == "overlay_ready"
