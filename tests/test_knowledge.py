from __future__ import annotations

import pytest

from app.agent import knowledge, tools
from app.agent.embeddings import MockEmbedder, cosine_similarity
from app.db import repo


@pytest.fixture(autouse=True)
def mock_embedder(monkeypatch):
    embedder = MockEmbedder(dimension=768)
    monkeypatch.setattr(knowledge, "get_embedder", lambda: embedder)
    return embedder


def test_mock_embedder_dimension_and_determinism():
    emb = MockEmbedder(dimension=768)
    v1 = emb.embed_text("tarif charging per kwh")
    v2 = emb.embed_text("tarif charging per kwh")
    assert len(v1) == 768
    assert v1 == v2
    assert cosine_similarity(v1, v2) == pytest.approx(1.0)


def test_cosine_similarity_edge_cases():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == pytest.approx(0.0)


def test_upsert_and_get_knowledge_item():
    item = repo.upsert_knowledge_item(
        slug="test-sunset",
        title="Enerva Sunset Road",
        category="station",
        content="Buka 24 jam di Kuta Bali.",
        embedding=[0.5] * 768,
        metadata={"city": "Kuta"},
    )
    assert item["slug"] == "test-sunset"
    assert item["title"] == "Enerva Sunset Road"

    fetched = repo.get_knowledge_item("test-sunset")
    assert fetched is not None
    assert fetched["content"] == "Buka 24 jam di Kuta Bali."
    assert fetched["metadata"] == {"city": "Kuta"}
    assert len(fetched["embedding"]) == 768

    # Update (upsert)
    updated = repo.upsert_knowledge_item(
        slug="test-sunset",
        title="Enerva Sunset Road (Updated)",
        category="station",
        content="Buka 24 jam dengan cafe.",
        metadata={"city": "Kuta", "cafe": True},
    )
    assert updated["title"] == "Enerva Sunset Road (Updated)"
    fetched_after = repo.get_knowledge_item("test-sunset")
    assert fetched_after["title"] == "Enerva Sunset Road (Updated)"
    assert fetched_after["content"] == "Buka 24 jam dengan cafe."
    assert fetched_after["metadata"]["cafe"] is True


def test_delete_and_count_knowledge_items():
    assert repo.count_knowledge_items() == 0
    repo.upsert_knowledge_item(
        slug="item-1",
        title="Item 1",
        category="faq",
        content="Konten 1",
    )
    assert repo.count_knowledge_items() == 1
    assert repo.delete_knowledge_item("item-1") is True
    assert repo.count_knowledge_items() == 0
    assert repo.delete_knowledge_item("item-1") is False


def test_semantic_ranking_with_embeddings(mock_embedder):
    knowledge.upsert_document(
        slug="doc-tarif",
        title="Tarif Charging Enerva",
        category="pricing",
        content="Biaya isi daya listrik mobil adalah Rp 2.475 per kWh.",
    )
    knowledge.upsert_document(
        slug="doc-wifi",
        title="Akses Wi-Fi Gratis",
        category="station",
        content="Koneksi internet tanpa bayar 30 menit di area lounge.",
    )

    results = knowledge.search_detailed("Tarif per kWh mobil", top=1)
    assert len(results) == 1
    assert results[0]["slug"] == "doc-tarif"

    results_wifi = knowledge.search_detailed("Koneksi internet lounge", top=1)
    assert len(results_wifi) == 1
    assert results_wifi[0]["slug"] == "doc-wifi"


def test_lexical_fallback_when_embedding_is_none():
    repo.upsert_knowledge_item(
        slug="doc-manual",
        title="Prosedur Stop Darurat",
        category="troubleshooting",
        content="Tekan tombol merah Emergency Stop di dispenser.",
        embedding=None,
    )

    results = knowledge.search_detailed("Emergency Stop", top=1)
    assert len(results) == 1
    assert results[0]["slug"] == "doc-manual"


def test_static_fallback_when_db_is_empty():
    assert repo.count_knowledge_items() == 0
    answers = knowledge.search("berapa tarif per kwh")
    assert len(answers) > 0
    assert "2.475" in answers[0] or "tarif" in answers[0].lower()


def test_tools_search_faq_integration():
    knowledge.upsert_document(
        slug="doc-konektor",
        title="Spesifikasi CCS2",
        category="station",
        content="Charger DC mendukung CCS2 120 kW.",
    )
    ctx = tools.ToolContext(customer_id="cust-123")
    res = tools.execute(ctx, "search_faq", {"query": "Spesifikasi CCS2"})
    assert "answers" in res
    assert len(res["answers"]) > 0
    assert "CCS2" in res["answers"][0]
