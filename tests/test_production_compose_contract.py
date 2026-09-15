"""Static release-contract checks for the unified production Compose file."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
# Bumped with the Compose anchor, deliberately in lockstep: the pin exists so
# an environment typo cannot label a different checkout as the approved
# release, and a test that tracked the file automatically would guard
# nothing. f952a08 adds the Gmail Pub/Sub push exemption
# (teleautomation-business#25).
OPERATIONS_RELEASE = "d3d1d83a9e78c57c262f7f3ad5890c583d2a7d86"


def test_production_compose_is_the_unified_stack() -> None:
    assert "name: teleautomation-production" in COMPOSE
    for service in (
        "marketing-db",
        "operations-db",
        "marketing-migrate",
        "operations-migrate",
        "marketing-api",
        "operations-api",
    ):
        assert f"  {service}:" in COMPOSE


def test_operations_release_is_pinned_for_both_images() -> None:
    assert f"operations: &operations-release {OPERATIONS_RELEASE}" in COMPOSE
    assert COMPOSE.count("RELEASE_SHA: *operations-release") == 2


def test_operations_calls_marketing_by_private_service_name() -> None:
    assert "MESSAGING_INTERNAL_URL: http://marketing-api:8000" in COMPOSE
    assert "OPERATIONS_INTERNAL_URL: http://operations-api:8000" in COMPOSE


def test_company_payment_receiver_environment_is_explicit() -> None:
    required = (
        "COMPANY_PAYMENT_UPI_IDS: ${COMPANY_PAYMENT_UPI_IDS:?}",
        "COMPANY_PAYMENT_PHONE_NUMBERS: ${COMPANY_PAYMENT_PHONE_NUMBERS:-}",
        "COMPANY_PAYMENT_ACCOUNT_NUMBERS: ${COMPANY_PAYMENT_ACCOUNT_NUMBERS:-}",
        "COMPANY_PAYMENT_RECEIVER_NAMES: ${COMPANY_PAYMENT_RECEIVER_NAMES:?}",
    )
    for declaration in required:
        assert declaration in COMPOSE


def test_operations_attendance_network_policy_is_server_side_and_explicit() -> None:
    for declaration in (
        "OPERATIONS_OFFICE_NETWORK_CIDRS: ${OPERATIONS_OFFICE_NETWORK_CIDRS:-}",
        "OPERATIONS_TRUSTED_PROXY_CIDRS: ${OPERATIONS_TRUSTED_PROXY_CIDRS:-}",
        "OPERATIONS_ATTENDANCE_EFFECTIVE_DATE: ${OPERATIONS_ATTENDANCE_EFFECTIVE_DATE:-}",
    ):
        assert declaration in COMPOSE


def test_marketing_sessions_use_the_persistent_data_volume() -> None:
    assert "MARKETING_DATA_DIR: /var/lib/teleautomation-marketing" in COMPOSE
    assert "TELEGRAM_SESSION_DIR: /var/lib/teleautomation-marketing" in COMPOSE
    assert "marketing_data:/var/lib/teleautomation-marketing" in COMPOSE


def test_operations_image_comes_from_the_release_file_or_the_legacy_name() -> None:
    """CI deploys name a digest-pinned image in the host release file. Without
    that file the default is the name the host build has always produced, so
    scripts/fix_and_deploy.sh keeps working unchanged."""
    assert "image: ${OPERATIONS_IMAGE:-teleautomation-production-operations-api}" in COMPOSE
    assert COMPOSE.count("${OPERATIONS_IMAGE") == 1


def test_operations_api_is_seen_healthy_seconds_after_a_restart() -> None:
    block = COMPOSE[COMPOSE.index("  operations-api:"):COMPOSE.index("\nvolumes:")]
    assert "start_period: 90s" in block
    assert "start_interval: 2s" in block
    # The steady-state probe is unchanged.
    assert "interval: 15s" in block and "retries: 10" in block

