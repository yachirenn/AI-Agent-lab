import pytest

from app.db import repo
from app.services import customer360
from tests.test_inactivity import _customer, _sessions


@pytest.mark.parametrize("kwargs,expected", [
    (dict(days_since_last=20, median_gap_days=1, sessions=10, has_open_alert=True), "high"),
    (dict(days_since_last=2, median_gap_days=1, sessions=3, has_open_alert=False), "unknown"),
    (dict(days_since_last=1, median_gap_days=1, sessions=10, has_open_alert=False), "low"),
    (dict(days_since_last=3, median_gap_days=2, sessions=10, has_open_alert=False), "medium"),
    (dict(days_since_last=None, median_gap_days=None, sessions=0, has_open_alert=False), "unknown"),
])
def test_churn_risk_rules(kwargs, expected):
    assert customer360.churn_risk(**kwargs) == expected


def test_kpis_counts_active_repeat_and_retained():
    _, a = _customer()
    _sessions(a, [1, 2, 40])      # aktif, repeat, dan juga aktif di periode sebelumnya
    _, b = _customer()
    _sessions(b, [5])             # aktif, bukan repeat
    _, c = _customer()
    _sessions(c, [40])            # hanya periode sebelumnya: tidak retained

    k = repo.dashboard_kpis(30)
    assert k["registered"] == 3
    assert k["active_drivers"] == 2
    assert k["repeat_drivers"] == 1
    assert k["prev_active"] == 2 and k["retained"] == 1
    assert k["total_kwh"] == 30.0   # 3 sesi x 10 kWh di 30 hari terakhir


def test_customer_360_profile():
    _, cid = _customer()
    _sessions(cid, [1, 2, 3, 4, 5])
    repo.award_points(cid, 100, "charging", "t1")
    code = repo.get_customer(cid)["customer_code"]

    p = customer360.get(code)
    assert p["total_sessions"] == 5 and p["kwh_30d"] == 50
    assert p["visits_per_week"] == pytest.approx(5 / 4)
    assert p["points"] == 100
    assert p["status"] == "active" and p["churn_risk"] == "low"
    assert p["preferred_station"] == "Enerva Sunset Road"


def test_unknown_customer_returns_none():
    assert customer360.get("ENV-999999") is None