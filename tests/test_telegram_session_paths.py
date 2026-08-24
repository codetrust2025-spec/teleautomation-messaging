from __future__ import annotations

from pathlib import Path

from core import config
from core import account_lifecycle, telegram_client
from core.session_manager import session_manager


def test_legacy_install_keeps_sessions_beside_application(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEGRAM_SESSION_DIR", raising=False)
    monkeypatch.delenv("MARKETING_DATA_DIR", raising=False)

    base_dir = tmp_path / "app"
    data_dir = tmp_path / "data"

    assert config._resolve_session_dir(
        base_dir=str(base_dir), data_dir=str(data_dir)
    ) == str(base_dir)


def test_marketing_data_root_makes_sessions_persistent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEGRAM_SESSION_DIR", raising=False)
    monkeypatch.setenv("MARKETING_DATA_DIR", str(tmp_path / "marketing-data"))

    data_dir = tmp_path / "marketing-data"

    assert config._resolve_session_dir(
        base_dir=str(tmp_path / "app"), data_dir=str(data_dir)
    ) == str(data_dir)


def test_explicit_session_root_wins(monkeypatch, tmp_path: Path) -> None:
    explicit = tmp_path / "telegram-sessions"
    monkeypatch.setenv("TELEGRAM_SESSION_DIR", str(explicit))
    monkeypatch.setenv("MARKETING_DATA_DIR", str(tmp_path / "marketing-data"))

    assert config._resolve_session_dir(
        base_dir=str(tmp_path / "app"), data_dir=str(tmp_path / "data")
    ) == str(explicit)


def test_session_filename_is_unchanged_under_configured_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "SESSION_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ACCOUNTS", {"account10": "session_account10"})

    assert config.telegram_session_base("account10") == str(
        tmp_path / "session_account10"
    )
    assert config.telegram_session_path("account10") == str(
        tmp_path / "session_account10.session"
    )


def test_runtime_discovery_uses_the_shared_persistent_root(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(config, "SESSION_DIR", str(tmp_path))

    expected_base = str(tmp_path / config.ACCOUNTS["account1"])
    assert telegram_client._main_session_base("account1") == expected_base
    assert account_lifecycle._main_session_base("account1") == expected_base
    assert session_manager.session_path("account1") == expected_base + ".session"
