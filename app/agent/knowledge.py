from __future__ import annotations

import logging
import re
from typing import Any

from app.agent.embeddings import cosine_similarity, get_embedder
from app.db import repo

logger = logging.getLogger(__name__)

# Fallback darurat jika database knowledge base masih kosong
_STATIC_FALLBACK: list[tuple[str, str]] = [
    ("jam buka operasional 24 jam", "Stasiun Enerva Sunset Road beroperasi 24 jam setiap hari."),
    (
        "wifi gratis password akses",
        "Wi-Fi gratis 30 menit (SSID: Enerva-Guest) tersedia setelah registrasi dan verifikasi nomor.",
    ),
    (
        "poin reward tukar redeem",
        "Poin dihitung otomatis dari kWh charging (1 kWh = 10 poin) dan dapat ditukar dengan voucher charging atau merchant partner.",
    ),
    (
        "harga tarif biaya per kwh",
        "Tarif resmi pengisian daya Enerva Sunset Road adalah Rp 2.475 per kWh (belum termasuk PPN & biaya administrasi).",
    ),
    (
        "tipe charger konektor ccs2 ac dc fast charging",
        "Enerva Sunset Road menyediakan DC Fast Charger CCS2 (60 kW dan 120 kW) serta AC Type 2 (22 kW).",
    ),
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def search(query: str, top: int = 3, min_similarity: float = 0.45) -> list[str]:
    """Pencarian RAG semantik (Semantic Vector Search) dengan fallback leksikal & static.
    Mengembalikan daftar teks jawaban yang siap dibaca oleh LLM."""
    detailed = search_detailed(query, top=top, min_similarity=min_similarity)
    if detailed:
        return [f"[{d['title']}] {d['content']}" for d in detailed]

    # Fallback ke static jika database kosong atau tidak ada hasil sama sekali
    q = _tokens(query)
    scored = sorted(((len(q & _tokens(k)), a) for k, a in _STATIC_FALLBACK), reverse=True)
    return [a for score, a in scored[:top] if score > 0]


def search_detailed(
    query: str,
    top: int = 3,
    min_similarity: float = 0.45,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Pencarian RAG mendalam yang mengembalikan metadata lengkap dan skor kemiripan."""
    clean_q = " ".join(query.strip().split())
    if not clean_q or len(clean_q) < 2:
        return []

    embedder = get_embedder()
    query_vec: list[float] | None = None
    try:
        query_vec = embedder.embed_text(clean_q)
    except Exception as exc:
        logger.warning("gagal membuat query embedding: %s, menggunakan pencarian leksikal", exc)

    # 1. Semantic Search jika query_vec tersedia
    if query_vec and any(x != 0.0 for x in query_vec):
        items = repo.all_knowledge_embeddings()
        if category:
            items = [it for it in items if it.get("category") == category]

        if items:
            q_tokens = _tokens(clean_q)
            scored: list[tuple[float, dict[str, Any]]] = []
            for item in items:
                emb = item.get("embedding")
                if not emb:
                    continue
                sim = cosine_similarity(query_vec, emb)
                # Sedikit bonus jika ada kata kunci di judul
                title_tokens = _tokens(item.get("title", ""))
                lexical_bonus = 0.08 if (q_tokens & title_tokens) else 0.0
                total_score = sim + lexical_bonus
                if total_score >= min_similarity:
                    scored.append((total_score, {**item, "similarity": round(sim, 4), "score": round(total_score, 4)}))

            scored.sort(key=lambda x: x[0], reverse=True)
            if scored:
                return [item for _, item in scored[:top]]

    # 2. Fallback Leksikal Full-Text Search via PostgreSQL
    lexical_items = repo.search_knowledge_lexical(clean_q, limit=top)
    if lexical_items:
        return [
            {**it, "similarity": round(float(it.get("rank", 0.1)), 4), "score": round(float(it.get("rank", 0.1)), 4)}
            for it in lexical_items
        ]

    return []


def upsert_document(
    *,
    slug: str,
    title: str,
    category: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper untuk menambah/memperbarui dokumen knowledge base lengkap dengan embedding-nya."""
    embedder = get_embedder()
    # Gabungkan judul dan konten untuk representasi semantik yang kaya
    text_to_embed = f"{title}\n{content}"
    try:
        embedding = embedder.embed_text(text_to_embed)
    except Exception as exc:
        logger.warning("gagal membuat embedding untuk '%s': %s", slug, exc)
        embedding = None

    return repo.upsert_knowledge_item(
        slug=slug,
        title=title,
        category=category,
        content=content,
        embedding=embedding,
        metadata=metadata or {},
    )
