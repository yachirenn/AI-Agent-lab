import pytest

from scripts.mcp_server import mcp

EXPECTED_TOOLS = {
    "overview", "list_stations", "station_performance", "list_inactive_customers", "open_tickets",
    "customer_360", "churn_risk_analysis", "preference_summary", "search_knowledge_base", "draft_reply",
}
# LLM tidak boleh mengirim pesan ke customer atau menutup tiket. Itu hanya dilakukan manusia di dashboard.
FORBIDDEN_TOOLS = {"reply_ticket", "resolve_ticket"}


@pytest.mark.anyio
async def test_mcp_server_tools_registered():
    names = {t.name for t in await mcp.list_tools()}
    assert EXPECTED_TOOLS <= names
    assert not (FORBIDDEN_TOOLS & names), f"tool tulis berbahaya terdaftar: {FORBIDDEN_TOOLS & names}"


@pytest.mark.anyio
async def test_mcp_server_resources_registered():
    uris = {str(r.uri) for r in await mcp.list_resources()}
    assert {"enerva://stations", "enerva://kpis/overview", "enerva://sop/emergency"} <= uris


@pytest.mark.anyio
async def test_mcp_server_prompts_registered():
    names = {p.name for p in await mcp.list_prompts()}
    assert {"incident_triage", "daily_executive_standup", "customer_retention_pitch"} <= names


@pytest.mark.anyio
async def test_prompts_only_reference_existing_tools():
    """Prompt yang menyuruh model memanggil tool fiktif adalah bug diam-diam."""
    import re

    tool_names = {t.name for t in await mcp.list_tools()}
    for p in await mcp.list_prompts():
        args = {a.name: "1" if a.name == "ticket_id" else "ENV-000001" for a in (p.arguments or [])}
        text = str((await mcp.get_prompt(p.name, args)))
        for referenced in re.findall(r"tool '([a-z_0-9]+)", text):
            assert referenced in tool_names, f"prompt {p.name} merujuk tool yang tidak ada: {referenced}"