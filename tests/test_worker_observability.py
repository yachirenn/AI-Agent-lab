from __future__ import annotations

import pytest

from app.agent import knowledge, tools
from app.agent.embeddings import MockEmbedder
from app.db import repo


@pytest.fixture(autouse=True)
def mock_embedder(monkeypatch):
    embedder = MockEmbedder(dimension=768)
    monkeypatch.setattr(knowledge, "get_embedder", lambda: embedder)
    return embedder


def test_inbox_stats_and_dead_inbox():
    # 1. Enqueue 2 inbox messages
    repo.enqueue_inbox(
        channel="telegram",
        user_id="u1",
        chat_id="c1",
        message_id="m1",
        body="Pesan pertama",
    )
    repo.enqueue_inbox(
        channel="whatsapp",
        user_id="u2",
        chat_id="c2",
        message_id="m2",
        body="Pesan kedua",
    )

    stats = repo.inbox_stats()
    assert len(stats) >= 2
    statuses = {s["status"] for s in stats}
    assert "pending" in statuses
    channels = {s["channel"] for s in stats}
    assert "telegram" in channels and "whatsapp" in channels

    # Tidak ada dead inbox di awal
    assert repo.dead_inbox() == []

    # 2. Klaim dan buat 1 pesan dead
    claimed = repo.claim_inbox(limit=1, lock_seconds=60)
    assert len(claimed) == 1
    item = claimed[0]

    dead_status = repo.fail_inbox(
        item["id"],
        error="Gagal fatal koneksi AI",
        claim_token=item["claim_token"],
        attempts=6,
        max_attempts=6,
        permanent=True,
    )
    assert dead_status == "dead"

    dead_items = repo.dead_inbox()
    assert len(dead_items) == 1
    dead = dead_items[0]
    assert dead["id"] == item["id"]
    assert dead["channel"] == item["channel"]
    assert "Gagal fatal" in dead["last_error"]


def test_rag_degradation_modes_and_metadata():
    # Mode 1: Static Fallback saat DB kosong
    assert repo.count_knowledge_items() == 0
    res_static = knowledge.search_with_metadata("berapa tarif per kwh")
    assert res_static["mode"] == "static_fallback"
    assert res_static["degraded"] is True
    assert len(res_static["answers"]) > 0
    assert any("2.475" in a or "tarif" in a.lower() for a in res_static["answers"])
    assert res_static["results"][0]["source"] == "static_fallback"

    # Mode 2: Lexical Fallback saat dokumen ada tapi tanpa embedding
    repo.upsert_knowledge_item(
        slug="sop-darurat-lexical",
        title="Prosedur Tombol Darurat Manual",
        category="troubleshooting",
        content="Tekan tombol merah emergency stop pada unit pengisi daya.",
        embedding=None,
    )
    res_lexical = knowledge.search_with_metadata("Tombol Darurat Manual")
    assert res_lexical["mode"] == "lexical"
    assert res_lexical["degraded"] is True
    assert len(res_lexical["results"]) > 0
    assert res_lexical["results"][0]["slug"] == "sop-darurat-lexical"
    assert res_lexical["results"][0]["source"] == "lexical"

    # Mode 3: Semantic Search saat dokumen memiliki embedding
    knowledge.upsert_document(
        slug="info-ccs2-semantic",
        title="Dukungan Charger CCS2 Fast Charging",
        category="station",
        content="Stasiun Sunset Road menyediakan DC Fast Charging CCS2 hingga 120 kW.",
    )
    res_semantic = knowledge.search_with_metadata("Charger CCS2 Fast Charging")
    assert res_semantic["mode"] == "semantic"
    assert res_semantic["degraded"] is False
    assert len(res_semantic["results"]) > 0
    assert res_semantic["results"][0]["slug"] == "info-ccs2-semantic"
    assert res_semantic["results"][0]["source"] == "semantic"


def test_tool_search_faq_returns_degradation_metadata():
    knowledge.upsert_document(
        slug="info-wifi-lounge",
        title="Fasilitas Wi-Fi Lounge",
        category="station",
        content="Wi-Fi gratis 30 menit di ruang tunggu stasiun Enerva.",
    )
    ctx = tools.ToolContext(customer_id="cust-observability-1")
    tool_res = tools.execute(ctx, "search_faq", {"query": "Wi-Fi gratis lounge"})

    assert "answers" in tool_res
    assert "mode" in tool_res
    assert "degraded" in tool_res
    assert tool_res["mode"] == "semantic"
    assert tool_res["degraded"] is False
    assert any("Wi-Fi" in a for a in tool_res["answers"])
