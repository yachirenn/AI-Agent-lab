import pytest
from app.agent import tools
from app.db import repo


def test_list_stations():
    stations = repo.list_stations()
    codes = {s["code"] for s in stations}
    assert "sunset-road" in codes
    assert "sanur-hub" in codes
    assert "ubud-central" in codes
    assert "canggu-coastal" in codes
    assert "airport-hub" in codes


def test_get_station_by_code():
    st = repo.get_station_by_code("sanur-hub")
    assert st is not None
    assert st["code"] == "sanur-hub"
    assert "Sanur" in st["name"]
    assert st["area"] == "Sanur"

    missing = repo.get_station_by_code("non-existent-station")
    assert missing is None


def test_find_stations_by_area():
    ubud_stations = repo.find_stations_by_area("Ubud")
    assert len(ubud_stations) >= 1
    assert ubud_stations[0]["code"] == "ubud-central"

    canggu_stations = repo.find_stations_by_area("canggu")
    assert len(canggu_stations) >= 1
    assert canggu_stations[0]["code"] == "canggu-coastal"


def test_tool_list_stations():
    ctx = tools.ToolContext(customer_id="00000000-0000-0000-0000-000000000001")
    
    # Ambil semua stasiun
    res_all = tools.execute(ctx, "list_stations", {})
    assert "stations" in res_all
    codes = {s["code"] for s in res_all["stations"]}
    assert "sunset-road" in codes
    assert "sanur-hub" in codes

    # Filter berdasarkan area
    res_area = tools.execute(ctx, "list_stations", {"area": "Sanur"})
    assert "stations" in res_area
    assert len(res_area["stations"]) >= 1
    assert res_area["stations"][0]["code"] == "sanur-hub"


def test_agent_calls_list_stations():
    from app.agent import loop
    from app.agent.llm_client import LLMResponse, ToolCall
    from tests.test_agent import ScriptedLLM

    c = repo.register_customer("sim", "u-station-agent-test")
    llm = ScriptedLLM(
        LLMResponse("", [ToolCall("list_stations", {"area": "Sanur"})]),
        lambda msgs: LLMResponse(f"Ada stasiun di: {msgs[-1]['result']['stations'][0]['name']}")
    )
    reply = loop.run_agent(c["id"], "ada stasiun di sanur?", llm=llm)
    assert "Sanur Port Hub" in reply

