"""Static release-contract checks for the unified production Compose file."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.production.yml").read_text(encoding="utf-8")
# Bumped with the Compose anchor, deliberately in lockstep: the pin exists so
# an environment typo cannot label a different checkout as the approved
# release, and a test that tracked the file automatically would guard
# nothing. f952a08 adds the Gmail Pub/Sub push exemption
# (teleautomation-business#25).
OPERATIONS_RELEASE = "6c3688d2d90b1f00f3049bd78781a8f393cc013c"


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


def test_marketing_sessions_use_the_persistent_data_volume() -> None:
    assert "MARKETING_DATA_DIR: /var/lib/teleautomation-marketing" in COMPOSE
    assert "TELEGRAM_SESSION_DIR: /var/lib/teleautomation-marketing" in COMPOSE
    assert "marketing_data:/var/lib/teleautomation-marketing" in COMPOSE
