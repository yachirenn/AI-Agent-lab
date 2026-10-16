from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.agent import faq
from app.db import repo

logger = logging.getLogger(__name__)

_AGENT_TICKET_CATEGORIES = ("complaint", "points_issue", "transaction_issue", "other")


def _create_ticket(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    category = args.get("category")
    if category not in _AGENT_TICKET_CATEGORIES:
        return {"error": f"category harus salah satu dari {list(_AGENT_TICKET_CATEGORIES)}"}
    summary = " ".join(str(args.get("summary", "")).split())[:300]
    if len(summary) < 5:
        return {"error": "summary terlalu pendek"}
    ticket, created = repo.create_ticket(ctx.customer_id, 2, category, summary, "agent")   # level dikunci 2
    return {"ticket_id": ticket["id"], "created": created}


@dataclass(frozen=True)
class ToolContext:
    """Identitas diambil dari sesi chat oleh kode kita. LLM tidak punya jalur untuk mengubahnya."""

    customer_id: Any


def _points_balance(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"points_balance": repo.get_balance(ctx.customer_id)}


def _profile(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    c = repo.get_customer(ctx.customer_id) or {}
    return {
        "customer_code": c.get("customer_code"),
        "name": c.get("name"),
        "driver_type": c.get("driver_type"),
        "home_area": c.get("home_area"),
        "main_route": c.get("main_route"),
        "vehicles": [v["model"] for v in repo.list_vehicles(ctx.customer_id)],
        "points_balance": repo.get_balance(ctx.customer_id),
    }


def _recent_sessions(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = max(1, min(int(args.get("limit", 3)), 10))   # LLM boleh minta, server yang membatasi
    except (TypeError, ValueError):
        limit = 3
    return {
        "sessions": [
            {
                "station": s["station"],
                "charger": s["charger_id"],
                "kwh": str(s["kwh"]),
                "amount_idr": s["amount_idr"],
                "started_at": s["started_at"].isoformat(),
            }
            for s in repo.recent_sessions(ctx.customer_id, limit)
        ]
    }


def _search_faq(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"answers": faq.search(str(args.get("query", ""))[:200])}



def declarations() -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in TOOLS.values()]


def execute(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"tool '{name}' tidak ada"}
    try:
        return tool.run(ctx, args)
    except Exception:
        logger.exception("tool %s gagal", name)
        return {"error": "tool gagal dijalankan"}
    
    
def _my_preferences(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"preferences": {p["pref_key"]: p["pref_value"] for p in repo.list_preferences(ctx.customer_id)}}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


def _list_stations(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    area = args.get("area")
    if area and str(area).strip():
        stations = repo.find_stations_by_area(str(area).strip())
    else:
        stations = repo.list_stations()
    return {
        "stations": [
            {"code": s["code"], "name": s["name"], "area": s["area"]}
            for s in stations
        ]
    }


_NO_ARGS = {"type": "object", "properties": {}}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("get_points_balance", "Saldo poin loyalty customer yang sedang chat.", _NO_ARGS, _points_balance),
        Tool("get_customer_profile", "Profil customer yang sedang chat: nama, kendaraan, area, saldo poin.", _NO_ARGS, _profile),
        Tool(
            "get_recent_sessions",
            "Riwayat sesi charging terakhir customer yang sedang chat.",
            {"type": "object", "properties": {"limit": {"type": "integer", "description": "Jumlah sesi, 1-10"}}},
            _recent_sessions,
        ),
        Tool(
            "list_stations",
            "Daftar seluruh stasiun pengisian kendaraan listrik Enerva atau cari berdasarkan area (misal: Kuta, Sanur, Ubud, Canggu, Airport/Tuban).",
            {
                "type": "object",
                "properties": {
                    "area": {
                        "type": "string",
                        "description": "Nama area atau kota untuk filter stasiun (opsional, contoh: 'Sanur', 'Ubud', 'Canggu', 'Kuta')",
                    }
                },
            },
            _list_stations,
        ),
        Tool(
            "search_faq",
            "Cari informasi resmi Enerva: lokasi stasiun, jam operasional, fasilitas, Wi-Fi, tipe charger/konektor (CCS2/AC), tarif kWh, dan program reward.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            _search_faq,
        ),
        Tool(
            "create_support_ticket",
            "Buat tiket untuk tim Enerva jika customer menyampaikan komplain atau masalah yang tidak bisa kamu selesaikan. "
            "Bukan untuk keadaan darurat.",
            {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(_AGENT_TICKET_CATEGORIES)},
                    "summary": {"type": "string", "description": "Ringkasan masalah, 1-2 kalimat"},
                },
                "required": ["category", "summary"],
            },
            _create_ticket,
        ),
        Tool(
            "get_my_preferences",
            "Preferensi customer yang sedang chat (antrean, harga, fasilitas), untuk menyesuaikan saran.",
            _NO_ARGS,
            _my_preferences,
        ),
    ]
}