"""Offline tests for healthcheck/tools.py, healthcheck/ai.py and mcp_server.py. No network, no API key."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from healthcheck import ai, tools  # noqa: E402

FIVE = {"lookup_barcode", "check_recalls", "drug_targets", "food_drug_interactions", "local_health_briefing"}


def _boom(*args, **kwargs):
    raise RuntimeError("upstream down")


@pytest.fixture
def broken_modules(monkeypatch):
    """Replace the other engineers' modules with fakes whose functions raise."""
    import healthcheck

    spec = {
        "products": ("identify", "from_name"),
        "recalls": ("check",),
        "drugs": ("profile",),
        "interactions": ("analyze",),
        "local": ("briefing",),
    }
    for mod_name, funcs in spec.items():
        fake = types.ModuleType(f"healthcheck.{mod_name}")
        for func in funcs:
            setattr(fake, func, _boom)
        monkeypatch.setitem(sys.modules, f"healthcheck.{mod_name}", fake)
        monkeypatch.setattr(healthcheck, mod_name, fake, raising=False)


def test_tools_return_error_instead_of_raising(broken_modules):
    calls = [
        tools.lookup_barcode("012345678905"),
        tools.check_recalls("peanut butter", "food"),
        tools.drug_targets("warfarin"),
        tools.food_drug_interactions("grapefruit juice", ["simvastatin"]),
        tools.local_health_briefing("CA"),
    ]
    for result in calls:
        assert "upstream down" in result["error"]
        json.dumps(result)


def test_lookup_barcode_rejects_garbage():
    assert "error" in tools.lookup_barcode("not a barcode")


def test_compact_keeps_results_small():
    big = {"recalls": [{"title": "x" * 2000, "n": i} for i in range(200)]}
    assert len(json.dumps(tools._compact(big))) <= tools.MAX_CHARS


def test_tool_registry_matches_schemas():
    assert set(tools.TOOLS) == FIVE == set(ai.TOOL_INPUTS)
    for spec in ai._tool_specs():
        assert len(spec["description"]) > 80


# ---- fake Anthropic client -------------------------------------------------


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for block in self.message.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)

    @property
    def text_stream(self):
        return (b.text for b in self.message.content if b.type == "text")

    def get_final_message(self):
        return self.message


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def stream(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return FakeStream(self.responses.pop(0))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)
        self.beta = SimpleNamespace(messages=self.messages)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _msg(content, stop_reason="end_turn"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(ai, "_api_key", "test-key")


def test_chat_runs_tool_then_answers(monkeypatch, with_key):
    ran = []

    def fake_interactions(food, drugs):
        ran.append((food, drugs))
        return {"interactions": [{"food": "Grapefruit", "via": "CYP3A4", "drug": "simvastatin"}]}

    monkeypatch.setitem(tools.TOOLS, "food_drug_interactions", fake_interactions)
    tool_use = SimpleNamespace(
        type="tool_use",
        id="toolu_1",
        name="food_drug_interactions",
        input={"food": "grapefruit juice", "drugs": ["simvastatin"]},
    )
    client = FakeClient(
        [
            _msg([tool_use], "tool_use"),
            _msg([_text("Grapefruit inhibits CYP3A4, which clears simvastatin.")]),
        ]
    )
    monkeypatch.setattr(ai, "_client", lambda: client)
    seen = []

    out = "".join(
        ai.chat(
            [{"role": "user", "content": "Grapefruit with simvastatin?"}],
            on_tool=lambda name, args: seen.append((name, args)),
        )
    )

    assert ran == [("grapefruit juice", ["simvastatin"])]
    assert seen == [("food_drug_interactions", {"food": "grapefruit juice", "drugs": ["simvastatin"]})]
    assert "Grapefruit inhibits CYP3A4" in out
    first, second = client.messages.requests
    assert first["model"] == ai.MODEL and first["system"] == ai.CHAT_SYSTEM
    assert first["output_config"] == {"effort": "medium"}
    assert "tool_choice" not in first and "temperature" not in first and "thinking" not in first
    assert {t["name"] for t in first["tools"]} == FIVE
    # The follow-up request carries the assistant turn and one user message with the result.
    assert second["messages"][-2]["role"] == "assistant"
    results = second["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["toolu_1"]
    assert "CYP3A4" in results[0]["content"]


def test_chat_caps_tool_rounds(monkeypatch, with_key):
    monkeypatch.setitem(tools.TOOLS, "drug_targets", lambda drug: {"name": drug})
    loop = [
        _msg([SimpleNamespace(type="tool_use", id=f"t{i}", name="drug_targets", input={"drug": "x"})], "tool_use")
        for i in range(20)
    ]
    client = FakeClient(loop)
    monkeypatch.setattr(ai, "_client", lambda: client)
    out = "".join(ai.chat([{"role": "user", "content": "loop"}]))
    assert len(client.messages.requests) == ai.MAX_TOOL_ROUNDS + 1
    assert "maximum number of lookups" in out


def test_chat_invalid_tool_input_is_reported_not_run(monkeypatch, with_key):
    ran = []
    monkeypatch.setitem(tools.TOOLS, "drug_targets", lambda drug: ran.append(drug) or {})
    bad = SimpleNamespace(type="tool_use", id="t1", name="drug_targets", input={"drugz": 3})
    client = FakeClient([_msg([bad], "tool_use"), _msg([_text("done")])])
    monkeypatch.setattr(ai, "_client", lambda: client)
    assert "done" in "".join(ai.chat([{"role": "user", "content": "q"}]))
    assert ran == []
    assert client.messages.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_chat_refusal_raises(monkeypatch, with_key):
    monkeypatch.setattr(ai, "_client", lambda: FakeClient([_msg([], "refusal")]))
    with pytest.raises(ai.AIUnavailable):
        list(ai.chat([{"role": "user", "content": "q"}]))


def test_explain_streams_text(monkeypatch, with_key):
    client = FakeClient([_msg([_text("No recall found in the sources that answered.")])])
    monkeypatch.setattr(ai, "_client", lambda: client)
    out = "".join(ai.explain({"name": "juice"}, {"recalls": []}, {"interactions": []}))
    assert "No recall found" in out
    request = client.messages.requests[0]
    assert request["system"] == ai.EXPLAIN_SYSTEM and request["output_config"] == {"effort": "low"}


def test_read_photo_parses_structured_output(monkeypatch, with_key):
    payload = {"medications": ["warfarin"], "foods": [], "barcode": "0 12345 67890 5", "notes": "A pill bottle."}
    client = FakeClient([_msg([_text(json.dumps(payload))])])
    monkeypatch.setattr(ai, "_client", lambda: client)
    result = ai.read_photo(b"\xff\xd8fake")
    assert result == {"medications": ["warfarin"], "foods": [], "barcode": "012345678905", "notes": "A pill bottle."}
    request = client.messages.requests[0]
    assert request["output_config"]["effort"] == "low"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["messages"][0]["content"][0]["type"] == "image"


def test_api_errors_become_ai_unavailable(monkeypatch, with_key):
    import anthropic
    import httpx2 as httpx

    class Failing(FakeMessages):
        def create(self, **kwargs):
            raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    client = FakeClient([])
    client.messages = client.beta.messages = Failing([])
    monkeypatch.setattr(ai, "_client", lambda: client)
    with pytest.raises(ai.AIUnavailable, match="reach Claude"):
        ai.read_photo(b"abc")


def test_ai_functions_raise_without_key(monkeypatch):
    monkeypatch.setattr(ai, "_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert ai.available() is False
    with pytest.raises(ai.AIUnavailable):
        ai.read_photo(b"abc")
    with pytest.raises(ai.AIUnavailable):
        ai.explain({}, {}, {})
    with pytest.raises(ai.AIUnavailable):
        ai.chat([{"role": "user", "content": "hi"}])
    ai.configure("sk-test")
    assert ai.available() is True
    ai.configure(None)
    assert ai.available() is False


def test_mcp_server_lists_exactly_five_tools():
    import mcp_server

    listed = asyncio.run(mcp_server.mcp.list_tools())
    assert {t.name for t in listed} == FIVE
    for tool in listed:
        assert tool.description and len(tool.description) > 80
