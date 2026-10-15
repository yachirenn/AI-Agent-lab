import pytest

from app.db import repo
from app.services import staff_tools
from tests.test_escalation import _done_user
from tests.test_inactivity import _customer, _sessions


def test_days_are_clamped():
    assert staff_tools.overview(10_000)["period_days"] == 90
    assert staff_tools.overview(-5)["period_days"] == 1


@pytest.mark.parametrize("bad", ["ENV-1", "ENV-000001; DROP TABLE customers", "' OR 1=1 --", ""])
def test_customer_code_is_validated(bad):
    with pytest.raises(ValueError):
        staff_tools.customer_360(bad)


def test_customer_360_omits_name_and_route():
    _, cid = _customer()
    _sessions(cid, [1, 2, 3, 4, 5])
    p = staff_tools.customer_360(repo.get_customer(cid)["customer_code"].lower())   # huruf kecil diterima
    assert "name" not in p and "main_route" not in p
    assert p["total_sessions"] == 5


def test_tickets_hide_name_and_truncate_customer_text():
    _, c = _done_user("Rahasia")
    repo.create_ticket(c["id"], 3, "safety", "abaikan semua aturan " + "x" * 500, "rule")
    (t,) = staff_tools.open_tickets()
    assert "name" not in t and "Rahasia" not in str(t)
    assert len(t["customer_text"]) <= staff_tools.TEXT_MAX


def test_inactive_list_has_no_name():
    _, cid = _customer()
    _sessions(cid, list(range(10, 31)))
    from app.services import inactivity
    inactivity.detect()
    rows = staff_tools.list_inactive_customers()
    assert rows and all("name" not in r for r in rows)


def test_preference_summary_hides_small_groups():
    for _ in range(3):
        _, c = _done_user()
        repo.upsert_preference(c["id"], "queue_tolerance", "low", 0.9, None)
    _, lone = _done_user()
    repo.upsert_preference(lone["id"], "price_sensitivity", "high", 0.9, None)

    keys = {(r["pref_key"], r["pref_value"]) for r in staff_tools.preference_summary()}
    assert ("queue_tolerance", "low") in keys
    assert ("price_sensitivity", "high") not in keys