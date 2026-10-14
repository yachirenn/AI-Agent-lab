"""Modul FAQ / Knowledge Base adapter.
Menggunakan RAG semantik dari app.agent.knowledge dengan fallback leksikal.
"""
from app.agent import knowledge


def search(query: str, top: int = 2) -> list[str]:
    return knowledge.search(query, top=top)