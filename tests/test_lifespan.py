import pytest
from starlette.testclient import TestClient

from app.api.main import app
from app.db import repo


def test_repo_close_pool():
    # Pastikan pool bisa dibuka
    p1 = repo.get_pool()
    assert p1 is not None
    assert repo._pool is not None

    # Tutup pool
    repo.close_pool()
    assert repo._pool is None

    # Idempotent (aman dipanggil berulang)
    repo.close_pool()
    assert repo._pool is None

    # Bisa dipanggil lagi dan membuka pool baru
    p2 = repo.get_pool()
    assert p2 is not None
    assert repo._pool is not None


def test_fastapi_lifespan_context():
    # Saat masuk context TestClient, lifespan dijalankan (startup -> shutdown)
    repo.close_pool()
    assert repo._pool is None

    with TestClient(app) as client:
        # Saat client aktif, pool sudah diinisialisasi
        assert repo._pool is not None
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    # Setelah keluar context, lifespan menutup pool
    assert repo._pool is None
