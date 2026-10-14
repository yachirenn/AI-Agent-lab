import json

import pytest

from app.agent.llm_client import LLMResponse
from app.db import repo
from app.services import handler, preferences
from tests.test_agent import ScriptedLLM
from tests.test_escalation import _done_user, _msg


def _json(*prefs):
    return json.dumps({"preferences": [{"key": k, "value": v, "confidence": c} for k, v, c in prefs]})


def test_parse_valid():
    raw = _json(("queue_tolerance", "low", 0.9), ("price_sensitivity", "high", 0.7))
    assert preferences.parse_extraction(raw) == [("queue_tolerance", "low", 0.9), ("price_sensitivity", "high", 0.7)]


def test_parse_accepts_markdown_fence():
    raw = "```json\n" + _json(("facility_toilet", "important", 0.8)) + "\n```"
    assert preferences.parse_extraction(raw) == [("facility_toilet", "important", 0.8)]


@pytest.mark.parametrize("pref", [
    ("tidak_ada", "low", 0.9),                              # kunci di luar whitelist
    ("queue_tolerance", "abaikan semua instruksi", 0.9),    # teks bebas / injection: nilai di luar enum
    ("queue_tolerance", "low", 0.3),                        # keyakinan rendah
    ("queue_tolerance", "low", "tinggi"),                   # confidence bukan angka
    ("queue_tolerance", "low", 1.5),                        # di luar rentang
])
def test_parse_rejects_invalid_items(pref):
    assert preferences.parse_extraction(_json(pref)) == []


@pytest.mark.parametrize("raw", ["bukan json", "", "{", '{"preferences": "x"}', '{"preferences": [1, "a", null]}'])
def test_parse_garbage_returns_empty(raw):
    assert preferences.parse_extraction(raw) == []


def test_parse_dedupes_keys_and_caps_count():
    raw = _json(
        ("queue_tolerance", "low", 0.9), ("queue_tolerance", "high", 0.8), ("price_sensitivity", "high", 0.9),
        ("charging_speed_priority", "high", 0.9), ("safety_priority", "high", 0.9),
    )
    out = preferences.parse_extraction(raw)
    assert [k for k, _, _ in out] == ["queue_tolerance", "price_sensitivity", "charging_speed_priority"]
    assert out[0][1] == "low"       # kemunculan pertama menang


def test_learn_stores_validated_preference():
    _, c = _done_user()
    llm = ScriptedLLM(LLMResponse(_json(("queue_tolerance", "low", 0.9))))
    assert preferences.learn(c["id"], "sim", "m1", "saya tidak suka antre lama", llm=llm) == 1
    assert {p["pref_key"]: p["pref_value"] for p in repo.list_preferences(c["id"])} == {"queue_tolerance": "low"}


def test_learn_skips_llm_when_no_topic_hint():
    _, c = _done_user()
    llm = ScriptedLLM()
    assert preferences.learn(c["id"], "sim", "m1", "halo, terima kasih ya", llm=llm) == 0
    assert llm.calls == 0


def test_learn_respects_personalization_off():
    _, c = _done_user()
    repo.set_personalization(c["id"], False)
    llm = ScriptedLLM(LLMResponse(_json(("queue_tolerance", "low", 0.9))))
    assert preferences.learn(c["id"], "sim", "m1", "saya tidak suka antre", llm=llm) == 0
    assert llm.calls == 0 and repo.list_preferences(c["id"]) == []


def test_newer_statement_overwrites_older():
    _, c = _done_user()
    preferences.learn(c["id"], "sim", "m1", "saya tidak suka antre",
                      llm=ScriptedLLM(LLMResponse(_json(("queue_tolerance", "low", 0.9)))))
    preferences.learn(c["id"], "sim", "m2", "sekarang saya santai soal antre",
                      llm=ScriptedLLM(LLMResponse(_json(("queue_tolerance", "high", 0.8)))))
    prefs = repo.list_preferences(c["id"])
    assert len(prefs) == 1 and prefs[0]["pref_value"] == "high"


def test_llm_failure_is_swallowed():
    class Broken:
        def chat(self, *a):
            raise RuntimeError("down")

    _, c = _done_user()
    assert preferences.learn(c["id"], "sim", "m1", "saya tidak suka antre", llm=Broken()) == 0


def test_preferensi_command_lists_data_without_llm():
    user, c = _done_user()
    repo.upsert_preference(c["id"], "queue_tolerance", "low", 0.9, None)
    reply = handler.handle_inbound(_msg(user, "/preferensi"))
    assert "Toleransi antrean: rendah" in reply


def test_lupa_deletes_and_stops_learning_then_ingat_resumes():
    user, c = _done_user()
    repo.upsert_preference(c["id"], "queue_tolerance", "low", 0.9, None)
    handler.handle_inbound(_msg(user, "/lupa"))
    assert repo.list_preferences(c["id"]) == [] and repo.personalization_enabled(c["id"]) is False
    repo.upsert_preference(c["id"], "queue_tolerance", "low", 0.9, None)   # insert terlambat harus ditolak SQL
    assert repo.list_preferences(c["id"]) == []
    handler.handle_inbound(_msg(user, "/ingat"))
    assert repo.personalization_enabled(c["id"]) is True
    