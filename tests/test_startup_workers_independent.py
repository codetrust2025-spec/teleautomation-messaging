"""One optional worker that cannot start must not stop the others.

Production case: `main.py` imported `core.daily_briefing` — a module that
belongs to Operations and has never existed in this repository — directly above
the inbox sweep and the interview reminder loop. Both of those were wrapped in
their own `try/except`, but the whole sequence shared one outer `try/except`,
so the unguarded import raised `ModuleNotFoundError`, the outer handler
swallowed it, and every worker below never started. The failure logged a single
generic "Startup background task error" line, so a boot with no workers running
looked much like a healthy one.

It reproduced on demand: restarting the container produced restart #10 and the
identical error, with `.running_workers.json` still empty. These lock the
behaviour that makes that impossible.
"""

import main
from core.startup_workers import start_optional_worker, start_optional_workers


def _decommissioned() -> None:
    """A worker whose module was moved to the other service."""
    import core.daily_briefing  # noqa: F401 - deliberately absent


def test_a_missing_module_does_not_stop_the_workers_after_it():
    started: list[str] = []
    logged: list[str] = []

    ran = start_optional_workers(
        (
            ("Decommissioned briefing", _decommissioned),
            ("Inbox sweep", lambda: started.append("sweep")),
            ("Interview reminder loop", lambda: started.append("reminder")),
        ),
        log=logged.append,
    )

    # The two live workers start even though the first one cannot.
    assert started == ["sweep", "reminder"]
    assert ran == ["Inbox sweep", "Interview reminder loop"]


def test_the_failing_worker_is_named_in_the_log():
    logged: list[str] = []
    assert start_optional_worker("Decommissioned briefing", _decommissioned, log=logged.append) is False
    assert len(logged) == 1
    # Naming the worker and the error is what turns a silent boot into a
    # diagnosable one.
    assert "Decommissioned briefing" in logged[0]
    assert "ModuleNotFoundError" in logged[0]


def test_a_worker_that_starts_reports_success_and_logs_nothing():
    logged: list[str] = []
    assert start_optional_worker("Live worker", lambda: None, log=logged.append) is True
    assert logged == []


def test_every_worker_is_attempted_even_when_all_of_them_fail():
    logged: list[str] = []

    def boom() -> None:
        raise RuntimeError("nope")

    assert start_optional_workers(
        (("First", _decommissioned), ("Second", boom)), log=logged.append
    ) == []
    assert len(logged) == 2, "each failure is reported on its own, not collapsed"


def test_startup_does_not_import_the_decommissioned_briefing_module():
    """The import that caused this must not come back.

    `core.daily_briefing` is an Operations module. Marketing importing it can
    only ever raise, so its absence from the executable source is the fix. The
    comment explaining why it is gone is expected to mention it, so this reads
    the parsed module rather than the raw text.
    """
    import ast

    tree = ast.parse(__import__("inspect").getsource(main))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert "core.daily_briefing" not in imported
    assert not any(name.startswith("core.daily_briefing") for name in imported)
