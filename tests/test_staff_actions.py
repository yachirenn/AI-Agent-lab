import pytest

from app.db import repo
from app.services import dispatcher, staff_tools
from tests.test_escalation import _done_user


def _ticket():
    _, c = _done_user()
    t, _ = repo.create_ticket(c["id"], 2, "complaint", "charger lambat", "rule")
    return t["id"]


def test_draft_does_not_send_anything(monkeypatch):
    monkeypatch.setattr(dispatcher, "send", lambda *a: pytest.fail("draf tidak boleh mengirim"))
    out = staff_tools.draft_reply(_ticket(), "Tim kami sedang memeriksa chargernya.", "budi")
    assert out["status"] == "pending_approval"
    assert len(repo.pending_drafts()) == 1


def test_only_one_approval_wins():
    draft = staff_tools.draft_reply(_ticket(), "Tim kami sedang memeriksa chargernya.", "budi")["draft_id"]
    assert repo.decide_draft(draft, True, "siti") is not None
    assert repo.decide_draft(draft, True, "andi") is None


def test_reopen_returns_failed_draft_to_queue():
    draft = staff_tools.draft_reply(_ticket(), "Tim kami sedang memeriksa chargernya.", "budi")["draft_id"]
    repo.decide_draft(draft, True, "siti")
    repo.reopen_draft(draft)
    assert [d["id"] for d in repo.pending_drafts()] == [draft]


def test_cannot_draft_for_resolved_ticket():
    tid = _ticket()
    repo.resolve_ticket(tid)
    with pytest.raises(LookupError):
        staff_tools.draft_reply(tid, "halo, apa kabar", "budi")


def test_pending_drafts_are_capped_per_ticket():
    tid = _ticket()
    for i in range(5):
        staff_tools.draft_reply(tid, f"draf nomor {i} untuk tiket", "budi")
    with pytest.raises(ValueError):
        staff_tools.draft_reply(tid, "draf ke enam yang harus ditolak", "budi")


@pytest.mark.parametrize("msg", ["", "abc", "x" * 501])
def test_message_length_is_enforced(msg):
    with pytest.raises(ValueError):
        staff_tools.draft_reply(_ticket(), msg, "budi")