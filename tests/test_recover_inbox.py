import sys

from scripts import recover_inbox


def test_recovery_success_closes_pool(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/enerva_test",
    )
    monkeypatch.setenv("RECOVERY_ALLOWED_DATABASE", "enerva_test")
    calls = []

    monkeypatch.setattr(recover_inbox.repo, "get_pool",
                        lambda: calls.append("open"))
    monkeypatch.setattr(recover_inbox.repo, "close_pool",
                        lambda: calls.append("close"))
    monkeypatch.setattr(recover_inbox.repo, "recover_dead_inbox_result",
                        lambda inbox_id: calls.append(inbox_id) or True)
    monkeypatch.setattr(sys, "argv", ["recover_inbox", "42"])

    assert recover_inbox.main() == 0
    assert calls == ["open", 42, "close"]


def test_recovery_not_eligible_closes_pool(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/enerva_test",
    )
    monkeypatch.setenv("RECOVERY_ALLOWED_DATABASE", "enerva_test")
    calls = []

    monkeypatch.setattr(recover_inbox.repo, "get_pool",
                        lambda: calls.append("open"))
    monkeypatch.setattr(recover_inbox.repo, "close_pool",
                        lambda: calls.append("close"))
    monkeypatch.setattr(recover_inbox.repo, "recover_dead_inbox_result",
                        lambda inbox_id: False)
    monkeypatch.setattr(sys, "argv", ["recover_inbox", "43"])

    assert recover_inbox.main() == 1
    assert calls == ["open", "close"]


def test_recovery_error_closes_pool(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/enerva_test",
    )
    monkeypatch.setenv("RECOVERY_ALLOWED_DATABASE", "enerva_test")
    calls = []

    monkeypatch.setattr(recover_inbox.repo, "get_pool",
                        lambda: calls.append("open"))
    monkeypatch.setattr(recover_inbox.repo, "close_pool",
                        lambda: calls.append("close"))

    def raise_error(inbox_id):
        raise RuntimeError("Simulasi kegagalan")

    monkeypatch.setattr(
        recover_inbox.repo, "recover_dead_inbox_result", raise_error
    )
    monkeypatch.setattr(sys, "argv", ["recover_inbox", "44"])

    assert recover_inbox.main() == 2
    assert calls == ["open", "close"]


def test_recovery_rejects_database_mismatch_before_opening_pool(monkeypatch):
    import pytest

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/enerva",
    )
    monkeypatch.setenv("RECOVERY_ALLOWED_DATABASE", "enerva_test")
    monkeypatch.setattr(sys, "argv", ["recover_inbox", "45"])

    def should_not_open_pool():
        pytest.fail("Pool tidak boleh dibuka untuk database yang tidak cocok")

    monkeypatch.setattr(recover_inbox.repo, "get_pool", should_not_open_pool)

    with pytest.raises(SystemExit) as exc:
        recover_inbox.main()

    assert exc.value.code == 2


def test_recovery_rejects_non_test_database_even_when_allowlist_matches(
    monkeypatch,
):
    import pytest

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test:test@localhost:5432/enerva",
    )
    monkeypatch.setenv("RECOVERY_ALLOWED_DATABASE", "enerva")
    monkeypatch.setattr(sys, "argv", ["recover_inbox", "46"])

    def should_not_open_pool():
        pytest.fail("Pool tidak boleh dibuka untuk database non-test")

    monkeypatch.setattr(recover_inbox.repo, "get_pool", should_not_open_pool)

    with pytest.raises(SystemExit) as exc:
        recover_inbox.main()

    assert exc.value.code == 2
