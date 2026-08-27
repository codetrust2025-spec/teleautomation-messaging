"""nginx must be able to write its own temp files, or it truncates silently.

nginx spills any proxied response larger than its in-memory buffers — and any
client upload larger than `client_body_buffer_size` — into `/var/lib/nginx/*`.
If the worker user cannot write there, nginx **truncates the response at the
buffered amount and still returns HTTP 200** with an honest `Content-Length`.

Found in production 2026-08-27: those directories were owned by `nobody:root`
while workers run as `www-data`. A 566685-byte JS bundle was delivered cut to
~98KB, so the ES module never executed, React never mounted, and `/submit-slot`
rendered blank on both hostnames. No console error, no 5xx, nothing in the
access log. `curl -I` was actively misleading — HEAD returns the backend's
headers without a body, so it reported the full length.

A manual `chown` fixed the running host, but a reboot, a package update, or
anything recreating the directories would bring it straight back. The drop-in
reasserts ownership on every nginx start.

These assertions are on the checked-in provisioning file, so the fix cannot be
quietly dropped from the repo — which is the only copy that survives a rebuild.
"""

from __future__ import annotations

from pathlib import Path

DROPIN = (
    Path(__file__).resolve().parent.parent
    / "deploy" / "production" / "nginx-temp-dir-ownership.conf"
)

# Every temp path nginx is compiled to use. `body` matters as much as `proxy`:
# it is where the submit-slot invite screenshot, payment proofs and resumes land
# when they exceed the buffer.
TEMP_DIRS = ("proxy", "body", "fastcgi", "uwsgi", "scgi")


def _text() -> str:
    assert DROPIN.exists(), f"{DROPIN.name} is missing — the fix is host-only again"
    return DROPIN.read_text(encoding="utf-8")


def _directives() -> list[str]:
    return [l.strip() for l in _text().splitlines() if l.strip().startswith("ExecStartPre=")]


def test_it_is_a_systemd_service_dropin():
    assert "[Service]" in _text()
    assert _directives(), "no ExecStartPre directives — nothing would run"


def test_every_temp_directory_is_chowned_to_the_worker_user():
    chown = [d for d in _directives() if "chown" in d]
    assert chown, "no chown directive"
    line = chown[0]
    assert "www-data:www-data" in line, "must match the `user www-data;` worker"
    for name in TEMP_DIRS:
        assert f"/var/lib/nginx/{name}" in line, (
            f"/var/lib/nginx/{name} not covered — it would still truncate"
        )


def test_the_directories_are_created_before_they_are_chowned():
    """A chown on a missing directory fails and blocks nginx from starting."""
    directives = _directives()
    mkdir = next((i for i, d in enumerate(directives) if "mkdir" in d), None)
    chown = next((i for i, d in enumerate(directives) if "chown" in d), None)
    assert mkdir is not None, "no mkdir — chown would fail if a directory is absent"
    assert chown is not None
    assert mkdir < chown, "mkdir must precede chown"


def test_the_chown_is_recursive():
    """Ownership on the directory alone is not enough — nginx writes into the
    numbered subdirectories it creates beneath it."""
    chown = [d for d in _directives() if "chown" in d][0]
    assert " -R " in chown


def test_it_does_not_touch_routing():
    """This file exists to fix filesystem permissions. Anything that changes how
    requests are routed belongs in the nginx config, not a systemd unit."""
    body = _text()
    for forbidden in ("proxy_pass", "location ", "server_name", "listen "):
        assert forbidden not in body, f"{forbidden!r} does not belong in a systemd drop-in"
