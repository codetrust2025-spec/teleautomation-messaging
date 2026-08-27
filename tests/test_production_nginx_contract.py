"""The nginx template must not regress what production actually serves.

`deploy/production/nginx-production.conf.template` is the source of truth for
the three vhosts. It had drifted badly from the running config on KVM1, and
every difference was a regression waiting for the next redeploy:

- the apex had **no** `/internal/` guard at all, so a redeploy would have
  reopened a path that is deliberately 404 on every hostname
- `/submit-slot` was a 301 to the operations host, while production proxies it
  on the apex - candidates are handed apex links, and a redirect breaks the
  booking flow for any client that will not follow one on POST
- the apex had no `/assets/`, `/public/` or `/bookings/` proxies, so the
  submit-slot page would load and its "Confirm booking" POST would 404 into the
  static landing page
- neither pubsub location set `access_log off`, so a redeploy would have
  reintroduced the credential leak fixed in teleautomation-business#27 - the
  verification token rides in the query string because Pub/Sub push cannot send
  custom headers

These assertions are deliberately literal. The point is not elegance; it is
that anyone editing this file has to consciously change a test rather than
silently drop a line - which is exactly how the `/internal/` guard was lost
once already.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "deploy" / "production" / "nginx-production.conf.template"
CONF = TEMPLATE.read_text(encoding="utf-8")

INTERNAL_GUARD = "location ^~ /internal/ { return 404; }"
PUSH_LOCATION = "location = /api/gmail/pubsub/push"


def _uncommented() -> str:
    """The config with comment lines stripped, so a commented-out rule cannot
    satisfy an assertion that a rule is present."""
    return "\n".join(l for l in CONF.splitlines() if not l.strip().startswith("#"))


def test_the_template_is_structurally_balanced():
    body = _uncommented()
    assert body.count("{") == body.count("}"), "unbalanced braces would fail nginx -t"
    assert body.count("server {") >= 6, "expected http+https server blocks for all three hosts"


def test_every_hostname_keeps_the_internal_guard():
    """apex, marketing and operations - three vhosts, three guards.

    The apex one is the easiest to forget because its root is a static file, so
    a 200 there looks harmless. It is not: the apex also proxies provider
    callbacks, so the guard is what stops a widened location becoming a hole.
    """
    assert _uncommented().count(INTERNAL_GUARD) == 3


def test_submit_slot_is_proxied_on_the_apex_not_redirected():
    body = _uncommented()
    assert "location = /submit-slot" in body
    assert "location = /submit-slot/" in body
    assert "return 301 https://operations.teleautomation.online$request_uri" not in body, (
        "a redirect breaks apex links for clients that will not follow one on POST"
    )


def test_the_apex_serves_what_the_submit_slot_page_needs():
    """The page loading is not enough - the booking POST has to land too."""
    body = _uncommented()
    for route in ("location ^~ /assets/", "location ^~ /public/", "location ^~ /bookings/"):
        assert route in body, "%s missing: submit-slot would load but not function" % route


def test_the_apex_does_not_proxy_the_api_wholesale():
    """The apex is a static landing page with narrow exceptions. A broad /api/
    proxy would recombine the two services behind one hostname."""
    body = _uncommented()
    assert "location ^~ /api/ " not in body
    assert "location /api/ " not in body


def test_the_operations_host_exposes_the_push_endpoint_by_exact_match():
    """Google holds no dashboard session, so this one path is unauthenticated
    at the nginx layer. Exact match, so no sibling API path is opened up."""
    body = _uncommented()
    assert PUSH_LOCATION in body
    assert "location ^~ /api/gmail/pubsub/push" not in body, "must be exact match, not a prefix"


def test_no_pubsub_route_writes_the_token_to_a_log():
    """The regression guard for teleautomation-business#27.

    The verification token travels in the query string, so any pubsub location
    that logs writes a live credential to disk on every push.
    """
    blocks = []
    lines = CONF.splitlines()
    for i, line in enumerate(lines):
        if "gmail/pubsub" in line and line.strip().startswith("location"):
            blocks.append("\n".join(lines[i : i + 12]))

    assert blocks, "no pubsub location found at all"
    for block in blocks:
        assert "access_log off;" in block, (
            "a pubsub location without `access_log off` leaks the verification "
            "token into nginx's access log:\n%s" % block
        )


def test_the_push_endpoint_is_not_accidentally_authenticated():
    """It must stay reachable without a session - the app does the auth."""
    lines = CONF.splitlines()
    idx = next((i for i, l in enumerate(lines) if PUSH_LOCATION in l), None)
    assert idx is not None, "no `%s` block to check" % PUSH_LOCATION
    block = "\n".join(lines[idx : idx + 14])
    assert "auth_basic" not in block
    assert "satisfy" not in block
    assert "proxy_pass" in block
